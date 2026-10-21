"""Репозитории агрегатов и атомарные границы принятия команд."""

from app.application.ports.persistence.repositories.outbox import (
    OutboxRepositoryProtocol,
)

__all__ = [
    "OutboxRepositoryProtocol",
]
