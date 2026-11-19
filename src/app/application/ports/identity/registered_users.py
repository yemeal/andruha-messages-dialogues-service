from typing import Protocol
from uuid import UUID


class RegisteredUsersProtocol(Protocol):
    async def require_registered_many(self, user_ids: tuple[UUID, ...]) -> None:
        """Confirm a bounded set through batched Identity requests."""
        ...

    async def require_registered(self, user_id: UUID) -> None:
        """Подтверждает завершённую регистрацию через контракт Identity.

        UserNotRegisteredError означает подтверждённый отрицательный ответ;
        IdentityUnavailableError означает отсутствие достоверного ответа.
        Наличие Profile и незавершённая регистрация не являются подтверждением.
        """
        ...
