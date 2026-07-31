import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_worker_loop_survives_process_job_exception(monkeypatch) -> None:
    from app import worker as worker_module

    call_count = {"n": 0}

    async def fake_claim():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return MagicMock(job_id="job-1")
        if call_count["n"] == 2:
            raise asyncio.CancelledError  # stop the loop after 2 iterations
        return None

    queue = MagicMock()
    queue.claim = AsyncMock(side_effect=fake_claim)

    process_job_mock = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(worker_module, "process_job", process_job_mock)

    settings = MagicMock()
    settings.poll_interval_seconds = 0.01

    with pytest.raises(asyncio.CancelledError):
        await worker_module.worker_loop(
            bot=MagicMock(),
            pool=MagicMock(),
            queue=queue,
            limiter=MagicMock(),
            downloader=MagicMock(),
            settings=settings,
        )

    # The loop reached iteration 2 (i.e. it didn't die on the first job's
    # process_job exception) before we stopped it via CancelledError.
    assert call_count["n"] == 2
    process_job_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_loop_survives_claim_exception(monkeypatch) -> None:
    from app import worker as worker_module

    call_count = {"n": 0}

    async def fake_claim():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient db error")
        raise asyncio.CancelledError

    queue = MagicMock()
    queue.claim = AsyncMock(side_effect=fake_claim)

    settings = MagicMock()
    settings.poll_interval_seconds = 0.01

    with pytest.raises(asyncio.CancelledError):
        await worker_module.worker_loop(
            bot=MagicMock(),
            pool=MagicMock(),
            queue=queue,
            limiter=MagicMock(),
            downloader=MagicMock(),
            settings=settings,
        )

    # Reached the second claim() call despite the first one raising —
    # proves a transient claim() failure doesn't kill the loop.
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_supervised_worker_restarts_after_unexpected_worker_loop_exit(monkeypatch) -> None:
    """Last-resort safety net: even if worker_loop itself somehow exits
    with an exception (it shouldn't, since it catches everything
    internally), the supervisor restarts it instead of silently losing a
    worker slot until someone notices and restarts the whole process."""
    from app import worker as worker_module

    call_count = {"n": 0}

    async def fake_worker_loop(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("worker_loop somehow crashed")
        raise asyncio.CancelledError

    monkeypatch.setattr(worker_module, "worker_loop", fake_worker_loop)
    monkeypatch.setattr(worker_module.asyncio, "sleep", AsyncMock())

    with pytest.raises(asyncio.CancelledError):
        await worker_module._supervised_worker(
            bot=MagicMock(),
            pool=MagicMock(),
            queue=MagicMock(),
            limiter=MagicMock(),
            downloader=MagicMock(),
            settings=MagicMock(),
            worker_index=0,
        )

    # worker_loop was called a second time after the first crash — proving
    # the supervisor restarted it rather than propagating the exception.
    assert call_count["n"] == 2
