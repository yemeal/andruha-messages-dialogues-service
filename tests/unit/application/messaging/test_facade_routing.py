from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid7

import pytest

from app.application.commands.dialogues.advance_direct_receipt.result import (
    AdvanceDirectReceiptResult,
)
from app.application.commands.dialogues.send_direct_message.result import (
    SendDirectMessageResult,
)
from app.application.commands.dialogues.send_saved_message.result import (
    SendSavedMessageResult,
)
from app.application.commands.groups.advance_receipt.command import ReceiptKind
from app.application.commands.groups.advance_receipt.result import (
    AdvanceGroupReceiptResult,
)
from app.application.commands.groups.send_message.result import SendGroupMessageResult
from app.application.commands.messaging.advance_receipt_facade import (
    AdvanceReceiptFacadeCommand,
    AdvanceReceiptFacadeHandler,
)
from app.application.commands.messaging.send_message_facade import (
    SendMessageFacadeCommand,
    SendMessageFacadeHandler,
)
from app.application.dto.messages import MessageDTO
from app.application.dto.receipts import ReceiptWatermarkDTO
from app.application.exceptions.dialogues import ReceiptsNotSupportedError
from app.application.exceptions.groups import DialogNotFoundError
from app.application.ports.persistence.repositories.dialog_lookup import (
    DialogKind,
    DialogLookupProtocol,
)


class InMemoryDialogLookup(DialogLookupProtocol):
    def __init__(self) -> None:
        self.kinds: dict[UUID, DialogKind] = {}

    async def get_dialog_kind(self, dialog_id: UUID) -> DialogKind | None:
        return self.kinds.get(dialog_id)


def make_dummy_message_dto(dialog_id: UUID, sender_id: UUID) -> MessageDTO:
    return MessageDTO(
        id=uuid7(),
        dialog_id=dialog_id,
        sender_id=sender_id,
        client_message_id=uuid7(),
        text="Sample text",
        attachment_ids=(),
        position=1,
        version=1,
        created_at=datetime(2026, 10, 19, 12, 0, tzinfo=UTC),
        edited_at=None,
        is_edited=False,
    )


def make_dummy_watermark_dto(dialog_id: UUID, user_id: UUID) -> ReceiptWatermarkDTO:
    return ReceiptWatermarkDTO(
        id=uuid7(),
        dialog_id=dialog_id,
        user_id=user_id,
        delivered_through=None,
        read_through=None,
        version=1,
        created_at=datetime(2026, 10, 19, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 10, 19, 12, 0, tzinfo=UTC),
    )


@pytest.fixture
def lookup() -> InMemoryDialogLookup:
    return InMemoryDialogLookup()


@pytest.fixture
def send_direct_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def send_group_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def send_saved_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def advance_direct_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def advance_group_mock() -> AsyncMock:
    return AsyncMock()


