import pytest

from app.application.commands.groups.advance_receipt.handler import (
    AdvanceGroupReceiptHandler,
)


@pytest.fixture
def advance_receipt(groups, clock, ids) -> AdvanceGroupReceiptHandler:
    return AdvanceGroupReceiptHandler(groups=groups, clock=clock.now, ids=ids.new_id)
