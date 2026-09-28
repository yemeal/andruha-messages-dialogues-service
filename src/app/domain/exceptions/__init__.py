from app.domain.exceptions.base import DomainError, InvalidDomainTimestampError
from app.domain.exceptions.dialogues import (
    NotDialogParticipantError,
    SelfDialogNotAllowedError,
)
from app.domain.exceptions.groups import (
    CannotRemoveOwnerError,
    EmptyGroupMembersError,
    GroupMemberAlreadyExistsError,
    GroupMemberLimitExceededError,
    InvalidGroupTitleError,
    NotGroupMemberError,
    NotGroupOwnerError,
)
from app.domain.exceptions.messages import (
    EmptyMessageContentError,
    InvalidClientMessageIdVersionError,
    InvalidMessageTextError,
    MessageCreatedAtPrecedesDialogError,
    SenderRecipientSameUserError,
    WatermarkDialogMismatchError,
    WatermarkRecipientMismatchError,
)
from app.domain.exceptions.receipts import ReadCheckpointExceedsDeliveredError

__all__ = [
    "CannotRemoveOwnerError",
    "DomainError",
    "EmptyGroupMembersError",
    "EmptyMessageContentError",
    "GroupMemberAlreadyExistsError",
    "GroupMemberLimitExceededError",
    "InvalidClientMessageIdVersionError",
    "InvalidDomainTimestampError",
    "InvalidGroupTitleError",
    "InvalidMessageTextError",
    "MessageCreatedAtPrecedesDialogError",
    "NotDialogParticipantError",
    "NotGroupMemberError",
    "NotGroupOwnerError",
    "ReadCheckpointExceedsDeliveredError",
    "SelfDialogNotAllowedError",
    "SenderRecipientSameUserError",
    "WatermarkDialogMismatchError",
    "WatermarkRecipientMismatchError",
]
