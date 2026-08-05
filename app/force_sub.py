import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

import asyncpg
from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
    User,
)

from .channels import ForceSubChannel, list_channels
from .config import Settings


logger = logging.getLogger(__name__)

NOT_SUBSCRIBED_STATUSES = {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}

# Channel list rarely changes (admin adds/removes it manually), so caching it
# for a while avoids a DB round-trip on every single message. This is safe
# to set fairly high because admin.py calls invalidate_channel_cache() right
# after any add/remove, so admin edits take effect immediately regardless of
# this TTL — it only governs the worst case if invalidation is somehow
# missed (e.g. a different process instance).
CHANNEL_CACHE_TTL_SECONDS = 60

_cached_channels: list[ForceSubChannel] = []
_cache_expires_at: float = 0.0


def invalidate_channel_cache() -> None:
    """Forces the next _get_channels() call to hit the DB. Call this after
    any add_channel/remove_channel so an admin's edit is visible on their
    very next message, instead of waiting out CHANNEL_CACHE_TTL_SECONDS."""
    global _cache_expires_at
    _cache_expires_at = 0.0


class ForceSubscribeMiddleware(BaseMiddleware):
    """Blocks bot usage until the user has joined every channel the admin
    has registered via /addchannel. Requires the bot to be an admin in each
    channel — without that, get_chat_member fails for every user (not just
    the ones who haven't joined), which this middleware treats as "let the
    request through for that channel" rather than locking everyone out
    because of a misconfiguration.
    """

    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None:
        self.settings = settings
        self.pool = pool
        super().__init__()

    async def _get_channels(self) -> list[ForceSubChannel]:
        global _cached_channels, _cache_expires_at
        now = time.monotonic()
        if now >= _cache_expires_at:
            _cached_channels = await list_channels(self.pool)
            _cache_expires_at = now + CHANNEL_CACHE_TTL_SECONDS
        return _cached_channels

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        channels = await self._get_channels()
        if not channels:
            return await handler(event, data)

        user: User | None = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        if user.id in self.settings.admin_id_set:
            return await handler(event, data)

        bot: Bot = data["bot"]
        missing = await self._missing_channels(bot, user.id, channels)
        if not missing:
            return await handler(event, data)

        await self._prompt_join(event, missing)
        return None

    async def _missing_channels(
        self, bot: Bot, user_id: int, channels: list[ForceSubChannel]
    ) -> list[ForceSubChannel]:
        results = await asyncio.gather(
            *(self._check_one_channel(bot, user_id, channel) for channel in channels)
        )
        return [channel for channel, is_missing in zip(channels, results) if is_missing]

    async def _check_one_channel(self, bot: Bot, user_id: int, channel: ForceSubChannel) -> bool:
        try:
            member = await bot.get_chat_member(chat_id=channel.chat_ref, user_id=user_id)
        except TelegramBadRequest as error:
            # Most common cause: the bot itself isn't an admin in this
            # channel, so Telegram refuses the lookup for anyone. Log it
            # loudly but don't lock every user out for a config mistake.
            logger.error(
                "force_sub_check_failed channel=%s error=%s",
                channel.chat_ref,
                error.message,
            )
            return False
        return member.status in NOT_SUBSCRIBED_STATUSES

    async def _prompt_join(self, event: TelegramObject, missing: list[ForceSubChannel]) -> None:
        buttons: list[list[InlineKeyboardButton]] = []
        for index, channel in enumerate(missing, start=1):
            link = channel.invite_link or self._public_link(channel.chat_ref)
            if link:
                label = channel.title or f"Kanal {index}"
                buttons.append([InlineKeyboardButton(text=f"➡️ {label}", url=link)])
        buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="force_sub_check")])

        text = (
            "Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo‘ling, "
            "so‘ng «Tekshirish» tugmasini bosing."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)

        try:
            if isinstance(event, CallbackQuery) and event.message is not None:
                await event.message.answer(text, reply_markup=markup)
                await event.answer()
            elif isinstance(event, Message):
                await event.answer(text, reply_markup=markup)
        except TelegramForbiddenError:
            # User has blocked the bot; nothing to do.
            pass

    @staticmethod
    def _public_link(chat_ref: str) -> str | None:
        if chat_ref.startswith("@"):
            return f"https://t.me/{chat_ref.lstrip('@')}"
        return None
