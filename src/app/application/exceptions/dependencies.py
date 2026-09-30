from app.application.exceptions.base import ApplicationError


class IdentityUnavailableError(ApplicationError):
    """Нет достоверного ответа Identity о завершении регистрации."""


class StorageUnavailableError(ApplicationError):
    """Нет подтверждённого результата операции с хранилищем."""


class ProjectionUnavailableError(ApplicationError):
    """Не подтверждена запись обязательной пользовательской проекции."""
