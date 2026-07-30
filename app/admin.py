import asyncio
import logging

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .channels import add_channel, list_channels, normalize_chat_ref, remove_channel_by_index
from .config import Settings
from .users import (
    count_users,
    create_broadcast,
    finish_broadcast,
    iter_broadcast_targets,
    mark_blocked,
)


logger = logging.getLogger(__name__)

# Telegram allows roughly 30 messages/second in aggregate across different
# chats. Sending in small batches with a short pause between batches keeps
# a broadcast well under that without needing a queueing library.
BROADCAST_BATCH_SIZE = 25
BROADCAST_BATCH_PAUSE_SECONDS = 1.0

# Pending broadcast text is held here between "/broadcast" and the admin's
# next message, per admin id, so a mistaken /broadcast doesn't immediately
# fire on stray text. In-process state is fine here: only admins use it, and
# losing it on a worker/webhook restart just means re-typing /broadcast.
_pending_broadcast: dict[int, bool] = {}


def is_admin(settings: Settings, user_id: int) -> bool:
    return user_id in settings.admin_id_set


def create_admin_router(settings: Settings, pool: asyncpg.Pool) -> Router:
    router = Router()

    @router.message(Command("admin"))
    async def admin_panel(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        await message.answer(
            "Admin panel:\n\n"
            "/stats — foydalanuvchilar statistikasi\n"
            "/broadcast — barcha foydalanuvchilarga xabar yuborish\n\n"
            "Majburiy obuna kanallari:\n"
            "/channels — ro‘yxatni ko‘rish\n"
            "/addchannel @kanal — kanal qo‘shish (yoki -100... ID)\n"
            "/removechannel N — ro‘yxatdagi N-raqamli kanalni o‘chirish"
        )

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        counts = await count_users(pool)
        await message.answer(
            "📊 Statistika:\n"
            f"Jami foydalanuvchi: {counts['total']}\n"
            f"Faol (bloklamagan): {counts['active']}\n"
            f"So‘nggi 24 soatda faol: {counts['today']}"
        )

    @router.message(Command("channels"))
    async def channels_list(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        channels = await list_channels(pool)
        if not channels:
            await message.answer(
                "Majburiy obuna kanallari yo‘q — hozircha bot cheklovsiz ishlaydi.\n"
                "Qo‘shish uchun: /addchannel @kanal"
            )
            return
        lines = [
            f"{index}. {channel.title or channel.chat_ref} ({channel.chat_ref})"
            for index, channel in enumerate(channels, start=1)
        ]
        await message.answer("Majburiy obuna kanallari:\n\n" + "\n".join(lines))

    @router.message(Command("addchannel"))
    async def channel_add(message: Message, command: CommandObject, bot: Bot) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        if not command.args:
            await message.answer(
                "Foydalanish: /addchannel @kanal_username\n"
                "Yopiq kanal uchun: /addchannel -1001234567890"
            )
            return

        chat_ref = normalize_chat_ref(command.args)
        if chat_ref is None:
            await message.answer(
                "Noto‘g‘ri format. @kanal_username yoki -100 bilan boshlanuvchi ID yuboring."
            )
            return

        # Confirm the bot can actually see this channel and is an admin in
        # it before saving — otherwise force-sub would silently no-op for
        # this channel later (see ForceSubscribeMiddleware's fail-open log).
        try:
            chat = await bot.get_chat(chat_ref)
            bot_member = await bot.get_chat_member(chat_id=chat_ref, user_id=bot.id)
        except TelegramBadRequest as error:
            await message.answer(
                f"❌ Botga bu kanalni topib bo‘lmadi: {error.message}\n"
                "Botni kanalga admin qilib qo‘shganingizni tekshiring."
            )
            return

        if bot_member.status not in {"administrator", "creator"}:
            await message.answer(
                "❌ Bot bu kanalda admin emas. Avval botni kanalga admin qilib qo‘shing, "
                "so‘ng qaytadan urinib ko‘ring."
            )
            return

        invite_link = chat.invite_link
        if invite_link is None and not chat_ref.startswith("@"):
            try:
                created = await bot.create_chat_invite_link(chat_id=chat_ref)
                invite_link = created.invite_link
            except TelegramBadRequest as error:
                logger.warning(
                    "invite_link_creation_failed channel=%s error=%s", chat_ref, error.message
                )

        added = await add_channel(
            pool,
            chat_ref=chat_ref,
            title=chat.title,
            invite_link=invite_link,
            added_by=message.from_user.id,
        )
        if added is None:
            await message.answer("Bu kanal ro‘yxatda allaqachon bor.")
            return

        await message.answer(f"✅ Qo‘shildi: {chat.title or chat_ref} ({chat_ref})")

    @router.message(Command("removechannel"))
    async def channel_remove(message: Message, command: CommandObject) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        if not command.args or not command.args.strip().isdigit():
            await message.answer(
                "Foydalanish: /removechannel N\n"
                "N — /channels ro‘yxatidagi tartib raqami."
            )
            return

        index = int(command.args.strip())
        removed = await remove_channel_by_index(pool, index)
        if removed is None:
            await message.answer("Bunday raqamli kanal topilmadi. /channels orqali ro‘yxatni tekshiring.")
            return
        await message.answer(f"🗑 O‘chirildi: {removed.title or removed.chat_ref}")

    @router.message(Command("broadcast"))
    async def broadcast_start(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        _pending_broadcast[message.from_user.id] = True
        await message.answer(
            "Barcha foydalanuvchilarga yuboriladigan xabar matnini yuboring.\n"
            "Bekor qilish uchun /cancel."
        )

    @router.message(Command("cancel"))
    async def broadcast_cancel(message: Message) -> None:
        if message.from_user is None:
            return
        if _pending_broadcast.pop(message.from_user.id, None):
            await message.answer("Bekor qilindi.")

    def _has_pending_broadcast(message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in _pending_broadcast

    @router.message(F.text, _has_pending_broadcast)
    async def broadcast_text_capture(message: Message, bot: Bot) -> None:
        if message.from_user is None or message.text is None:
            return
        _pending_broadcast.pop(message.from_user.id, None)
        await run_broadcast(bot, pool, admin_id=message.from_user.id, text=message.text)

    return router


async def run_broadcast(bot: Bot, pool: asyncpg.Pool, admin_id: int, text: str) -> None:
    counts = await count_users(pool)
    broadcast_id = await create_broadcast(pool, admin_id, text, total=counts["active"])
    await bot.send_message(admin_id, f"⏳ Yuborish boshlandi: {counts['active']} foydalanuvchiga...")

    sent = 0
    failed = 0
    async for batch in iter_broadcast_targets(pool):
        for user_id in batch:
            try:
                await bot.send_message(user_id, text)
                sent += 1
            except TelegramRetryAfter as error:
                await asyncio.sleep(error.retry_after)
                try:
                    await bot.send_message(user_id, text)
                    sent += 1
                except Exception:
                    failed += 1
            except TelegramForbiddenError:
                await mark_blocked(pool, user_id, True)
                failed += 1
            except Exception:
                logger.exception("broadcast_send_failed user_id=%s", user_id)
                failed += 1
        await asyncio.sleep(BROADCAST_BATCH_PAUSE_SECONDS)

    await finish_broadcast(pool, broadcast_id, sent, failed)
    await bot.send_message(admin_id, f"✅ Yuborish tugadi.\nYuborildi: {sent}\nXato: {failed}")