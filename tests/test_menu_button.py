from unittest.mock import AsyncMock

import pytest
from aiogram.types import BotCommandScopeChat, BotCommandScopeDefault, MenuButtonCommands

from app.bot import setup_menu_button
from app.config import Settings


def _settings(monkeypatch, **overrides) -> Settings:
    base = {
        "TELEGRAM_BOT_TOKEN": "123456:ABCDEFabcdefGHIJKLmnopQRSTUVwxyz1234567",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "PUBLIC_BASE_URL": "https://example.com",
        "TELEGRAM_WEBHOOK_SECRET": "0123456789abcdef",
        "ADMIN_IDS": "555,777",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    return Settings()


@pytest.mark.asyncio
async def test_default_commands_and_menu_button_are_set(monkeypatch) -> None:
    settings = _settings(monkeypatch)
    bot = AsyncMock()

    await setup_menu_button(bot, settings)

    default_call = next(
        call for call in bot.set_my_commands.call_args_list
        if isinstance(call.kwargs.get("scope"), BotCommandScopeDefault)
    )
    command_names = [c.command for c in default_call.kwargs["commands"]]
    assert "start" in command_names
    assert "help" in command_names
    assert "admin" not in command_names  # not exposed to everyone

    bot.set_chat_menu_button.assert_awaited_once()
    menu_button = bot.set_chat_menu_button.call_args.kwargs["menu_button"]
    assert isinstance(menu_button, MenuButtonCommands)


@pytest.mark.asyncio
async def test_each_admin_gets_admin_command_in_their_own_scope(monkeypatch) -> None:
    settings = _settings(monkeypatch)
    bot = AsyncMock()

    await setup_menu_button(bot, settings)

    admin_scoped_calls = [
        call for call in bot.set_my_commands.call_args_list
        if isinstance(call.kwargs.get("scope"), BotCommandScopeChat)
    ]
    scoped_chat_ids = {call.kwargs["scope"].chat_id for call in admin_scoped_calls}
    assert scoped_chat_ids == {555, 777}

    for call in admin_scoped_calls:
        command_names = [c.command for c in call.kwargs["commands"]]
        assert "admin" in command_names
        assert "start" in command_names  # admins still get the base commands too


@pytest.mark.asyncio
async def test_one_admin_setup_failure_does_not_block_the_others(monkeypatch) -> None:
    """An admin who has never opened a chat with the bot yet will make
    set_my_commands fail for their scope (Telegram has no chat to scope to).
    That must not prevent the other admin's menu from being configured."""
    settings = _settings(monkeypatch)
    bot = AsyncMock()

    call_log = []

    async def flaky_set_my_commands(commands, scope):
        call_log.append(scope)
        if isinstance(scope, BotCommandScopeChat) and scope.chat_id == 555:
            raise RuntimeError("chat not found")

    bot.set_my_commands.side_effect = flaky_set_my_commands

    await setup_menu_button(bot, settings)

    admin_scoped = [s for s in call_log if isinstance(s, BotCommandScopeChat)]
    assert {s.chat_id for s in admin_scoped} == {555, 777}
