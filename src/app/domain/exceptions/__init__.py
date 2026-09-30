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
    InvalidMessageAttachmentsError,
    InvalidMessageEditMetadataError,
    InvalidMessageTextError,
    MessageCreatedAtPrecedesDialogError,
    NotMessageAuthorError,
    PositionDialogMismatchError,
    WatermarkDialogMismatchError,
    WatermarkRecipientMismatchError,
)
from app.domain.exceptions.receipts import (
    CheckpointMessageMismatchError,
    NotIncomingMessageError,
    ReadCheckpointExceedsDeliveredError,
    ReceiptActorMismatchError,
    ReceiptDialogMismatchError,
)

__all__ = [
    "CannotRemoveOwnerError",
    "CheckpointMessageMismatchError",
    "DomainError",
    "EmptyGroupMembersError",
    "EmptyMessageContentError",
    "GroupMemberAlreadyExistsError",
    "GroupMemberLimitExceededError",
    "InvalidClientMessageIdVersionError",
    "InvalidDomainTimestampError",
    "InvalidGroupTitleError",
    "InvalidMessageAttachmentsError",
    "InvalidMessageEditMetadataError",
    "InvalidMessageTextError",
    "MessageCreatedAtPrecedesDialogError",
    "NotDialogParticipantError",
    "NotGroupMemberError",
    "NotGroupOwnerError",
    "NotIncomingMessageError",
    "NotMessageAuthorError",
    "PositionDialogMismatchError",
    "ReadCheckpointExceedsDeliveredError",
    "ReceiptActorMismatchError",
    "ReceiptDialogMismatchError",
    "SelfDialogNotAllowedError",
    "WatermarkDialogMismatchError",
    "WatermarkRecipientMismatchError",
]
