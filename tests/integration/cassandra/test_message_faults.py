from datetime import UTC, datetime
from uuid import uuid7

import pytest
from cassandra import OperationTimedOut

from app.application.exceptions.dependencies import StorageUnavailableError
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.message import Message
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.direct_participants import DirectParticipants
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.infrastructure.persistence.cassandra.dialogues import CassandraDirectDialogs
from app.infrastructure.persistence.cassandra.messages import CassandraMessages

NOW = datetime(2026, 11, 17, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "commit_reaches_cassandra", [True, False], ids=["lost-response", "no-commit"]
)
async def test_unknown_send_outcome_never_becomes_success_without_durable_confirmation(
    cassandra_session, monkeypatch, lost_commit_response, commit_reaches_cassandra
):
    sender, peer = uuid7(), uuid7()
    dialog = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(sender, peer), now=NOW
    )
    await CassandraDirectDialogs(cassandra_session).create_or_get(dialog)
    candidate = Message.create(
        dialog_id=dialog.id,
        sender_id=sender,
        client_message_id=ClientMessageId.from_uuid(uuid7()),
        content=MessageContent.from_parts(text="Неизвестный исход", attachments=()),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        now=NOW,
    )
    native = cassandra_session.execute_async
    fault_used = False

    def unknown_send(query, *args, **kwargs):
        nonlocal fault_used
        if (
            "INSERT INTO canonical_rows" in str(query)
            and "'send'" in str(query)
            and not fault_used
        ):
            fault_used = True
            if commit_reaches_cassandra:
                return lost_commit_response(native(query, *args, **kwargs))
            raise OperationTimedOut()
        return native(query, *args, **kwargs)

    monkeypatch.setattr(cassandra_session, "execute_async", unknown_send)
    adapter = CassandraMessages(cassandra_session)
    if commit_reaches_cassandra:
        result = await adapter.save_message(
            candidate, idempotency_key=candidate.send_key
        )
        assert result.id == candidate.id
        assert result.position.value == 1
    else:
        with pytest.raises(StorageUnavailableError):
            await adapter.save_message(candidate, idempotency_key=candidate.send_key)
        assert await adapter.get_last_position(dialog.id) == 0
    assert fault_used
    monkeypatch.setattr(cassandra_session, "execute_async", native)
    recovered = await CassandraMessages(cassandra_session).get_by_send_key(
        candidate.send_key
    )
    assert recovered is not None
    assert recovered.id == candidate.id
    assert recovered.position.value == 1
    assert await adapter.get_last_position(dialog.id) == 1
