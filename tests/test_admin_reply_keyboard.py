from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, Update, User

from app.bot import create_dispatcher
from app.config import Settings
from app.texts import TEXT_DEFS_BY_KEY
from app.ui_constants import ADMIN_PANEL_BUTTON_TEXT


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


def _make_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.id = 999
    return bot


def _make_message(text: str, user_id: int = 555) -> Message:
    user = User(id=user_id, is_bot=False, first_name="Admin")
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


@pytest.mark.asyncio
async def test_tapping_reply_keyboard_button_opens_admin_panel(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    message = _make_message(ADMIN_PANEL_BUTTON_TEXT)
    update = Update(update_id=1, message=message)

    await dispatcher.feed_update(bot, update)

    assert bot.called is True
    sent_request = bot.call_args.args[0]
    assert "Admin panel" in sent_request.text
    # Confirms this went through admin_panel's inline-button menu, not
    # link_handler's "invalid link" rejection message.
    assert "havolasini" not in sent_request.text


@pytest.mark.asyncio
async def test_admin_button_text_from_non_admin_is_not_treated_as_admin_panel(monkeypatch) -> None:
    """A non-admin user typing the exact same text (unlikely, but possible)
    must not get the admin panel — is_admin() check inside the handler
    still applies."""
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    message = _make_message(ADMIN_PANEL_BUTTON_TEXT, user_id=777)  # not in ADMIN_IDS
    update = Update(update_id=2, message=message)

    await dispatcher.feed_update(bot, update)

    # Falls through to link_handler, which rejects it as not an Instagram link.
    assert bot.called is True
    sent_request = bot.call_args.args[0]
    assert "havolasini" in sent_request.text


@pytest.mark.asyncio
async def test_start_command_sends_reply_keyboard_to_admin(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    message = _make_message("/start")
    update = Update(update_id=3, message=message)

    await dispatcher.feed_update(bot, update)

    assert bot.called is True
    sent_request = bot.call_args.args[0]
    assert sent_request.reply_markup is not None
    button_texts = [
        button.text
        for row in sent_request.reply_markup.keyboard
        for button in row
    ]
    assert ADMIN_PANEL_BUTTON_TEXT in button_texts


@pytest.mark.asyncio
async def test_start_command_does_not_send_reply_keyboard_to_non_admin(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    message = _make_message("/start", user_id=777)  # not in ADMIN_IDS
    update = Update(update_id=4, message=message)

    await dispatcher.feed_update(bot, update)

    assert bot.called is True
    sent_request = bot.call_args.args[0]
    assert sent_request.reply_markup is None
