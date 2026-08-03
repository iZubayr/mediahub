import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat, Message, Update, User

from app.bot import create_dispatcher
from app.config import Settings
from app.texts import TEXT_DEFS_BY_KEY
from app.worker_state import WorkerActivityTracker


def _settings(monkeypatch, **overrides) -> Settings:
    base = {
        "TELEGRAM_BOT_TOKEN": "123456:ABCDEFabcdefGHIJKLmnopQRSTUVwxyz1234567",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "PUBLIC_BASE_URL": "https://example.com",
        "TELEGRAM_WEBHOOK_SECRET": "0123456789abcdef",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    return Settings()


def _make_message(text: str, user_id: int = 777) -> Message:
    user = User(id=user_id, is_bot=False, first_name="User")
    chat = Chat(id=user_id, type="private")
    return Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text=text)


def _make_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.id = 999
    return bot


async def _fake_get_text(pool, key, **format_args):
    template = TEXT_DEFS_BY_KEY[key].default
    return template.format(**format_args) if format_args else template


@pytest.fixture(autouse=True)
def _patch_common(monkeypatch):
    monkeypatch.setattr("app.bot.get_text", _fake_get_text)
    monkeypatch.setattr("app.force_sub.list_channels", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.bot.upsert_user", AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_idle_tracker_runs_job_directly_without_enqueue(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    tracker = WorkerActivityTracker()
    downloader = MagicMock()

    with (
        patch("app.limits.RateLimiter.allow_request", AsyncMock(return_value=True)),
        patch("app.limits.RateLimiter.allow_daily_download", AsyncMock(return_value=True)),
        patch("app.limits.RateLimiter.acquire_job_slot", AsyncMock(return_value=True)),
        patch("app.queue.DownloadQueue.enqueue", AsyncMock()) as enqueue_mock,
        patch("app.worker.process_job", AsyncMock()) as process_job_mock,
    ):
        dispatcher = create_dispatcher(settings, FakePool(), tracker, downloader)
        bot = _make_bot()
        message = _make_message("https://www.instagram.com/reel/ABC123/")
        update = Update(update_id=1, message=message)

        await dispatcher.feed_update(bot, update)
        # The fast path schedules process_job as a background task —
        # give the event loop a tick to run it.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        enqueue_mock.assert_not_called()
        process_job_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_busy_tracker_falls_back_to_queue(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    tracker = WorkerActivityTracker()
    await tracker.enter()  # simulate a worker already processing something
    downloader = MagicMock()

    with (
        patch("app.limits.RateLimiter.allow_request", AsyncMock(return_value=True)),
        patch("app.limits.RateLimiter.allow_daily_download", AsyncMock(return_value=True)),
        patch("app.limits.RateLimiter.acquire_job_slot", AsyncMock(return_value=True)),
        patch("app.queue.DownloadQueue.enqueue", AsyncMock()) as enqueue_mock,
        patch("app.worker.process_job", AsyncMock()) as process_job_mock,
    ):
        dispatcher = create_dispatcher(settings, FakePool(), tracker, downloader)
        bot = _make_bot()
        message = _make_message("https://www.instagram.com/reel/ABC123/")
        update = Update(update_id=2, message=message)

        await dispatcher.feed_update(bot, update)

        enqueue_mock.assert_awaited_once()
        process_job_mock.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_mode_without_tracker_always_uses_queue(monkeypatch) -> None:
    """No activity_tracker/downloader passed (webhook mode) — must always
    go through the queue, never the fast path."""
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    with (
        patch("app.limits.RateLimiter.allow_request", AsyncMock(return_value=True)),
        patch("app.limits.RateLimiter.allow_daily_download", AsyncMock(return_value=True)),
        patch("app.limits.RateLimiter.acquire_job_slot", AsyncMock(return_value=True)),
        patch("app.queue.DownloadQueue.enqueue", AsyncMock()) as enqueue_mock,
    ):
        dispatcher = create_dispatcher(settings, FakePool())  # no tracker/downloader
        bot = _make_bot()
        message = _make_message("https://www.instagram.com/reel/ABC123/")
        update = Update(update_id=3, message=message)

        await dispatcher.feed_update(bot, update)

        enqueue_mock.assert_awaited_once()
