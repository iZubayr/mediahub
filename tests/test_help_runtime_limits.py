from datetime import datetime
from unittest.mock import AsyncMock

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
        "REQUESTS_PER_MINUTE": "10",
        "DAILY_DOWNLOAD_LIMIT": "100",
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


@pytest.mark.asyncio
async def test_help_shows_admin_overridden_limits_not_env_defaults(monkeypatch) -> None:
    """Regression test for a real production bug: /help was built with
    settings.requests_per_minute (the static .env value) instead of
    get_int(pool, "requests_per_minute", settings) (the admin-panel
    overridable value), so an admin changing the limit via the panel had
    no visible effect on what /help told users -- even though the new
    value was correctly saved to Postgres."""
    settings = _settings(monkeypatch)

    class FakePool:
        pass

    monkeypatch.setattr("app.bot.get_text", _fake_get_text)
    monkeypatch.setattr("app.force_sub.list_channels", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.bot.upsert_user", AsyncMock(return_value=None))

    # Simulate an admin having overridden requests_per_minute to 25 via the
    # panel (i.e. what get_int would return once a DB row exists).
    async def fake_get_int(pool, key, settings):
        overrides = {"requests_per_minute": 25, "daily_download_limit": 100}
        return overrides[key]

    monkeypatch.setattr("app.bot.get_int", fake_get_int)

    dispatcher = create_dispatcher(settings, FakePool())
    bot = _make_bot()
    message = _make_message("/help")
    update = Update(update_id=1, message=message)

    await dispatcher.feed_update(bot, update)

    assert bot.called is True
    sent_request = bot.call_args.args[0]
    assert "25 ta so‘rov" in sent_request.text
    # The stale .env value (10) must NOT appear in the sent text.
    assert "10 ta so‘rov" not in sent_request.text
