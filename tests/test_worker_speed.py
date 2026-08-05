import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.downloader import MediaItem
from app.models import DownloadJob


def _fake_job() -> DownloadJob:
    return DownloadJob.create(
        user_id=1, chat_id=1, status_message_id=1, source_url="https://instagram.com/p/x/"
    )


@pytest.mark.asyncio
async def test_send_items_sends_all_items_with_bounded_concurrency() -> None:
    """Confirms send_items processes every item (order of completion isn't
    guaranteed under concurrency, but every item must be attempted exactly
    once) and respects the concurrency limit (no more than 2 in flight)."""
    from app import worker as worker_module

    items = [
        MediaItem(url=f"https://x/{i}.jpg", filename=f"{i}.jpg", media_type="photo")
        for i in range(1, 6)
    ]
    job = _fake_job()
    bot = MagicMock()
    downloader = MagicMock()
    settings = MagicMock()
    pool = MagicMock()

    in_flight = {"current": 0, "max_seen": 0}
    call_log = []

    async def fake_send_item(bot, downloader, settings, job, item, index, total, caption_base):
        in_flight["current"] += 1
        in_flight["max_seen"] = max(in_flight["max_seen"], in_flight["current"])
        call_log.append(index)
        await asyncio.sleep(0.01)
        in_flight["current"] -= 1

    with (
        patch("app.worker.get_text", AsyncMock(return_value="Caption")),
        patch("app.worker.send_item", fake_send_item),
        patch("app.worker.notify_status_text", MagicMock()),
    ):
        await worker_module.send_items(bot, pool, downloader, settings, job, items, len(items))

    assert sorted(call_log) == [1, 2, 3, 4, 5]
    assert in_flight["max_seen"] <= 2


@pytest.mark.asyncio
async def test_notify_status_text_does_not_block_caller() -> None:
    """notify_status_text must return immediately (not await the text
    lookup or the Telegram call inline) -- the whole point of the fix was
    to remove even the get_text() await from the critical path."""
    from app import worker as worker_module

    job = _fake_job()
    bot = MagicMock()
    pool = MagicMock()

    get_text_started = asyncio.Event()
    get_text_can_finish = asyncio.Event()

    async def slow_get_text(pool, key, **kwargs):
        get_text_started.set()
        await get_text_can_finish.wait()
        return "some status text"

    with (
        patch("app.worker.get_text", slow_get_text),
        patch("app.worker.update_status", AsyncMock()),
    ):
        worker_module.notify_status_text(bot, job, pool, "checking")
        # If notify_status_text were blocking, execution would never reach
        # here until slow_get_text resolves. Since it doesn't block, we can
        # release the background task immediately after confirming it's
        # running in the background.
        await asyncio.wait_for(get_text_started.wait(), timeout=1.0)
        get_text_can_finish.set()
        await asyncio.sleep(0)  # let the background task finish


@pytest.mark.asyncio
async def test_process_job_cleanup_runs_concurrently() -> None:
    """Regression test: the three cleanup steps in process_job's finally
    block (release_job_slot, downloader.cleanup, queue.acknowledge) must
    run concurrently via asyncio.gather, not sequentially."""
    from app import worker as worker_module

    job = _fake_job()
    bot = MagicMock()
    pool = MagicMock()
    queue = MagicMock()
    limiter = MagicMock()
    downloader = MagicMock()
    settings = MagicMock()

    call_order = []

    async def fake_release_job_slot(user_id, job_id):
        call_order.append("release_start")
        await asyncio.sleep(0.02)
        call_order.append("release_end")

    async def fake_cleanup(job_id):
        call_order.append("cleanup_start")
        await asyncio.sleep(0.02)
        call_order.append("cleanup_end")

    async def fake_acknowledge(job):
        call_order.append("ack_start")
        await asyncio.sleep(0.02)
        call_order.append("ack_end")

    limiter.release_job_slot = fake_release_job_slot
    downloader.cleanup = fake_cleanup
    queue.acknowledge = fake_acknowledge
    downloader.resolve = AsyncMock(
        side_effect=Exception("simulate failure to reach the finally block quickly")
    )

    with (
        patch("app.worker.get_text", AsyncMock(return_value="text")),
        patch("app.worker.notify_status_text", MagicMock()),
        patch("app.worker.update_status", AsyncMock()),
    ):
        await worker_module.process_job(bot, pool, queue, limiter, downloader, settings, job)

    # If the three cleanup calls ran sequentially, we'd see each one fully
    # start-then-end before the next starts. Running concurrently means all
    # three "_start" markers appear before any "_end" marker.
    starts = [event for event in call_order if event.endswith("_start")]
    first_end_index = next(i for i, event in enumerate(call_order) if event.endswith("_end"))
    assert all(call_order.index(s) < first_end_index for s in starts)
