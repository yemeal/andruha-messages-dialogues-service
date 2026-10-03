from typing import Protocol
from uuid import UUID

from app.application.ports.persistence.models import (
    GroupMembershipAcceptance,
    GroupMembershipIntent,
    GroupMutation,
    GroupSnapshot,
)
from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.value_objects.message_send_key import MessageSendKey


class GroupRevisionRepositoryProtocol(Protocol):
    """Все чтения at_revision относятся к одной атомарной истории группы.

    Изменение наблюдаемых данных продвигает общую revision, включая будущее
    сохранение редактирования Message. Отдельная eventual projection
    не является источником командных чтений без подтверждения этой ревизии.
    Запрошенная ревизия должна включать и отсутствие записи. Если адаптер
    не может подтвердить состояние именно этой ревизии, он поднимает
    GroupReadConflictError, а не возвращает устаревший объект или None.
    StorageUnavailableError остаётся ошибкой доступности, а не конфликтом.
    """

    async def get_by_id(self, dialog_id: UUID) -> GroupSnapshot | None:
        """Читает согласованные group/revision/last_position в отдельные объекты."""
        ...


class GroupCommitRepositoryProtocol(GroupRevisionRepositoryProtocol, Protocol):
    async def try_commit(
        self, expected: GroupSnapshot, mutation: GroupMutation, *, command_id: UUID
    ) -> bool:
        """Сравнивает ревизию и атомарно сохраняет результат одной команды.

        Все команды группы, включая изменение состава и no-op, используют
        эту границу. Успех одновременно сохраняет mutation, новую ревизию,
        позицию сообщения (для отправки), а также durable
        подтверждение command_id.
        None означает условный fence без изменения доменных агрегатов.

        Новое Message условно резервирует send key и ID, а позиция равна
        last_position + 1. Существующий ключ не создаёт новую запись даже
        при ошибочном отсутствии результата предварительного чтения.
        ReceiptWatermark сохраняет ID, read/delivered не уменьшаются;
        версия кандидата следует непосредственно за сохранённой версией.
        Эти условия проверяются вместе с revision; нарушение даёт False
        без записи, включая продвижение revision и позиции.

        False означает доказанный конфликт БЕЗ каких-либо записей. Неизвестный
        исход разрешается по durable подтверждению command_id; неразрешённый
        исход выражается StorageUnavailableError и никогда не превращается
        в False. Адаптер запрещает обычные записи в обход этой границы.

        Для Cassandra: условный batch одной таблицы/partition, включающий
        проверку revision и запись результата; последовательные CAS и INSERT
        в разных partitions не удовлетворяют контракту.
        """
        ...


class GroupMembershipRepositoryProtocol(GroupRevisionRepositoryProtocol, Protocol):
    async def get_membership_result(
        self, dialog_id: UUID, command_id: UUID, *, at_revision: int
    ) -> GroupMembershipAcceptance | None:
        """Результат команды состава на at_revision; отсутствие тоже согласовано."""
        ...

    async def try_commit_membership(
        self,
        expected: GroupSnapshot,
        candidate: GroupDialog,
        *,
        command_id: UUID,
        intent: GroupMembershipIntent,
    ) -> bool:
        """Одна атомарная граница для состава, revision и результата команды.

        Применяет гарантии try_commit; command_id уникален внутри dialog_id.
        Успех сохраняет intent и GroupDialogDTO принятого candidate в той же
        операции. Повторно занятый command_id даёт False без записей; handler
        читает сохранённый результат. Неизвестный исход разрешается этим же
        стабильным command_id либо выражается StorageUnavailableError.
        Материал незавершённого восстановления не удаляется по TTL.
        """
        ...


class GroupReceiptRepositoryProtocol(GroupCommitRepositoryProtocol, Protocol):
    async def get_message(
        self, dialog_id: UUID, message_id: UUID, *, at_revision: int
    ) -> Message | None:
        """Изолированное сообщение указанного диалога на at_revision."""
        ...

    async def get_receipt(
        self, dialog_id: UUID, user_id: UUID, *, at_revision: int
    ) -> ReceiptWatermark | None:
        """Изолированный watermark на at_revision; query не меняет хранилище."""
        ...


class GroupMessageRepositoryProtocol(GroupCommitRepositoryProtocol, Protocol):
    async def get_sent_message(
        self, dialog_id: UUID, send_key: MessageSendKey, *, at_revision: int
    ) -> Message | None:
        """Изолированная текущая редакция по ключу на at_revision.

        До редактирования handler сравнивает всё нормализованное содержимое.
        После редактирования различия текста не влияют на распознавание replay;
        неизменяемые поля по-прежнему должны совпадать. Для этой проверки
        исходный текст и fingerprint не сохраняются.
        """
        ...


class GroupCommandRepositoryProtocol(
    GroupMembershipRepositoryProtocol,
    GroupMessageRepositoryProtocol,
    GroupReceiptRepositoryProtocol,
    Protocol,
):
    """Составной контракт адаптера; handlers зависят от клиентских Protocol."""
