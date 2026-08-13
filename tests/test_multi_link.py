from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message, Update, User

from app.bot import create_dispatcher
from app.config import Settings
from app.texts import TEXT_DEFS_BY_KEY


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


def _make_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.id = 999
    return bot


def _make_message(text: str, user_id: int = 777) -> Message:
    user = User(id=user_id, is_bot=False, first_name="User")
    chat = Chat(id=user_id, type="private")
    return Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text=text)


async def _fake_get_text(pool, key, **format_args):
    template = TEXT_DEFS_BY_KEY[key].default
    return template.format(**format_args) if format_args else template


@pytest.fixture(autouse=True)
def _patch_common(monkeypatch):
    monkeypatch.setattr("app.bot.get_text", _fake_get_text)
    monkeypatch.setattr("app.force_sub.list_channels", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.bot.upsert_user", AsyncMock(return_value=None))
    monkeypatch.setattr("app.limits.RateLimiter.allow_request", AsyncMock(return_value=True))
    monkeypatch.setattr("app.limits.RateLimiter.allow_daily_download", AsyncMock(return_value=True))
    monkeypatch.setattr("app.limits.RateLimiter.acquire_job_slot", AsyncMock(return_value=True))


@pytest.mark.asyncio
async def test_multiple_links_in_one_message_are_all_enqueued(monkeypatch) -> None:
    """Regression test for a real bug: a message containing several
    Instagram links only had the first one processed (extract_url only
    ever found one URL). All valid links in the message must be enqueued
    independently."""
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    enqueue_mock = AsyncMock()
    monkeypatch.setattr("app.queue.DownloadQueue.enqueue", enqueue_mock)

    dispatcher = create_dispatcher(settings, FakePool())  # no activity_tracker -> always queues
    bot = _make_bot()
    text = (
        "https://www.instagram.com/reel/AAA111/ "
        "https://www.instagram.com/p/BBB222/ "
        "https://www.instagram.com/reel/CCC333/"
    )
    message = _make_message(text)
    update = Update(update_id=1, message=message)

    await dispatcher.feed_update(bot, update)

    assert enqueue_mock.await_count == 3
    enqueued_urls = {call.args[0].source_url for call in enqueue_mock.call_args_list}
    assert enqueued_urls == {
        "https://www.instagram.com/reel/AAA111/",
        "https://www.instagram.com/p/BBB222/",
        "https://www.instagram.com/reel/CCC333/",
    }


@pytest.mark.asyncio
async def test_single_link_still_works_as_before(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    enqueue_mock = AsyncMock()
    monkeypatch.setattr("app.queue.DownloadQueue.enqueue", enqueue_mock)

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    message = _make_message("https://www.instagram.com/reel/ABC123/")
    update = Update(update_id=2, message=message)

    await dispatcher.feed_update(bot, update)

    enqueue_mock.assert_awaited_once()
    assert enqueue_mock.call_args.args[0].source_url == "https://www.instagram.com/reel/ABC123/"


@pytest.mark.asyncio
async def test_story_link_is_enqueued_for_an_admin_only(monkeypatch) -> None:
    settings = _settings(monkeypatch, ADMIN_IDS="555")

    class FakePool:
        pass

    enqueue_mock = AsyncMock()
    monkeypatch.setattr("app.queue.DownloadQueue.enqueue", enqueue_mock)
    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    story_url = "https://www.instagram.com/stories/someone/123456/"
    update = Update(update_id=4, message=_make_message(story_url, user_id=555))

    await dispatcher.feed_update(bot, update)

    enqueue_mock.assert_awaited_once()
    assert enqueue_mock.call_args.args[0].source_url == story_url


@pytest.mark.asyncio
async def test_story_link_remains_rejected_for_a_regular_user(monkeypatch) -> None:
    settings = _settings(monkeypatch, ADMIN_IDS="555")

    class FakePool:
        pass

    enqueue_mock = AsyncMock()
    monkeypatch.setattr("app.queue.DownloadQueue.enqueue", enqueue_mock)
    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    update = Update(
        update_id=5,
        message=_make_message("https://www.instagram.com/stories/someone/123456/", user_id=777),
    )

    await dispatcher.feed_update(bot, update)

    enqueue_mock.assert_not_awaited()
    assert bot.called is True


@pytest.mark.asyncio
async def test_mixed_valid_and_invalid_links_processes_only_valid_ones(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    enqueue_mock = AsyncMock()
    monkeypatch.setattr("app.queue.DownloadQueue.enqueue", enqueue_mock)

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    text = (
        "https://www.instagram.com/reel/AAA111/ "
        "https://example.com/not-instagram/ "
        "https://www.instagram.com/p/BBB222/"
    )
    message = _make_message(text)
    update = Update(update_id=3, message=message)

    await dispatcher.feed_update(bot, update)

    assert enqueue_mock.await_count == 2
    enqueued_urls = {call.args[0].source_url for call in enqueue_mock.call_args_list}
    assert enqueued_urls == {
        "https://www.instagram.com/reel/AAA111/",
        "https://www.instagram.com/p/BBB222/",
    }
