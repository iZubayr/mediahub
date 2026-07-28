import asyncio
import logging
from uuid import uuid4

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from redis.asyncio import Redis
from redis.exceptions import RedisError

from .config import Settings
from .errors import QueueFull
from .limits import RateLimiter
from .logging_config import configure_logging
from .models import DownloadJob
from .queue import DownloadQueue
from .validation import extract_url, validate_instagram_url


logger = logging.getLogger(__name__)


def create_dispatcher(settings: Settings, redis: Redis) -> Dispatcher:
    dispatcher = Dispatcher()
    router = Router()
    queue = DownloadQueue(redis, settings)
    limiter = RateLimiter(redis, settings)

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
        except RedisError:
            logger.exception("rate_limit_redis_error user_id=%s", user_id)
            await message.answer("Server vaqtincha band. Birozdan keyin qayta urinib ko‘ring.")
            return

        status_message = await message.answer("⏳ So‘rov qabul qilindi, navbatga qo‘shilmoqda...")
        job = DownloadJob.create(
            job_id=uuid4().hex,
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
        except RedisError:
            await limiter.release_job_slot(user_id, job.job_id)
            logger.exception("enqueue_redis_error job_id=%s", job.job_id)
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

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await redis.ping()
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = create_dispatcher(settings, redis)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
