from typing import Protocol
from uuid import UUID

from app.application.ports.persistence.models import GroupMutation, GroupSnapshot
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.value_objects.message_send_key import MessageSendKey


class GroupCommandRepositoryProtocol(Protocol):
    async def get_by_id(self, dialog_id: UUID) -> GroupSnapshot | None:
        """Читает согласованные group/revision/last_position в отдельные объекты."""
        ...

    async def get_message(self, dialog_id: UUID, message_id: UUID) -> Message | None:
        """Возвращает сохранённое сообщение только указанного диалога."""
        ...

    async def get_sent_message(
        self, dialog_id: UUID, send_key: MessageSendKey
    ) -> Message | None:
        """Находит принятую отправку в группе; возвращает изолированный снимок."""
        ...

    async def get_receipt(
        self, dialog_id: UUID, user_id: UUID
    ) -> ReceiptWatermark | None: ...

    async def try_commit(
        self, expected: GroupSnapshot, mutation: GroupMutation, *, command_id: UUID
    ) -> bool:
        """Сравнивает ревизию и атомарно сохраняет результат одной команды.

        Все команды группы, включая изменение состава и no-op, используют
        эту границу. Успех одновременно сохраняет mutation, новую ревизию,
        позицию сообщения (для отправки) и durable подтверждение command_id.
        None означает условный fence без изменения доменных агрегатов.

        False означает доказанный конфликт БЕЗ каких-либо записей. Неизвестный
        исход разрешается по durable подтверждению command_id; неразрешённый
        исход выражается StorageUnavailableError и никогда не превращается
        в False. Адаптер запрещает обычные записи в обход этой границы.

        Для Cassandra: условный batch одной таблицы/partition, включающий
        проверку revision и запись результата; последовательные CAS и INSERT
        в разных partitions не удовлетворяют контракту.
        """
        ...
