from uuid import UUID

import pytest

from app.application.commands.groups.rename.command import RenameGroupDialogCommand
from app.application.commands.groups.rename.handler import RenameGroupDialogHandler
from app.application.exceptions.groups import (
    ConcurrentModificationError,
    GroupMetadataConflictError,
)
from app.domain.exceptions.groups import (
    InvalidGroupTitleError,
    NotGroupMemberError,
)


@pytest.mark.asyncio
async def test_rename_group_success(groups, clock) -> None:
    handler = RenameGroupDialogHandler(groups=groups, clock=clock.now)

    alice_id = groups.current.dialog.owner_id
    command_id = UUID("01995140-0000-7000-8000-0000000000c1")
    cmd = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=alice_id,
        command_id=command_id,
        new_title="Новое Название",
    )

    result = await handler(cmd)

    assert result.title == "Новое Название"
    assert result.version == 2
    assert result.updated_at == clock.now()
    assert groups.current.dialog.title.value == "Новое Название"
    assert groups.current.revision == 2


@pytest.mark.asyncio
async def test_rename_group_by_non_member_raises_error(groups, clock) -> None:
    stranger_id = UUID("00000000-0000-4000-8000-000000000999")
    handler = RenameGroupDialogHandler(groups=groups, clock=clock.now)

    cmd = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=stranger_id,
        command_id=UUID("01995140-0000-7000-8000-0000000000c2"),
        new_title="Взлом",
    )

    with pytest.raises(NotGroupMemberError):
        await handler(cmd)

    assert groups.current.dialog.title.value == "Рабочая группа"


@pytest.mark.asyncio
async def test_rename_group_invalid_title(groups, clock) -> None:
    handler = RenameGroupDialogHandler(groups=groups, clock=clock.now)

    cmd = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=groups.current.dialog.owner_id,
        command_id=UUID("01995140-0000-7000-8000-0000000000c3"),
        new_title="   ",
    )

    with pytest.raises(InvalidGroupTitleError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_rename_group_same_title_no_op(groups, clock) -> None:
    handler = RenameGroupDialogHandler(groups=groups, clock=clock.now)

    cmd = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=groups.current.dialog.owner_id,
        command_id=UUID("01995140-0000-7000-8000-0000000000c4"),
        new_title="Рабочая группа",
    )

    result = await handler(cmd)

    assert result.title == "Рабочая группа"
    assert result.version == 1  # version not bumped for no-op!


@pytest.mark.asyncio
async def test_rename_group_idempotency_cached_result(groups, clock) -> None:
    handler = RenameGroupDialogHandler(groups=groups, clock=clock.now)

    command_id = UUID("01995140-0000-7000-8000-0000000000c5")
    cmd = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=groups.current.dialog.owner_id,
        command_id=command_id,
        new_title="Первое Переименование",
    )

    first = await handler(cmd)
    second = await handler(cmd)

    assert first == second
    assert groups.current.revision == 2


@pytest.mark.asyncio
async def test_rename_group_command_id_conflict(groups, clock) -> None:
    handler = RenameGroupDialogHandler(groups=groups, clock=clock.now)

    command_id = UUID("01995140-0000-7000-8000-0000000000c6")
    cmd1 = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=groups.current.dialog.owner_id,
        command_id=command_id,
        new_title="Название 1",
    )
    cmd2 = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=groups.current.dialog.owner_id,
        command_id=command_id,
        new_title="Другое Название",
    )

    await handler(cmd1)

    with pytest.raises(GroupMetadataConflictError):
        await handler(cmd2)


@pytest.mark.asyncio
async def test_rename_group_normalization_preserves_idempotency(groups, clock) -> None:
    handler = RenameGroupDialogHandler(groups=groups, clock=clock.now)

    command_id = UUID("01995140-0000-7000-8000-0000000000c8")
    cmd_raw = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=groups.current.dialog.owner_id,
        command_id=command_id,
        new_title="  Название с Пробелами  ",
    )
    cmd_trimmed = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=groups.current.dialog.owner_id,
        command_id=command_id,
        new_title="Название с Пробелами",
    )

    first = await handler(cmd_raw)
    second = await handler(cmd_trimmed)

    assert first.title == "Название с Пробелами"
    assert first == second
    assert groups.current.revision == 2


@pytest.mark.asyncio
async def test_rename_group_concurrent_exhaustion(groups, clock) -> None:
    groups.force_conflict = True
    handler = RenameGroupDialogHandler(groups=groups, clock=clock.now, max_attempts=3)

    cmd = RenameGroupDialogCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=groups.current.dialog.owner_id,
        command_id=UUID("01995140-0000-7000-8000-0000000000c7"),
        new_title="Не применится",
    )

    with pytest.raises(ConcurrentModificationError):
        await handler(cmd)
