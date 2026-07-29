from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberLeft, ChatMemberMember, Message, User

from app.channels import ForceSubChannel
from app.config import Settings
from app.force_sub import ForceSubscribeMiddleware


def _settings(monkeypatch, **overrides) -> Settings:
    base = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "PUBLIC_BASE_URL": "https://example.com",
        "TELEGRAM_WEBHOOK_SECRET": "0123456789abcdef",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    return Settings()


def _one_channel() -> list[ForceSubChannel]:
    return [
        ForceSubChannel(
            channel_id=1,
            chat_ref="@testchan",
            title="Test Channel",
            invite_link=None,
            added_by=1,
        )
    ]


@pytest.mark.asyncio
async def test_subscribed_user_passes_through(monkeypatch) -> None:
    settings = _settings(monkeypatch)
    middleware = ForceSubscribeMiddleware(settings, pool=MagicMock())
    monkeypatch.setattr(
        "app.force_sub.list_channels", AsyncMock(return_value=_one_channel())
    )

    user = User(id=555, is_bot=False, first_name="Test")
    bot = MagicMock()
    bot.get_chat_member = AsyncMock(
        return_value=ChatMemberMember(user=user, status=ChatMemberStatus.MEMBER)
    )

    message = MagicMock(spec=Message)
    message.from_user = user

    called = False

    async def handler(event, data):
        nonlocal called
        called = True
        return "ok"

    result = await middleware(handler, message, {"bot": bot})
    assert called is True
    assert result == "ok"


@pytest.mark.asyncio
async def test_unsubscribed_user_is_blocked_and_prompted(monkeypatch) -> None:
    settings = _settings(monkeypatch)
    middleware = ForceSubscribeMiddleware(settings, pool=MagicMock())
    monkeypatch.setattr(
        "app.force_sub.list_channels", AsyncMock(return_value=_one_channel())
    )

    user = User(id=555, is_bot=False, first_name="Test")
    bot = MagicMock()
    bot.get_chat_member = AsyncMock(
        return_value=ChatMemberLeft(user=user, status=ChatMemberStatus.LEFT)
    )

    message = MagicMock(spec=Message)
    message.from_user = user
    message.answer = AsyncMock()

    called = False

    async def handler(event, data):
        nonlocal called
        called = True
        return "ok"

    await middleware(handler, message, {"bot": bot})
    assert called is False
    assert message.answer.called is True


@pytest.mark.asyncio
async def test_admin_bypasses_membership_check(monkeypatch) -> None:
    settings = _settings(monkeypatch, ADMIN_IDS="555")
    middleware = ForceSubscribeMiddleware(settings, pool=MagicMock())
    monkeypatch.setattr(
        "app.force_sub.list_channels", AsyncMock(return_value=_one_channel())
    )

    user = User(id=555, is_bot=False, first_name="Test")
    bot = MagicMock()
    bot.get_chat_member = AsyncMock(side_effect=AssertionError("should not be called for admins"))

    message = MagicMock(spec=Message)
    message.from_user = user

    called = False

    async def handler(event, data):
        nonlocal called
        called = True
        return "ok"

    await middleware(handler, message, {"bot": bot})
    assert called is True
    bot.get_chat_member.assert_not_called()


@pytest.mark.asyncio
async def test_no_channels_registered_skips_check_entirely(monkeypatch) -> None:
    settings = _settings(monkeypatch)
    middleware = ForceSubscribeMiddleware(settings, pool=MagicMock())
    monkeypatch.setattr(
        "app.force_sub.list_channels", AsyncMock(return_value=[])
    )

    user = User(id=555, is_bot=False, first_name="Test")
    bot = MagicMock()
    bot.get_chat_member = AsyncMock(side_effect=AssertionError("should not be called"))

    message = MagicMock(spec=Message)
    message.from_user = user

    async def handler(event, data):
        return "ok"

    result = await middleware(handler, message, {"bot": bot})
    assert result == "ok"
    bot.get_chat_member.assert_not_called()


@pytest.mark.asyncio
async def test_bot_not_admin_in_channel_fails_open_for_that_channel(monkeypatch) -> None:
    """If the bot can't check membership (e.g. not an admin in the channel),
    that channel is skipped rather than blocking every user."""
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import GetChatMember

    settings = _settings(monkeypatch)
    middleware = ForceSubscribeMiddleware(settings, pool=MagicMock())
    monkeypatch.setattr(
        "app.force_sub.list_channels", AsyncMock(return_value=_one_channel())
    )

    user = User(id=555, is_bot=False, first_name="Test")
    bot = MagicMock()
    bot.get_chat_member = AsyncMock(
        side_effect=TelegramBadRequest(
            method=GetChatMember(chat_id="@testchan", user_id=555),
            message="Bad Request: not enough rights",
        )
    )

    message = MagicMock(spec=Message)
    message.from_user = user

    called = False

    async def handler(event, data):
        nonlocal called
        called = True
        return "ok"

    result = await middleware(handler, message, {"bot": bot})
    assert called is True
    assert result == "ok"
