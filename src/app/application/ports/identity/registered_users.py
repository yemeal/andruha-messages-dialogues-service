from typing import Protocol
from uuid import UUID


class RegisteredUsersProtocol(Protocol):
    async def require_registered(self, user_id: UUID) -> None:
        """Подтверждает завершённую регистрацию через контракт Identity.

        UserNotRegisteredError означает подтверждённый отрицательный ответ;
        IdentityUnavailableError означает отсутствие достоверного ответа.
        Наличие Profile и незавершённая регистрация не являются подтверждением.
        """
        ...
