from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.base import DomainModel


class ObjectId(DomainModel):
    """Непрозрачная стабильная идентичность объекта внешнего хранилища."""

    value: Annotated[UUID, Field(description="ID объекта, выданный Object Storage.")]

    @model_validator(mode="before")
    @classmethod
    def _parse_reference(cls, value: Any) -> Any:
        if isinstance(value, (UUID, str)):
            return {"value": value}
        return value

    @classmethod
    def from_uuid(cls, value: UUID) -> Self:
        return cls(value=value)

    def __str__(self) -> str:
        return str(self.value)
