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
        "ADMIN_IDS": "555",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    return Settings()


def _make_message(text: str, user_id: int = 555) -> Message:
    user = User(id=user_id, is_bot=False, first_name="Admin")
    chat = Chat(id=user_id, type="private")
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=chat,
        from_user=user,
        text=text,
    )


def _make_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.id = 999
    return bot


async def _fake_get_text(pool, key, **format_args):
    template = TEXT_DEFS_BY_KEY[key].default
    return template.format(**format_args) if format_args else template


@pytest.mark.asyncio
async def test_admin_start_command_reaches_start_handler_not_broadcast_capture(monkeypatch) -> None:
    """Regression test for a real bug: without this fix, any text message from
    an admin (including /start or a link) was swallowed by the broadcast
    text-capture handler even with no pending /broadcast, because the old
    filter matched on is_admin() alone and returned None from inside the
    handler instead of not matching at all."""
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())

    monkeypatch.setattr(
        "app.force_sub.list_channels", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "app.bot.upsert_user", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("app.bot.get_text", _fake_get_text)

    message = _make_message("/start")
    bot = _make_bot()
    update = Update(update_id=1, message=message)

    await dispatcher.feed_update(bot, update)

    assert bot.called is True
    sent_request = bot.call_args.args[0]
    assert "Salom" in sent_request.text


@pytest.mark.asyncio
async def test_admin_plain_link_reaches_link_handler_when_no_pending_broadcast(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())

    monkeypatch.setattr(
        "app.force_sub.list_channels", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "app.bot.upsert_user", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("app.bot.get_text", _fake_get_text)

    message = _make_message("just some random text, not a command")
    bot = _make_bot()
    update = Update(update_id=2, message=message)

    await dispatcher.feed_update(bot, update)

    assert bot.called is True
    sent_request = bot.call_args.args[0]
    # link_handler's rejection message for non-Instagram text
    assert "havolasini" in sent_request.text
