import asyncio
import logging

import asyncpg
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .admin import create_admin_router
from .config import Settings
from .db import create_pool
from .errors import QueueFull
from .force_sub import ForceSubscribeMiddleware
from .limits import RateLimiter
from .logging_config import configure_logging
from .models import DownloadJob
from .queue import DownloadQueue
from .users import upsert_user
from .validation import extract_url, validate_instagram_url


logger = logging.getLogger(__name__)


def create_dispatcher(settings: Settings, pool: asyncpg.Pool) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.message.middleware(ForceSubscribeMiddleware(settings, pool))
    dispatcher.callback_query.middleware(ForceSubscribeMiddleware(settings, pool))

    queue = DownloadQueue(pool, settings)
    limiter = RateLimiter(pool, settings)

    # Admin router is included first: /broadcast's text-capture handler must
    # see the admin's next message before the generic link_handler below
    # tries to parse it as an Instagram URL.
    dispatcher.include_router(create_admin_router(settings, pool))

    router = Router()

    @router.message.middleware()
    async def track_user(handler, message: Message, data):
        if message.from_user is not None and message.chat.type == ChatType.PRIVATE:
            await upsert_user(pool, message.from_user.id, message.from_user.username)
        return await handler(message, data)

    @router.callback_query(F.data == "force_sub_check")
    async def force_sub_recheck(callback: CallbackQuery) -> None:
        # If this handler runs at all, ForceSubscribeMiddleware already
        # confirmed membership for this callback (it would have blocked the
        # request otherwise), so we just confirm to the user.
        if callback.message is not None:
            await callback.message.answer("✅ Obuna tasdiqlandi. Endi botdan foydalanishingiz mumkin.")
        await callback.answer()

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        await message.answer(
            "Salom! Instagram’dan Reel, video, rasm va carousel yuklash uchun "
            "havolani yuboring.\n\n"
            "Private akkauntlar va login talab qiladigan kontent qo‘llab-quvvatlanmaydi.\n"
            "Yordam: /help"
        )

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(
            "Instagram media havolasini yuboring. Bot public Reel, video, rasm va "
            "carousel’larni qaytaradi.\n\n"
            f"Bir daqiqalik limit: {settings.requests_per_minute} ta so‘rov.\n"
            f"Kunlik limit: {settings.daily_download_limit} ta yuklash.\n\n"
            "Private, o‘chirilgan yoki mavjud bo‘lmagan kontent yuklanmaydi."
        )

    @router.message(F.text)
    async def link_handler(message: Message) -> None:
        if message.from_user is None or message.text is None:
            return

        user_id = message.from_user.id
        source_url = extract_url(message.text)
        if source_url is None:
            await message.answer("Instagram havolasini yuboring.")
            return

        try:
            source_url = validate_instagram_url(source_url)
        except Exception:
            await message.answer(
                "Havola noto‘g‘ri. Instagram’dagi post, Reel yoki story havolasini yuboring."
            )
            return

        try:
            if not await limiter.allow_request(user_id):
                await message.answer("So‘rovlar juda tez yuborildi. Bir daqiqadan keyin urinib ko‘ring.")
                return
            if not await limiter.allow_daily_download(user_id):
                await message.answer("Bugungi yuklash limitiga yetdingiz.")
                return
        except asyncpg.PostgresError:
            logger.exception("rate_limit_db_error user_id=%s", user_id)
            await message.answer("Server vaqtincha band. Birozdan keyin qayta urinib ko‘ring.")
            return

        status_message = await message.answer("⏳ So‘rov qabul qilindi, navbatga qo‘shilmoqda...")
        job = DownloadJob.create(
            user_id=user_id,
            chat_id=message.chat.id,
            status_message_id=status_message.message_id,
            source_url=source_url,
        )

        try:
            has_slot = await limiter.acquire_job_slot(user_id, job.job_id)
            if not has_slot:
                await status_message.edit_text(
                    "Sizda faol yuklashlar soni ko‘p. Avvalgi vazifa tugashini kuting."
                )
                return
            await queue.enqueue(job)
        except QueueFull:
            await limiter.release_job_slot(user_id, job.job_id)
            await status_message.edit_text(
                "Serverdagi navbat hozir to‘la. Birozdan keyin qayta urinib ko‘ring."
            )
        except asyncpg.PostgresError:
            await limiter.release_job_slot(user_id, job.job_id)
            logger.exception("enqueue_db_error job_id=%s", job.job_id)
            await status_message.edit_text("Server vaqtincha band. Keyinroq qayta urinib ko‘ring.")
        except Exception:
            await limiter.release_job_slot(user_id, job.job_id)
            logger.exception("enqueue_error job_id=%s", job.job_id)
            await status_message.edit_text("So‘rovni qabul qilishda xatolik yuz berdi.")

    dispatcher.include_router(router)
    return dispatcher


async def main() -> None:
    configure_logging()
    settings = Settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    pool = await create_pool(settings)
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = create_dispatcher(settings, pool)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
