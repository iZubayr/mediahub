import asyncio
import logging
from enum import Enum, auto

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .channels import add_channel, list_channels, normalize_chat_ref, remove_channel_by_index
from .config import Settings
from .texts import TEXT_DEFS, get_text, reset_text, set_text
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
BROADCAST_BATCH_PAUSE_SECONDS = 1.0


class PendingAction(Enum):
    """What the admin's next text message should be interpreted as. Kept as
    simple in-process state (not a DB-backed FSM) since only admins use it
    and losing it on a restart just means re-opening the panel — an
    acceptable tradeoff for how rarely admin actions happen."""

    BROADCAST = auto()
    ADD_CHANNEL = auto()
    EDIT_TEXT = auto()


# user_id -> (action, extra) where extra carries e.g. the text_key being edited
_pending: dict[int, tuple[PendingAction, str | None]] = {}


def is_admin(settings: Settings, user_id: int) -> bool:
    return user_id in settings.admin_id_set


def _main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Statistika", callback_data="admin:stats")],
            [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="📡 Majburiy obuna kanallari", callback_data="admin:channels")],
            [InlineKeyboardButton(text="✏️ Matnlarni tahrirlash", callback_data="admin:texts")],
        ]
    )


def _back_markup(target: str = "admin:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=target)]]
    )


def _channels_markup(channels: list) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🗑 {index}. {channel.title or channel.chat_ref}",
                callback_data=f"admin:rmchannel:{index}",
            )
        ]
        for index, channel in enumerate(channels, start=1)
    ]
    rows.append([InlineKeyboardButton(text="➕ Kanal qo‘shish", callback_data="admin:addchannel")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _texts_list_markup() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=text_def.label, callback_data=f"admin:edittext:{text_def.key}")]
        for text_def in TEXT_DEFS
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _text_detail_markup(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"admin:dotext:{key}")],
            [InlineKeyboardButton(text="↩️ Standartga qaytarish", callback_data=f"admin:resettext:{key}")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin:texts")],
        ]
    )