@pytest.mark.asyncio
async def test_send_message_facade_unknown_dialog(
    lookup: InMemoryDialogLookup,
    send_direct_mock: AsyncMock,
    send_group_mock: AsyncMock,
    send_saved_mock: AsyncMock,
) -> None:
    handler = SendMessageFacadeHandler(
        dialog_lookup=lookup,
        send_direct=send_direct_mock,
        send_group=send_group_mock,
        send_saved=send_saved_mock,
    )
    cmd = SendMessageFacadeCommand(
        dialog_id=uuid7(),
        actor_id=uuid7(),
        client_message_id=uuid7(),
        text="Hello",
    )
    with pytest.raises(DialogNotFoundError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_send_message_facade_routes_to_direct(
    lookup: InMemoryDialogLookup,
    send_direct_mock: AsyncMock,
    send_group_mock: AsyncMock,
    send_saved_mock: AsyncMock,
) -> None:
    dialog_id = uuid7()
    actor_id = uuid7()
    lookup.kinds[dialog_id] = DialogKind.DIRECT

    msg_dto = make_dummy_message_dto(dialog_id, actor_id)
    send_direct_mock.return_value = SendDirectMessageResult(message=msg_dto)

    handler = SendMessageFacadeHandler(
        dialog_lookup=lookup,
        send_direct=send_direct_mock,
        send_group=send_group_mock,
        send_saved=send_saved_mock,
    )
    client_msg_id = uuid7()
    cmd = SendMessageFacadeCommand(
        dialog_id=dialog_id,
        actor_id=actor_id,
        client_message_id=client_msg_id,
        text="Direct message",
    )
    result = await handler(cmd)
    assert result.dialog_kind == DialogKind.DIRECT
    assert result.message == msg_dto
    send_direct_mock.assert_awaited_once()
    send_group_mock.assert_not_called()
    send_saved_mock.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_facade_routes_to_group(
    lookup: InMemoryDialogLookup,
    send_direct_mock: AsyncMock,
    send_group_mock: AsyncMock,
    send_saved_mock: AsyncMock,
) -> None:
    dialog_id = uuid7()
    actor_id = uuid7()
    lookup.kinds[dialog_id] = DialogKind.GROUP

    msg_dto = make_dummy_message_dto(dialog_id, actor_id)
    send_group_mock.return_value = SendGroupMessageResult(
        message=msg_dto, group_version=2
    )

    handler = SendMessageFacadeHandler(
        dialog_lookup=lookup,
        send_direct=send_direct_mock,
        send_group=send_group_mock,
        send_saved=send_saved_mock,
    )
    cmd = SendMessageFacadeCommand(
        dialog_id=dialog_id,
        actor_id=actor_id,
        client_message_id=uuid7(),
        text="Group announcement",
    )
    result = await handler(cmd)
    assert result.dialog_kind == DialogKind.GROUP
    assert result.message == msg_dto
    send_group_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_facade_routes_to_saved(
    lookup: InMemoryDialogLookup,
    send_direct_mock: AsyncMock,
    send_group_mock: AsyncMock,
    send_saved_mock: AsyncMock,
) -> None:
    dialog_id = uuid7()
    actor_id = uuid7()
    lookup.kinds[dialog_id] = DialogKind.SAVED

    msg_dto = make_dummy_message_dto(dialog_id, actor_id)
    send_saved_mock.return_value = SendSavedMessageResult(message=msg_dto)

    handler = SendMessageFacadeHandler(
        dialog_lookup=lookup,
        send_direct=send_direct_mock,
        send_group=send_group_mock,
        send_saved=send_saved_mock,
    )
    cmd = SendMessageFacadeCommand(
        dialog_id=dialog_id,
        actor_id=actor_id,
        client_message_id=uuid7(),
        text="Saved note",
    )
    result = await handler(cmd)
    assert result.dialog_kind == DialogKind.SAVED
    assert result.message == msg_dto
    send_saved_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_advance_receipt_facade_unknown_dialog(
    lookup: InMemoryDialogLookup,
    advance_direct_mock: AsyncMock,
    advance_group_mock: AsyncMock,
) -> None:
    handler = AdvanceReceiptFacadeHandler(
        dialog_lookup=lookup,
        advance_direct=advance_direct_mock,
        advance_group=advance_group_mock,
    )
    cmd = AdvanceReceiptFacadeCommand(
        dialog_id=uuid7(),
        actor_id=uuid7(),
        kind=ReceiptKind.DELIVERED,
        through_message_id=uuid7(),
    )
    with pytest.raises(DialogNotFoundError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_advance_receipt_facade_saved_dialog_rejected(
    lookup: InMemoryDialogLookup,
    advance_direct_mock: AsyncMock,
    advance_group_mock: AsyncMock,
) -> None:
    dialog_id = uuid7()
    lookup.kinds[dialog_id] = DialogKind.SAVED

    handler = AdvanceReceiptFacadeHandler(
        dialog_lookup=lookup,
        advance_direct=advance_direct_mock,
        advance_group=advance_group_mock,
    )
    cmd = AdvanceReceiptFacadeCommand(
        dialog_id=dialog_id,
        actor_id=uuid7(),
        kind=ReceiptKind.READ,
        through_message_id=uuid7(),
    )
    with pytest.raises(ReceiptsNotSupportedError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_advance_receipt_facade_routes_to_direct(
    lookup: InMemoryDialogLookup,
    advance_direct_mock: AsyncMock,
    advance_group_mock: AsyncMock,
) -> None:
    dialog_id = uuid7()
    actor_id = uuid7()
    lookup.kinds[dialog_id] = DialogKind.DIRECT

    wm_dto = make_dummy_watermark_dto(dialog_id, actor_id)
    advance_direct_mock.return_value = AdvanceDirectReceiptResult(
        watermark=wm_dto, changed=True
    )

    handler = AdvanceReceiptFacadeHandler(
        dialog_lookup=lookup,
        advance_direct=advance_direct_mock,
        advance_group=advance_group_mock,
    )
    cmd = AdvanceReceiptFacadeCommand(
        dialog_id=dialog_id,
        actor_id=actor_id,
        kind=ReceiptKind.DELIVERED,
        through_message_id=uuid7(),
    )
    result = await handler(cmd)
    assert result.dialog_kind == DialogKind.DIRECT
    assert result.changed is True
    assert result.watermark == wm_dto
    advance_direct_mock.assert_awaited_once()
    advance_group_mock.assert_not_called()


@pytest.mark.asyncio
async def test_advance_receipt_facade_routes_to_group(
    lookup: InMemoryDialogLookup,
    advance_direct_mock: AsyncMock,
    advance_group_mock: AsyncMock,
) -> None:
    dialog_id = uuid7()
    actor_id = uuid7()
    lookup.kinds[dialog_id] = DialogKind.GROUP

    wm_dto = make_dummy_watermark_dto(dialog_id, actor_id)
    advance_group_mock.return_value = AdvanceGroupReceiptResult(
        watermark=wm_dto, group_version=5, changed=True
    )

    handler = AdvanceReceiptFacadeHandler(
        dialog_lookup=lookup,
        advance_direct=advance_direct_mock,
        advance_group=advance_group_mock,
    )
    cmd = AdvanceReceiptFacadeCommand(
        dialog_id=dialog_id,
        actor_id=actor_id,
        kind=ReceiptKind.READ,
        through_message_id=uuid7(),
    )
    result = await handler(cmd)
    assert result.dialog_kind == DialogKind.GROUP
    assert result.changed is True
    assert result.watermark == wm_dto
    advance_group_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_facade_unsupported_dialog_kind(
    lookup: InMemoryDialogLookup,
    send_direct_mock: AsyncMock,
    send_group_mock: AsyncMock,
    send_saved_mock: AsyncMock,
) -> None:
    from app.application.exceptions.base import ApplicationError
    from app.application.exceptions.dialogues import UnsupportedDialogKindError

    dialog_id = uuid7()
    lookup.kinds[dialog_id] = "UNKNOWN_KIND"  # type: ignore[assignment]

    handler = SendMessageFacadeHandler(
        dialog_lookup=lookup,
        send_direct=send_direct_mock,
        send_group=send_group_mock,
        send_saved=send_saved_mock,
    )
    cmd = SendMessageFacadeCommand(
        dialog_id=dialog_id,
        actor_id=uuid7(),
        client_message_id=uuid7(),
        text="Hello",
    )
    with pytest.raises(UnsupportedDialogKindError) as exc_info:
        await handler(cmd)
    assert isinstance(exc_info.value, ApplicationError)
    assert "UNKNOWN_KIND" in str(exc_info.value)


@pytest.mark.asyncio
async def test_advance_receipt_facade_unsupported_dialog_kind(
    lookup: InMemoryDialogLookup,
    advance_direct_mock: AsyncMock,
    advance_group_mock: AsyncMock,
) -> None:
    from app.application.exceptions.base import ApplicationError
    from app.application.exceptions.dialogues import UnsupportedDialogKindError

    dialog_id = uuid7()
    lookup.kinds[dialog_id] = "UNKNOWN_KIND"  # type: ignore[assignment]

    handler = AdvanceReceiptFacadeHandler(
        dialog_lookup=lookup,
        advance_direct=advance_direct_mock,
        advance_group=advance_group_mock,
    )
    cmd = AdvanceReceiptFacadeCommand(
        dialog_id=dialog_id,
        actor_id=uuid7(),
        kind=ReceiptKind.DELIVERED,
        through_message_id=uuid7(),
    )
    with pytest.raises(UnsupportedDialogKindError) as exc_info:
        await handler(cmd)
    assert isinstance(exc_info.value, ApplicationError)
    assert "UNKNOWN_KIND" in str(exc_info.value)
