from datetime import UTC, datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.domain.exceptions.base import InvalidDomainTimestampError


class DomainModel(BaseModel):
    """
    Неизменяемое, проверенное состояние предметной области.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
        validate_assignment=True,
        validate_default=True,
        arbitrary_types_allowed=False,
        populate_by_name=True,
        ser_json_bytes="base64",
        ser_json_timedelta="iso8601",
    )


class Entity(DomainModel):
    """
    Идентичность и время создания, явно заданные вызывающей стороной.
    """

    id: Annotated[
        UUID,
        Field(
            description="Уникальный идентификатор сущности (UUIDv7)",
        ),
    ]
    created_at: Annotated[
        datetime,
        Field(
            description="Дата и время создания сущности (UTC)",
        ),
    ]

    @field_validator("created_at")
    @classmethod
    def _normalize_created_at(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise InvalidDomainTimestampError()
        return value.astimezone(UTC)


class MutableEntity(Entity):
    """
    Базовый класс для изменяемых сущностей предметной области.

    Расширяет `Entity` поддержкой метки времени последнего обновления `updated_at`
    и протоколом безопасных атомарных мутаций состояния.

    ВАЖНО:
    1. Изменение состояния сущности выполняется исключительно через защищённый
       метод `_apply_changes`, вызываемый из явных бизнес-методов класса.
    2. Если переданные в `_apply_changes` аргументы полностью эквивалентны текущему
       состоянию сущности (no-op), метод возвращает `False`, а `updated_at`
       гарантированно остаётся нетронутым (защита от холостых событий и записей).
    3. Прямое присваивание атрибутов запрещено (`frozen=True`). Любые изменения
       выполняются через бизнес-методы сущности.

    Пример реализации изменяемой сущности:
    ```python
        class DialogDraft(MutableEntity):
            draft_text: Annotated[str, Field(default="", max_length=4096)]

            def update_draft(self, text: str, now: datetime) -> bool:
                # 1. Если text == self.draft_text: _apply_changes сам вернёт False (no-op),
                #    updated_at останется прежним без ручных проверок if text == self.draft_text.
                # 2. Если text длиннее 4096 символов: Pydantic выбросит ValidationError,
                #    а текущее состояние черновика гарантированно останется нетронутым.
                # 3. Если text изменился и валиден: обновит draft_text и updated_at, вернёт True.
                return self._apply_changes(now=now, draft_text=text)
    ```

    Гарантии:
    - Валидация нового состояния изолированно выполняется на объекте-кандидате.
    - Метка времени `updated_at` автоматически нормализуется к UTC и не может предшествовать `created_at`.
    - При любой ошибке валидации инвариантов или времени состояние сущности
      остаётся в исходном неизменном виде (атомарный откат).
    """

    updated_at: Annotated[
        datetime | None,
        Field(
            default=None,
            description="Дата и время последнего обновления сущности (UTC)",
        ),
    ]

    @field_validator("updated_at")
    @classmethod
    def _normalize_updated_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            raise InvalidDomainTimestampError()
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_timestamps(self) -> Self:
        if self.updated_at is not None and self.updated_at < self.created_at:
            raise InvalidDomainTimestampError()
        return self

    def _mark_updated(self, now: datetime) -> None:
        """
        Фиксирует факт обновления сущности в момент времени `now`.

        Проверяет корректность часового пояса и гарантирует, что новое время
        не предшествует времени создания или предыдущему обновлению.
        """
        candidate = self.__class__.model_validate(
            {
                **self.model_dump(),
                "updated_at": now,
            }
        )
        if (
            self.updated_at is not None
            and candidate.updated_at is not None
            and candidate.updated_at < self.updated_at
        ):
            raise InvalidDomainTimestampError()
        self._replace_state(candidate)

    def _replace_state(self, candidate: Self) -> None:
        """
        Применяет уже проверенное состояние без последовательных присваиваний.

        Все потенциальные ошибки валидации возникают при создании candidate,
        пока исходный объект ещё не изменён. Вложенные значения агрегатов неизменяемы.
        """
        object.__setattr__(self, "__dict__", candidate.__dict__.copy())
        object.__setattr__(
            self, "__pydantic_fields_set__", candidate.model_fields_set.copy()
        )

    def _apply_changes(self, *, now: datetime, **changes: Any) -> bool:
        """
        Применяет набор изменений к сущности с валидацией инвариантов.

        Возвращает True, если состояние изменилось, или False, если изменения
        полностью эквивалентны текущему состоянию (no-op).
        При любой ошибке валидации состояние сущности остаётся нетронутым.
        """
        # Сначала валидируем и нормализуем бизнес-поля на отдельном объекте.
        candidate = self.__class__.model_validate(
            {
                **self.model_dump(),
                **changes,
            }
        )

        if candidate == self:
            return False  # No-op: если ничего не изменилось, время не двигаем

        # Даже ошибка времени не должна оставлять частичное изменение.
        candidate._mark_updated(now)
        self._replace_state(candidate)
        return True


class VersionedMutableEntity(MutableEntity):
    """
    Базовый класс для изменяемых сущностей с оптимистической блокировкой (OCC).

    Расширяет `MutableEntity` поддержкой монотонно растущей версии `version`
    для безопасной конкурентной записи (CAS / Optimistic Concurrency Control).

    ВАЖНО:
    1. Наследует протокол безопасных мутаций `_apply_changes` от `MutableEntity`.
       Вам НЕ нужно вручную инкрементировать `version` — при любом подтверждённом
       изменении данных метод `_apply_changes` автоматически выполняет `version + 1`
       вместе с обновлением `updated_at`.
    2. Если переданные в `_apply_changes` аргументы полностью эквивалентны текущему
       состоянию сущности (no-op), метод возвращает `False`, а `version` и `updated_at`
       гарантированно остаются нетронутыми (защита от холостых событий и ложных конфликтов OCC).
    3. Прямое присваивание атрибутов запрещено (`frozen=True`). Любые изменения
       выполняются через бизнес-методы сущности.

    Пример реализации агрегата с версионированием:
    ```python
        class ChatSettings(VersionedMutableEntity):
            title: Annotated[str, Field(min_length=1, max_length=100)]
            is_muted: Annotated[bool, Field(default=False, description="Отключены ли уведомления чата.")]

            def rename(self, new_title: str, now: datetime) -> bool:
                # 1. Если new_title == self.title: _apply_changes сам вернёт False
                #    (детекция no-op без ручных if-проверок). Версия не вырастет.
                # 2. Если new_title невалиден (пустая строка или >100 символов):
                #    Pydantic выбросит ValidationError на кандидате, а исходный объект
                #    и его версия гарантированно останутся нетронутыми (атомарный откат).
                # 3. Если значение изменилось и валидно: обновит title, увеличит version на 1,
                #    обновит updated_at и вернёт True.
                return self._apply_changes(now=now, title=new_title)

            def mute(self, now: datetime) -> bool:
                # Повторный вызов mute() автоматически вернёт False без ручных if-проверок
                return self._apply_changes(now=now, is_muted=True)
    ```

    Гарантии:
    - Начальная версия сущности всегда >= 1 (по умолчанию 1).
    - Каждое реальное изменение состояния увеличивает версию ровно на 1.
    - При любой ошибке валидации инвариантов или времени состояние сущности
      и её текущая версия остаются в исходном неизменном виде.
    """

    version: Annotated[
        int,
        Field(
            default=1,
            ge=1,
            description="Номер версии сущности (изменяется вместе с updated_at)",
        ),
    ]

    def _mark_updated(self, now: datetime) -> None:
        """
        Фиксирует факт обновления сущности в момент времени `now` и инкрементирует `version`.

        Проверяет корректность часового пояса и гарантирует, что новое время
        не предшествует времени создания или предыдущему обновлению.
        """
        candidate = self.__class__.model_validate(
            {
                **self.model_dump(),
                "updated_at": now,
                "version": self.version + 1,
            }
        )
        if (
            self.updated_at is not None
            and candidate.updated_at is not None
            and candidate.updated_at < self.updated_at
        ):
            raise InvalidDomainTimestampError()
        self._replace_state(candidate)
