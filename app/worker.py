import asyncio
import logging
from pathlib import Path

import asyncpg
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, URLInputFile

from .config import Settings
from .db import create_pool
from .downloader import InstagramDownloader, MediaItem
from .errors import MediaHubError
from .limits import RateLimiter
from .logging_config import configure_logging
from .models import DownloadJob
from .queue import DownloadQueue
from .texts import get_text
from .worker_state import WorkerActivityTracker


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


def notify_status(bot: Bot, job: DownloadJob, text: str) -> None:
    """Fire-and-forget status update: schedules the Telegram edit as a
    background task instead of awaiting it inline. Status text is purely
    informational (what the user sees while waiting), so there's no reason
    to block the actual download/upload work — which is on the real
    critical path — on a Telegram API round-trip just to update a progress
    message. Errors are still logged by update_status itself.
    """
    asyncio.ensure_future(update_status(bot, job, text))


async def send_item(
    bot: Bot,
    pool: asyncpg.Pool,
    downloader: InstagramDownloader,
    settings: Settings,
    job: DownloadJob,
    item: MediaItem,
    index: int,
    total: int,
) -> None:
    caption_base = await get_text(pool, "media_caption")
    caption = f"{caption_base} • {index}/{total}" if total > 1 else caption_base
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
    temp_path = await downloader.download_to_temp(item, str(job.job_id), index)
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


async def user_error_message(pool: asyncpg.Pool, error: Exception) -> str:
    if isinstance(error, MediaHubError):
        return str(error)
    if isinstance(error, TelegramAPIError):
        return "Faylni Telegram’ga yuborishda xatolik yuz berdi."
    return await get_text(pool, "unexpected_download_error")


async def process_job(
    bot: Bot,
    pool: asyncpg.Pool,
    queue: DownloadQueue,
    limiter: RateLimiter,
    downloader: InstagramDownloader,
    settings: Settings,
    job: DownloadJob,
) -> None:
    try:
        notify_status(bot, job, await get_text(pool, "checking"))
        result = await downloader.resolve(job.source_url)
        items = result.items
        total = len(items)

        for index, item in enumerate(items, start=1):
            notify_status(
                bot, job, await get_text(pool, "uploading", index=index, total=total)
            )
            await send_item(bot, pool, downloader, settings, job, item, index, total)

        if result.partial:
            await update_status(bot, job, await get_text(pool, "partial_carousel"))
        else:
            await update_status(bot, job, await get_text(pool, "done"))
        logger.info("job_completed job_id=%s items=%s partial=%s", job.job_id, total, result.partial)
    except Exception as error:
        logger.exception("job_failed job_id=%s", job.job_id)
        message = await user_error_message(pool, error)
        await update_status(bot, job, f"❌ {message}")
    finally:
        await limiter.release_job_slot(job.user_id, job.job_id)
        await downloader.cleanup(str(job.job_id))
        await queue.acknowledge(job)


async def worker_loop(
    bot: Bot,
    pool: asyncpg.Pool,
    queue: DownloadQueue,
    limiter: RateLimiter,
    downloader: InstagramDownloader,
    settings: Settings,
    activity_tracker: WorkerActivityTracker | None = None,
) -> None:
    while True:
        try:
            job = await queue.claim()
        except Exception:
            # A transient DB/network hiccup here must not kill this loop —
            # without this guard, one failed claim() would propagate out of
            # asyncio.gather() in main() and take the entire worker process
            # offline until someone notices and restarts it by hand.
            logger.exception("queue_claim_failed")
            await asyncio.sleep(settings.poll_interval_seconds)
            continue

        if job is None:
            await asyncio.sleep(settings.poll_interval_seconds)
            continue

        if activity_tracker is not None:
            await activity_tracker.enter()
        try:
            await process_job(bot, pool, queue, limiter, downloader, settings, job)
        except Exception:
            # process_job already handles and reports expected errors to the
            # user; this is a final safety net for anything that slipped
            # through, so a single bad job can't kill the whole worker.
            logger.exception("process_job_crashed job_id=%s", job.job_id)
        finally:
            if activity_tracker is not None:
                await activity_tracker.exit()


async def stuck_job_recovery_loop(queue: DownloadQueue, settings: Settings) -> None:
    # Periodically requeue jobs abandoned by a crashed/restarted worker,
    # since Postgres has no automatic lock-release like Redis's processing
    # list recovery had.
    while True:
        await asyncio.sleep(max(settings.stuck_job_timeout_seconds // 2, 30))
        try:
            await queue.recover_stuck()
        except Exception:
            logger.exception("stuck_job_recovery_failed")


async def _supervised_worker(
    bot: Bot,
    pool: asyncpg.Pool,
    queue: DownloadQueue,
    limiter: RateLimiter,
    downloader: InstagramDownloader,
    settings: Settings,
    worker_index: int,
    activity_tracker: WorkerActivityTracker | None = None,
) -> None:
    """Wraps worker_loop so that if it ever exits unexpectedly (it shouldn't,
    since worker_loop already catches everything internally, but this is a
    last-resort safety net), it gets logged and restarted instead of quietly
    reducing worker capacity until the whole process is restarted by hand."""
    while True:
        try:
            await worker_loop(bot, pool, queue, limiter, downloader, settings, activity_tracker)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker_%s_crashed_restarting", worker_index)
            await asyncio.sleep(5)


async def main() -> None:
    configure_logging()
    settings = Settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    pool = await create_pool(settings)
    queue = DownloadQueue(pool, settings)
    await queue.recover_stuck()
    limiter = RateLimiter(pool, settings)
    downloader = InstagramDownloader(settings)
    bot = Bot(token=settings.telegram_bot_token)
    tasks = [
        asyncio.create_task(
            _supervised_worker(bot, pool, queue, limiter, downloader, settings, index)
        )
        for index in range(settings.worker_concurrency)
    ]
    tasks.append(asyncio.create_task(stuck_job_recovery_loop(queue, settings)))
    try:
        # return_exceptions=True: one task's unhandled exception must not
        # cancel every other still-healthy worker task via gather's default
        # fail-fast behavior.
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for task in tasks:
            task.cancel()
        await bot.session.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