def create_admin_router(settings: Settings, pool: asyncpg.Pool) -> Router:
    router = Router()

    # ---- Entry point -----------------------------------------------------

    @router.message(Command("admin"))
    async def admin_panel(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        _pending.pop(message.from_user.id, None)
        await message.answer("🛠 Admin panel", reply_markup=_main_menu_markup())

    # Keep the old text commands working too, as shortcuts.
    @router.message(Command("stats"))
    async def stats_command(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        await message.answer(await _stats_text(pool))

    @router.message(Command("channels"))
    async def channels_command(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        channels = await list_channels(pool)
        await message.answer(await _channels_text(channels), reply_markup=_channels_markup(channels))

    # ---- Callback router (all panel navigation edits the SAME message) ---

    @router.callback_query(F.data.startswith("admin:"))
    async def admin_callback(callback: CallbackQuery, bot: Bot) -> None:
        if (
            callback.from_user is None
            or not is_admin(settings, callback.from_user.id)
            or callback.message is None
            or callback.data is None
        ):
            await callback.answer()
            return

        action = callback.data.removeprefix("admin:")
        admin_id = callback.from_user.id

        if action == "home":
            _pending.pop(admin_id, None)
            await callback.message.edit_text("🛠 Admin panel", reply_markup=_main_menu_markup())

        elif action == "stats":
            await callback.message.edit_text(await _stats_text(pool), reply_markup=_back_markup())

        elif action == "channels":
            channels = await list_channels(pool)
            await callback.message.edit_text(
                await _channels_text(channels), reply_markup=_channels_markup(channels)
            )

        elif action == "addchannel":
            _pending[admin_id] = (PendingAction.ADD_CHANNEL, None)
            await callback.message.edit_text(
                "Kanal username’ini (@kanal) yoki ID’sini (-100...) yuboring.\n"
                "Bekor qilish uchun /cancel.",
                reply_markup=_back_markup("admin:channels"),
            )

        elif action.startswith("rmchannel:"):
            index = int(action.split(":", 1)[1])
            removed = await remove_channel_by_index(pool, index)
            channels = await list_channels(pool)
            prefix = f"🗑 O‘chirildi: {removed.title or removed.chat_ref}\n\n" if removed else ""
            await callback.message.edit_text(
                prefix + await _channels_text(channels), reply_markup=_channels_markup(channels)
            )

        elif action == "broadcast":
            _pending[admin_id] = (PendingAction.BROADCAST, None)
            await callback.message.edit_text(
                "Barcha foydalanuvchilarga yuboriladigan xabar matnini yuboring.\n"
                "Bekor qilish uchun /cancel.",
                reply_markup=_back_markup(),
            )

        elif action == "texts":
            _pending.pop(admin_id, None)
            await callback.message.edit_text(
                "Tahrirlamoqchi bo‘lgan matnni tanlang:", reply_markup=_texts_list_markup()
            )

        elif action.startswith("edittext:"):
            key = action.split(":", 1)[1]
            await callback.message.edit_text(
                await _text_detail_text(pool, key), reply_markup=_text_detail_markup(key)
            )

        elif action.startswith("dotext:"):
            key = action.split(":", 1)[1]
            _pending[admin_id] = (PendingAction.EDIT_TEXT, key)
            from .texts import TEXT_DEFS_BY_KEY

            text_def = TEXT_DEFS_BY_KEY[key]
            await callback.message.edit_text(
                f"«{text_def.label}» uchun yangi matn yuboring.\n"
                f"{text_def.help}\n\n"
                "Bekor qilish uchun /cancel.",
                reply_markup=_back_markup(f"admin:edittext:{key}"),
            )

        elif action.startswith("resettext:"):
            key = action.split(":", 1)[1]
            await reset_text(pool, key)
            await callback.message.edit_text(
                await _text_detail_text(pool, key), reply_markup=_text_detail_markup(key)
            )

        await callback.answer()

    # ---- /cancel -----------------------------------------------------------

    @router.message(Command("cancel"))
    async def cancel_command(message: Message) -> None:
        if message.from_user is None:
            return
        if _pending.pop(message.from_user.id, None) is not None:
            await message.answer("Bekor qilindi.")

    # ---- Pending text capture (broadcast / add channel / edit text) -------

    def _has_pending(message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in _pending

    @router.message(F.text, _has_pending)
    async def pending_text_capture(message: Message, bot: Bot) -> None:
        if message.from_user is None or message.text is None:
            return
        admin_id = message.from_user.id
        action, extra = _pending.pop(admin_id, (None, None))

        if action is PendingAction.BROADCAST:
            await run_broadcast(bot, pool, admin_id=admin_id, text=message.text)

        elif action is PendingAction.ADD_CHANNEL:
            await _handle_add_channel(message, bot, pool, admin_id)

        elif action is PendingAction.EDIT_TEXT and extra is not None:
            await set_text(pool, extra, message.text, updated_by=admin_id)
            await message.answer(f"✅ Yangilandi.\n\n{await _text_detail_text(pool, extra)}")

    return router


# ---- Helpers: rendered text blocks -----------------------------------------


async def _stats_text(pool: asyncpg.Pool) -> str:
    counts = await count_users(pool)
    return (
        "📊 Statistika:\n"
        f"Jami foydalanuvchi: {counts['total']}\n"
        f"Faol (bloklamagan): {counts['active']}\n"
        f"So‘nggi 24 soatda faol: {counts['today']}"
    )


async def _channels_text(channels: list) -> str:
    if not channels:
        return "Majburiy obuna kanallari yo‘q — hozircha bot cheklovsiz ishlaydi."
    lines = [
        f"{index}. {channel.title or channel.chat_ref} ({channel.chat_ref})"
        for index, channel in enumerate(channels, start=1)
    ]
    return "Majburiy obuna kanallari:\n\n" + "\n".join(lines)


async def _text_detail_text(pool: asyncpg.Pool, key: str) -> str:
    from .texts import TEXT_DEFS_BY_KEY, get_customized_keys

    text_def = TEXT_DEFS_BY_KEY[key]
    current = await get_text(pool, key)
    customized = key in await get_customized_keys(pool)
    status = "✏️ tahrirlangan" if customized else "standart"
    return f"«{text_def.label}» ({status}):\n\n{current}"


async def _handle_add_channel(message: Message, bot: Bot, pool: asyncpg.Pool, admin_id: int) -> None:
    if message.text is None:
        return
    chat_ref = normalize_chat_ref(message.text)
    if chat_ref is None:
        await message.answer(
            "Noto‘g‘ri format. @kanal_username yoki -100 bilan boshlanuvchi ID yuboring."
        )
        return

    # Confirm the bot can actually see this channel and is an admin in it
    # before saving — otherwise force-sub would silently no-op for this
    # channel later (see ForceSubscribeMiddleware's fail-open log).
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
        added_by=admin_id,
    )
    if added is None:
        await message.answer("Bu kanal ro‘yxatda allaqachon bor.")
        return

    channels = await list_channels(pool)
    await message.answer(
        f"✅ Qo‘shildi: {chat.title or chat_ref} ({chat_ref})\n\n" + await _channels_text(channels),
        reply_markup=_channels_markup(channels),
    )


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
