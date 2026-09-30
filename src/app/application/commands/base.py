from pydantic import BaseModel, ConfigDict


class BaseCommand[ResultT](BaseModel):
    """Неизменяемая команда с явным типом результата сценария."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
