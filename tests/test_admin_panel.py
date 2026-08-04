from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update, User

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


def _make_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.id = 999
    return bot


def _make_message(text: str | None = None, user_id: int = 555) -> Message:
    user = User(id=user_id, is_bot=False, first_name="Admin")
    chat = Chat(id=user_id, type="private")
    return Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text=text)


def _make_callback(data: str, user_id: int = 555) -> CallbackQuery:
    user = User(id=user_id, is_bot=False, first_name="Admin")
    message = _make_message(text="🛠 Admin panel", user_id=user_id)
    return CallbackQuery(id="1", from_user=user, chat_instance="x", data=data, message=message)


async def _fake_get_text(pool, key, **format_args):
    template = TEXT_DEFS_BY_KEY[key].default
    return template.format(**format_args) if format_args else template


@pytest.fixture(autouse=True)
def _patch_texts(monkeypatch):
    monkeypatch.setattr("app.bot.get_text", _fake_get_text)
    monkeypatch.setattr("app.force_sub.list_channels", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.bot.upsert_user", AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_admin_command_shows_main_menu_with_buttons(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    message = _make_message("/admin")
    update = Update(update_id=1, message=message)

    await dispatcher.feed_update(bot, update)

    assert bot.called is True
    sent_request = bot.call_args.args[0]
    assert sent_request.reply_markup is not None
    button_texts = [
        button.text
        for row in sent_request.reply_markup.inline_keyboard
        for button in row
    ]
    assert "📊 Statistika" in button_texts
    assert "✏️ Matnlarni tahrirlash" in button_texts
    assert "⚙️ Rate limit sozlamalari" in button_texts


@pytest.mark.asyncio
async def test_limits_callback_shows_all_rate_limit_buttons(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    callback = _make_callback("admin:limits")
    update = Update(update_id=10, callback_query=callback)

    await dispatcher.feed_update(bot, update)

    called_methods = [call.args[0].__class__.__name__ for call in bot.call_args_list]
    assert "EditMessageText" in called_methods
    edit_call = next(
        call for call in bot.call_args_list
        if call.args[0].__class__.__name__ == "EditMessageText"
    )
    button_texts = [
        button.text
        for row in edit_call.args[0].reply_markup.inline_keyboard
        for button in row
    ]
    assert "Daqiqalik so‘rov limiti" in button_texts
    assert "Kunlik yuklash limiti" in button_texts


@pytest.mark.asyncio
async def test_admin_stats_callback_edits_same_message(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    monkeypatch.setattr(
        "app.admin.count_users",
        AsyncMock(return_value={"total": 5, "active": 4, "today": 2}),
    )

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    callback = _make_callback("admin:stats")
    update = Update(update_id=2, callback_query=callback)

    await dispatcher.feed_update(bot, update)

    # editMessageText should have been called (not sendMessage), proving
    # navigation updates the existing panel message instead of spamming a
    # new one into the chat.
    called_methods = [call.args[0].__class__.__name__ for call in bot.call_args_list]
    assert "EditMessageText" in called_methods


@pytest.mark.asyncio
async def test_force_sub_check_callback_not_intercepted_by_admin_router(monkeypatch) -> None:
    """Regression guard: admin router matches on the 'admin:' prefix only,
    so the unrelated force_sub_check callback must still reach its own
    handler in bot.py."""
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()

    user = User(id=555, is_bot=False, first_name="Admin")
    message = _make_message(text="join prompt", user_id=555)
    callback = CallbackQuery(
        id="2", from_user=user, chat_instance="x", data="force_sub_check", message=message
    )
    update = Update(update_id=3, callback_query=callback)

    await dispatcher.feed_update(bot, update)

    called_methods = [call.args[0].__class__.__name__ for call in bot.call_args_list]
    # force_sub_recheck in bot.py sends a fresh confirmation message.
    assert "SendMessage" in called_methods


@pytest.mark.asyncio
async def test_edit_text_flow_updates_stored_text(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    set_text_mock = AsyncMock()
    monkeypatch.setattr("app.admin.set_text", set_text_mock)
    monkeypatch.setattr(
        "app.admin._text_detail_text", AsyncMock(return_value="«Salomlashuv» (tahrirlangan):\n\nYangi matn")
    )

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()

    # Step 1: admin taps "edit" on the start text -> pending state set
    callback = _make_callback("admin:dotext:start")
    await dispatcher.feed_update(bot, Update(update_id=4, callback_query=callback))

    # Step 2: admin sends the new text -> should be captured and stored
    message = _make_message("Yangi salomlashuv matni")
    await dispatcher.feed_update(bot, Update(update_id=5, message=message))

    set_text_mock.assert_awaited_once()
    args = set_text_mock.call_args.args
    assert args[1] == "start"
    assert args[2] == "Yangi salomlashuv matni"
