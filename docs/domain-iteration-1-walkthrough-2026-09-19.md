# Первая доменная итерация: walkthrough для review

Реализованы `DirectParticipants` и `DirectDialog` из согласованного первого
инкремента. Изменения находятся в рабочем дереве Messages and Dialogues;
коммиты и PR не создавались. `Message` и `ReceiptWatermark` остаются следующими
итерациями проекта.

## Как читать изменение

1. [DirectParticipants](../src/app/domain/value_objects/direct_participants.py):
   канонизирует два UUID по bytes. A–B и B–A равны и имеют одинаковый hash.
   Диалог A–A запрещён. Оператор `in` проверяет участие, `peer_of` возвращает
   собеседника либо поднимает `NotDialogParticipantError`.
2. [DirectDialog](../src/app/domain/aggregates/direct_dialog.py): содержит ID,
   время создания и пару. Оператор `in` проверяет доступ, `peer_of` использует правило пары.
3. [DomainModel / Entity](../src/app/domain/base.py): защищают все публичные
   поля и запрещают неизвестные поля. Время без timezone отклоняется;
   timezone-aware время приводится к UTC без изменения момента.
4. [Тесты пары](../tests/unit/domain/test_direct_participants.py) и
   [тесты диалога](../tests/unit/domain/test_direct_dialog.py): показывают
   контракт создания, восстановления, доступа и ошибочных состояний.

Минимальный пример публичного интерфейса:

```python
from datetime import UTC, datetime
from uuid import UUID

from app.domain import DirectDialog, DirectParticipants

alice = UUID("00000000-0000-4000-8000-000000000001")
bob = UUID("00000000-0000-4000-8000-000000000002")
dialog = DirectDialog.create(
    dialog_id=UUID("01995140-0000-7000-8000-000000000001"),
    participants=DirectParticipants.from_user_ids(bob, alice),
    now=datetime(2026, 9, 19, 5, 30, tzinfo=UTC),
)
assert alice in dialog
assert dialog.peer_of(alice) == bob
```

## Решения, которые стоит обсудить на review

| Решение | На что обратить внимание |
|---|---|
| Неизменяемый диалог и пара | Нет `version`, `updated_at`, методов добавления/удаления участника. Это соответствует текущему 1:1 MVP; новые операции потребуют явной модели переходов |
| Канонизация при любой валидации | Переставленные `first/second` нормализуются и при восстановлении. Проверить, подходит ли эта семантика для будущего persistence mapper |
| Явные ID и время | В моделях нет генераторов UUID и системных часов. Application будет выбирать их перед созданием кандидата; повторная загрузка не создаёт новых значений |
| Pydantic как в Profile | Фабрика, конструктор, `model_validate` и JSON-восстановление проверяют правила. `model_construct` и `model_copy(update=...)` обходят проверки Pydantic и не являются поддерживаемыми путями создания/изменения |
| Два вида ошибок | Нарушения предметных правил дают `DomainError`; повреждённые типы/UUID, неизвестные или отсутствующие поля дают `ValidationError`. Будущий adapter обязан переводить оба вида по назначению |
| Граница ответственности | Python-модель проверяет форму пары и membership. Завершённую регистрацию подтвердит application-порт Identity; единственность пары при конкуренции обеспечит репозиторий |

`DomainModel` сохраняет сравнение Pydantic по полям. Для пары это value equality;
для агрегата это сравнение снимков. Business identity диалога определяется `id`;
не следует выводить её из равенства всех полей. Отдельная семантика `Entity.__eq__`
не вводилась — это также точка для обсуждения при появлении изменяемых агрегатов.

Нормализация пары использует `object.__setattr__` только внутри валидатора
после проверки участников. Публичные присваивания и удаления запрещены, включая
изменение `dialog.participants.user_high`. Защита относится к обычному API Python.

## TDD и проверки

Работа шла небольшими RED → GREEN циклами. Наблюдались реальные RED:
отсутствующие публичные модели/методы, принятие A–A, молчаливое игнорирование
третьего поля, принятие naive datetime и сохранение отличного от UTC timezone.
Каждое новое правило реализовано после соответствующего падения. Дополнительные
проверки уже обеспеченных Pydantic ограничений закрепили контракт восстановления.

В pytest использованы function-scoped fixtures, parametrized fixtures для
четырёх путей построения, осмысленные case IDs, `pytest.raises`, проверка
состояния после отказа, `monkeypatch` и `tmp_path` для изолированного процесса.
[Проверка импортов](../tests/unit/domain/test_import_boundaries.py) запрещает
загрузку application, core, HTTP и известных инфраструктурных зависимостей.
Доменные модели в тестах настоящие, внутренние методы не мокируются.

Результаты на 19 сентября 2026 года:

| Проверка | Результат |
|---|---|
| `pytest tests/unit/domain` | 71 passed; 100% statements/branches домена |
| Unit suite сервиса | 119 passed, без skip/xfail |
| Integration suite сервиса | 8 passed: существующие HTTP bootstrap/health сценарии |
| Общее покрытие | 100% statements/branches: 334 statements, 52 branches |
| Ruff, format, `ty --error-on-warning`, `poetry check --lock` | Passed |
| Audit 15 runtime-пакетов из lock | Известных уязвимостей не найдено |

Pydantic 2.13.4 объявлен прямой зависимостью. Версии пакетов в lock не изменились;
обновлён только content hash. В локальном Poetry отсутствует export plugin,
поэтому для audit использован временный список точных версий всех не-optional
пакетов группы main из lock, с `pip-audit --no-deps --disable-pip --strict`.

Docker build/smoke, remote CI и реальные Cassandra/Kafka/Identity интеграции
не запускались. Сервис пока предоставляет только operational HTTP routes;
новые модели ещё не подключены к application или persistence.

Для воспроизведения доменных проверок из каталога сервиса:

```powershell
poetry run pytest tests/unit/domain -v --cov=app.domain --cov-branch --cov-report=term-missing
```
