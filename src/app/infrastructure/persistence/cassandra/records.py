"""Typed CQL rows and JSON restoration shared by the storage adapters."""

from collections.abc import Awaitable, Callable
from functools import wraps

from pydantic import BaseModel, ValidationError

from app.application.exceptions.dependencies import StorageUnavailableError
from app.infrastructure.persistence.cassandra.statements import DRIVER_ERRORS


class PayloadRow(BaseModel):
    payload: str


class VersionedRow(PayloadRow):
    revision: int


class SequenceRow(BaseModel):
    sequence: int


def storage_boundary[**P, T](
    operation: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[T]]:
    @wraps(operation)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await operation(*args, **kwargs)
        except (*DRIVER_ERRORS, ValidationError) as error:
            raise StorageUnavailableError("Message storage unavailable") from error

    return guarded
