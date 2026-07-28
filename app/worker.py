import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, URLInputFile
from redis.asyncio import Redis

from .config import Settings
from .downloader import InstagramDownloader, MediaItem
from .errors import MediaHubError
from .limits import RateLimiter
from .logging_config import configure_logging
from .models import DownloadJob
from .queue import DownloadQueue


logger = logging.getLogger(__name__)


async def update_status(bot: Bot, job: DownloadJob, text: str) -> None:
    try:
        await bot.edit_message_text(
            chat_id=job.chat_id,
            message_id=job.status_message_id,
            text=text,
        )
    except TelegramAPIError:
        logger.warning("status_update_failed job_id=%s", job.job_id, exc_info=True)


async def send_item(
    bot: Bot,
    downloader: InstagramDownloader,
    settings: Settings,
    job: DownloadJob,
    item: MediaItem,
    index: int,
    total: int,
) -> None:
    caption = f"MediaHub • {index}/{total}" if total > 1 else "MediaHub"
    for attempt in range(settings.retry_attempts + 1):
        direct_file = URLInputFile(
            item.url,
            filename=item.filename,
            headers=item.headers,
            timeout=settings.upload_timeout_seconds,
            bot=bot,
        )
        try:
            await _send_file(bot, job.chat_id, item, direct_file, caption)
            logger.info("stream_upload_completed job_id=%s index=%s", job.job_id, index)
            return
        except TelegramAPIError:
            logger.warning(
                "stream_upload_failed attempt=%s job_id=%s index=%s",
                attempt + 1,
                job.job_id,
                index,
                exc_info=True,
            )
            if attempt < settings.retry_attempts:
                await asyncio.sleep(2**attempt)

    logger.warning("stream_upload_failed_fallback job_id=%s index=%s", job.job_id, index)

    # Fallback only runs when URLInputFile/Telegram cannot consume the source
    # stream. The file is downloaded in chunks and removed after upload.
    temp_path = await downloader.download_to_temp(item, job.job_id, index)
    try:
        await _send_file(bot, job.chat_id, item, FSInputFile(temp_path), caption)
        logger.info("fallback_upload_completed job_id=%s index=%s", job.job_id, index)
    finally:
        Path(temp_path).unlink(missing_ok=True)


async def _send_file(
    bot: Bot,
    chat_id: int,
    item: MediaItem,
    input_file: URLInputFile | FSInputFile,
    caption: str,
) -> None:
    if item.media_type == "video":
        await bot.send_video(
            chat_id=chat_id,
            video=input_file,
            caption=caption,
            supports_streaming=True,
        )
    elif item.media_type == "photo":
        await bot.send_photo(chat_id=chat_id, photo=input_file, caption=caption)
    else:
        await bot.send_document(chat_id=chat_id, document=input_file, caption=caption)


def user_error_message(error: Exception) -> str:
    if isinstance(error, MediaHubError):
        return str(error)
    if isinstance(error, TelegramAPIError):
        return "Faylni Telegram’ga yuborishda xatolik yuz berdi."
    return "Yuklash vaqtida kutilmagan xatolik yuz berdi. Keyinroq qayta urinib ko‘ring."


async def process_job(
    bot: Bot,
    queue: DownloadQueue,
    limiter: RateLimiter,
    downloader: InstagramDownloader,
    settings: Settings,
    job: DownloadJob,
) -> None:
    try:
        await update_status(bot, job, "🔎 Instagram kontenti tekshirilmoqda...")
        items = await downloader.resolve(job.source_url)
        total = len(items)

        for index, item in enumerate(items, start=1):
            await update_status(bot, job, f"⬆️ Yuklanmoqda: {index}/{total}")
            await send_item(bot, downloader, settings, job, item, index, total)

        await update_status(bot, job, "✅ Tayyor. Media fayl(lar) yuborildi.")
        logger.info("job_completed job_id=%s items=%s", job.job_id, total)
    except Exception as error:
        logger.exception("job_failed job_id=%s", job.job_id)
        await update_status(bot, job, f"❌ {user_error_message(error)}")
    finally:
        await limiter.release_job_slot(job.user_id, job.job_id)
        await downloader.cleanup(job.job_id)
        await queue.acknowledge(job)


async def worker_loop(
    bot: Bot,
    queue: DownloadQueue,
    limiter: RateLimiter,
    downloader: InstagramDownloader,
    settings: Settings,
) -> None:
    while True:
        job = await queue.claim()
        if job is None:
            continue
        await process_job(bot, queue, limiter, downloader, settings, job)


async def main() -> None:
    configure_logging()
    settings = Settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await redis.ping()
    queue = DownloadQueue(redis, settings)
    await queue.recover_processing()
    limiter = RateLimiter(redis, settings)
    downloader = InstagramDownloader(settings)
    bot = Bot(token=settings.telegram_bot_token)
    tasks = [
        asyncio.create_task(worker_loop(bot, queue, limiter, downloader, settings))
        for _ in range(settings.worker_concurrency)
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await bot.session.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
