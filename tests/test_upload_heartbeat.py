import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import DownloadJob


def _fake_job() -> DownloadJob:
    return DownloadJob.create(
        user_id=1, chat_id=1, status_message_id=1, source_url="https://instagram.com/p/x/"
    )


@pytest.mark.asyncio
async def test_heartbeat_does_not_fire_for_a_fast_upload() -> None:
    """If send_items finishes quickly (well under the heartbeat interval),
    the heartbeat must never fire -- a fast download shouldn't show any
    'still working' message."""
    from app import worker as worker_module

    job = _fake_job()
    bot = MagicMock()
    pool = MagicMock()
    downloader = MagicMock()
    settings = MagicMock()

    notify_mock = MagicMock()

    with (
        patch("app.worker.send_items", AsyncMock()),
        patch("app.worker.notify_status_text", notify_mock),
    ):
        await worker_module._send_items_with_heartbeat(
            bot, pool, downloader, settings, job, [], 0, heartbeat_interval_seconds=20
        )

    heartbeat_calls = [
        call for call in notify_mock.call_args_list if call.args[3] == "still_uploading"
    ]
    assert heartbeat_calls == []


@pytest.mark.asyncio
async def test_heartbeat_fires_during_a_slow_upload() -> None:
    """For an upload slower than the heartbeat interval, the heartbeat must
    fire with the still_uploading key at least once, and the background
    task must not leak past _send_items_with_heartbeat returning."""
    from app import worker as worker_module

    job = _fake_job()
    bot = MagicMock()
    pool = MagicMock()
    downloader = MagicMock()
    settings = MagicMock()

    async def slow_send_items(*args, **kwargs):
        await asyncio.sleep(0.1)

    notify_mock = MagicMock()

    with (
        patch("app.worker.send_items", slow_send_items),
        patch("app.worker.notify_status_text", notify_mock),
    ):
        await worker_module._send_items_with_heartbeat(
            bot, pool, downloader, settings, job, [], 0, heartbeat_interval_seconds=0.01
        )

    heartbeat_calls = [
        call for call in notify_mock.call_args_list if call.args[3] == "still_uploading"
    ]
    assert len(heartbeat_calls) >= 1
    # elapsed_seconds should be passed as a kwarg to notify_status_text.
    assert "elapsed_seconds" in heartbeat_calls[0].kwargs

    # Give the cancelled heartbeat task one event loop tick to actually
    # finish cancelling before checking for leaks.
    await asyncio.sleep(0)
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert all(t.done() or t.cancelled() for t in tasks)


@pytest.mark.asyncio
async def test_heartbeat_task_is_cancelled_even_if_send_items_raises() -> None:
    """If send_items itself raises (e.g. Telegram error mid-upload), the
    heartbeat task must still be cancelled (via the finally block) rather
    than leaking as a running background task forever."""
    from app import worker as worker_module

    job = _fake_job()
    bot = MagicMock()
    pool = MagicMock()
    downloader = MagicMock()
    settings = MagicMock()

    async def failing_send_items(*args, **kwargs):
        await asyncio.sleep(0.1)
        raise RuntimeError("upload failed")

    with (
        patch("app.worker.send_items", failing_send_items),
        patch("app.worker.notify_status_text", MagicMock()),
    ):
        with pytest.raises(RuntimeError):
            await worker_module._send_items_with_heartbeat(
                bot, pool, downloader, settings, job, [], 0, heartbeat_interval_seconds=0.01
            )

    # Give the cancelled heartbeat task one event loop tick to actually
    # finish cancelling before checking for leaks.
    await asyncio.sleep(0)
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert all(t.done() or t.cancelled() for t in tasks)
