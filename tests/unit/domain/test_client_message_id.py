import uuid
from uuid import UUID, uuid4, uuid7

import pytest
from pydantic import ValidationError

from app.domain.exceptions.messages import InvalidClientMessageIdVersionError
from app.domain.value_objects.client_message_id import ClientMessageId


def test_generate_creates_valid_uuidv7_client_message_id() -> None:
    client_msg_id = ClientMessageId.generate()
    assert isinstance(client_msg_id.value, UUID)
    assert client_msg_id.value.version == 7


def test_from_uuid_accepts_uuidv7() -> None:
    raw_v7 = uuid7()
    client_msg_id = ClientMessageId.from_uuid(raw_v7)
    assert client_msg_id.value == raw_v7


def test_from_str_accepts_uuidv7_string() -> None:
    raw_v7 = uuid7()
    client_msg_id = ClientMessageId.from_str(str(raw_v7))
    assert client_msg_id.value == raw_v7


def test_rejects_uuid_version_other_than_v7() -> None:
    raw_v4 = uuid4()
    with pytest.raises(InvalidClientMessageIdVersionError):
        ClientMessageId.from_uuid(raw_v4)

    with pytest.raises(InvalidClientMessageIdVersionError):
        ClientMessageId.from_str(str(raw_v4))

    raw_v1 = uuid.uuid1()
    with pytest.raises(InvalidClientMessageIdVersionError):
        ClientMessageId(value=raw_v1)


def test_equality_and_hashing() -> None:
    raw_v7 = uuid7()
    id1 = ClientMessageId.from_uuid(raw_v7)
    id2 = ClientMessageId.from_str(str(raw_v7))
    id3 = ClientMessageId.generate()

    assert id1 == id2
    assert id1 != id3
    assert id1 != "non-client-id"
    assert hash(id1) == hash(id2)
    assert len({id1, id2, id3}) == 2


def test_str_and_repr() -> None:
    raw_v7 = uuid7()
    client_msg_id = ClientMessageId.from_uuid(raw_v7)
    assert str(client_msg_id) == str(raw_v7)
    assert repr(client_msg_id) == f"ClientMessageId('{raw_v7}')"


def test_immutability() -> None:
    client_msg_id = ClientMessageId.generate()
    with pytest.raises(ValidationError):
        client_msg_id.value = uuid7()  # type: ignore[misc]
