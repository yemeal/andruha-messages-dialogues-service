from pydantic import BaseModel, ConfigDict


class BaseDTO(BaseModel):
    """Неизменяемое представление результата, независимое от транспорта."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", from_attributes=True, validate_default=True
    )
