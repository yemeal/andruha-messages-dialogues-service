from datetime import datetime
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from app.domain import (
    GroupDialog,
    MessageContent,
    MessagePosition,
    MessageText,
    ReceiptWatermark,
)
from app.domain.exceptions import InvalidMessageTextError


def test_copy_validates_new_content_without_changing_original() -> None:
    original = MessageText.from_str("Original")

    with pytest.raises(InvalidMessageTextError):
        original.model_copy(update={"value": ""})

    assert original.value == "Original"


def test_content_revalidates_a_nested_instance_from_an_unsafe_external_copy() -> None:
    invalid = BaseModel.model_copy(MessageText.from_str("Valid"), update={"value": ""})

    with pytest.raises(InvalidMessageTextError):
        MessageContent.from_text(invalid)


def test_construct_cannot_bypass_content_validation() -> None:
    with pytest.raises(InvalidMessageTextError):
        MessageText.model_construct(value="")


def test_mutable_aggregates_cannot_be_dictionary_keys(
    alice_id: UUID, dialog_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(title="Group", owner_id=alice_id, now=now)
    watermark = ReceiptWatermark.create_empty(
        dialog_id=dialog_id, user_id=alice_id, now=now
    )

    for aggregate in (group, watermark):
        with pytest.raises(TypeError, match="unhashable"):
            hash(aggregate)


@pytest.mark.parametrize("value", [True, 1.0, "1"], ids=["bool", "float", "string"])
def test_order_and_version_reject_coercible_nonintegers(
    value: object, alice_id: UUID, dialog_id: UUID, now: datetime
) -> None:
    with pytest.raises(ValidationError):
        MessagePosition.model_validate({"dialog_id": dialog_id, "value": value})

    group = GroupDialog.create(title="Group", owner_id=alice_id, now=now)
    with pytest.raises(ValidationError):
        GroupDialog.model_validate({**group.model_dump(), "version": value})
