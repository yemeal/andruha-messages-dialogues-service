from uuid import UUID

from app.application.exceptions.base import ApplicationError


class UserNotRegisteredError(ApplicationError):
    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        super().__init__(f"Registration is not completed for user {user_id}")


class DialogProjectionsIncompleteError(ApplicationError):
    def __init__(self, dialog_id: UUID, user_id: UUID) -> None:
        self.dialog_id = dialog_id
        self.user_id = user_id
        super().__init__(f"Dialog {dialog_id} projection is incomplete for {user_id}")
