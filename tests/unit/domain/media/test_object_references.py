from uuid import UUID

from app.domain import MessageContent


def test_attachment_reference_preserves_external_id_and_serializes_without_storage_details() -> (
    None
):
    from app.domain.value_objects.object_id import ObjectId

    raw = UUID("01995140-0000-7000-8000-000000000020")
    reference = ObjectId.from_uuid(raw)
    content = MessageContent.from_parts(attachments=(reference,))

    assert content.attachments == (reference,)
    assert content.attachments[0].value == raw
    assert content.model_dump(mode="json")["attachments"] == [str(raw)]
    assert MessageContent.model_validate_json(content.model_dump_json()) == content
