import pytest

from app.worker_state import WorkerActivityTracker


@pytest.mark.asyncio
async def test_starts_idle() -> None:
    tracker = WorkerActivityTracker()
    assert tracker.is_idle is True


@pytest.mark.asyncio
async def test_not_idle_while_a_worker_is_active() -> None:
    tracker = WorkerActivityTracker()
    await tracker.enter()
    assert tracker.is_idle is False


@pytest.mark.asyncio
async def test_idle_again_after_exit() -> None:
    tracker = WorkerActivityTracker()
    await tracker.enter()
    await tracker.exit()
    assert tracker.is_idle is True


@pytest.mark.asyncio
async def test_multiple_workers_all_must_exit_before_idle() -> None:
    tracker = WorkerActivityTracker()
    await tracker.enter()
    await tracker.enter()
    await tracker.exit()
    assert tracker.is_idle is False  # one worker still active
    await tracker.exit()
    assert tracker.is_idle is True


@pytest.mark.asyncio
async def test_exit_never_goes_negative() -> None:
    tracker = WorkerActivityTracker()
    await tracker.exit()  # exit without a matching enter
    assert tracker.is_idle is True
