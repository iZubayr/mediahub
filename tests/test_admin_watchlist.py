from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot import create_dispatcher
from app.config import Settings
from app.texts import TEXT_DEFS_BY_KEY
from app.watchlist import UserSearchResult


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
async def test_main_menu_has_users_button(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    message = _make_message("/admin")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    sent_request = bot.call_args.args[0]
    button_texts = [b.text for row in sent_request.reply_markup.inline_keyboard for b in row]
    assert "🔍 Foydalanuvchilar" in button_texts


@pytest.mark.asyncio
async def test_search_prompt_sets_pending_state(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    callback = _make_callback("admin:searchuser")
    await dispatcher.feed_update(bot, Update(update_id=2, callback_query=callback))

    called_methods = [call.args[0].__class__.__name__ for call in bot.call_args_list]
    assert "EditMessageText" in called_methods


@pytest.mark.asyncio
async def test_searching_shows_results_with_watch_button(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    monkeypatch.setattr(
        "app.admin.search_users",
        AsyncMock(
            return_value=[
                UserSearchResult(user_id=777, username="testuser", first_name="Test", is_watched=False)
            ]
        ),
    )

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()

    # Step 1: admin taps "search" -> pending state set
    callback = _make_callback("admin:searchuser")
    await dispatcher.feed_update(bot, Update(update_id=3, callback_query=callback))

    # Step 2: admin sends the search query -> results shown
    message = _make_message("testuser")
    await dispatcher.feed_update(bot, Update(update_id=4, message=message))

    sent_request = bot.call_args.args[0]
    button_texts = [b.text for row in sent_request.reply_markup.inline_keyboard for b in row]
    assert any("Test" in t for t in button_texts)


@pytest.mark.asyncio
async def test_watch_button_adds_user_to_watchlist(monkeypatch) -> None:
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    add_watched_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("app.admin.add_watched_user", add_watched_mock)
    monkeypatch.setattr("app.admin.is_watched", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.admin.search_users",
        AsyncMock(
            return_value=[
                UserSearchResult(user_id=777, username="testuser", first_name="Test", is_watched=False)
            ]
        ),
    )

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    callback = _make_callback("admin:watchuser:777")
    await dispatcher.feed_update(bot, Update(update_id=5, callback_query=callback))

    add_watched_mock.assert_awaited_once()
    assert add_watched_mock.call_args.args[1] == 777
