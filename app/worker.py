import asyncio
import logging
from html import escape
from pathlib import Path

import asyncpg
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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
from .runtime_settings import get_bool
from .texts import get_text
from .watchlist import record_download_if_watched
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


def notify_status_text(bot: Bot, job: DownloadJob, pool: asyncpg.Pool, key: str, **format_args) -> None:
    """Fire-and-forget status update where even the text lookup (get_text,
    a cache or DB read) happens inside the background task instead of being
    awaited before scheduling it. The earlier version awaited get_text()
    inline and only made the Telegram edit itself non-blocking, which still
    left a small but real delay on the critical path for every status
    update, multiplied by however many items are in a carousel.
    """

    async def _run() -> None:
        text = await get_text(pool, key, **format_args)
        await update_status(bot, job, text)

    asyncio.ensure_future(_run())


async def send_items(
    bot: Bot,
    pool: asyncpg.Pool,
    downloader: InstagramDownloader,
    settings: Settings,
    job: DownloadJob,
    items: list[MediaItem],
    total: int,
) -> None:
    """Sends every item in `items`, with up to 2 uploads in flight at once.
    Telegram upload requests are the single biggest remaining cost in the
    total pipeline (network-bound, not CPU-bound), so overlapping a couple
    of them meaningfully cuts total time for multi-image carousels versus
    sending strictly one-at-a-time, without saturating Telegram's per-chat
    rate limits the way full parallelism across a large carousel could.
    """
    caption_base = await build_caption(pool, job.source_url)
    semaphore = asyncio.Semaphore(2)

    async def _send_with_limit(index: int, item: MediaItem) -> None:
        async with semaphore:
            notify_status_text(bot, job, pool, "uploading", index=index, total=total)
            await send_item(bot, downloader, settings, job, item, index, total, caption_base)

    await asyncio.gather(
        *(_send_with_limit(index, item) for index, item in enumerate(items, start=1))
    )


async def build_caption(pool: asyncpg.Pool, source_url: str) -> str:
    """Builds the caption. When the "caption link" toggle is on (default):
    1. A hidden link — the editable "link text" wrapped in <a href> pointing
       at the original Instagram post/reel URL. Tapping it opens the
       original post; Telegram does not render a link preview for links
       inside a photo/video caption (only in plain text messages), so
       there's nothing further to configure there.
    2. The plain editable caption text on the line below.
    When the toggle is off, only the plain caption text is sent (no link
    line at all) — useful if the link isn't needed for a while without
    having to clear the link-text field itself.
    Requires HTML parse mode to be set on the Bot instance sending this
    (see standalone.py/webhook.py/worker.py's Bot(default=...) setup) —
    otherwise Telegram would show the raw <a href=...> markup as text.
    """
    link_enabled, link_text, caption_text = await asyncio.gather(
        get_bool(pool, "caption_link_enabled", True),
        get_text(pool, "media_caption_link_text"),
        get_text(pool, "media_caption"),
    )
    escaped_caption = escape(caption_text)
    if not link_enabled:
        return escaped_caption
    escaped_url = escape(source_url, quote=True)
    escaped_link_text = escape(link_text)
    return f'<a href="{escaped_url}">{escaped_link_text}</a>\n{escaped_caption}'


async def send_item(
    bot: Bot,
    downloader: InstagramDownloader,
    settings: Settings,
    job: DownloadJob,
    item: MediaItem,
    index: int,
    total: int,
    caption_base: str,
) -> None:
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
    status = "completed"
    media_type: str | None = None
    item_count = 0
    try:
        notify_status_text(bot, job, pool, "checking")
        result = await downloader.resolve(job.source_url)
        items = result.items
        total = len(items)
        item_count = total
        media_type = items[0].media_type if items else None

        await send_items(bot, pool, downloader, settings, job, items, total)

        if result.partial:
            await update_status(bot, job, await get_text(pool, "partial_carousel"))
            status = "partial"
        else:
            await update_status(bot, job, await get_text(pool, "done"))
        logger.info("job_completed job_id=%s items=%s partial=%s", job.job_id, total, result.partial)
    except Exception as error:
        status = "failed"
        logger.exception("job_failed job_id=%s", job.job_id)
        message = await user_error_message(pool, error)
        await update_status(bot, job, f"❌ {message}")
    finally:
        # These steps are independent of each other (a rate-limit slot
        # release, temp-file cleanup, marking the job done in Postgres, and
        # a watch-list history write) — running them concurrently instead
        # of one after another shaves a bit more off the tail of every job.
        # record_download_if_watched is a single query that only writes if
        # the user is on the watch list, so it's essentially free for the
        # common case of an unwatched user.
        await asyncio.gather(
            limiter.release_job_slot(job.user_id, job.job_id),
            downloader.cleanup(str(job.job_id)),
            queue.acknowledge(job),
            record_download_if_watched(
                pool, job.user_id, job.source_url, media_type, item_count, status
            ),
        )


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


async def rate_limit_cleanup_loop(limiter: RateLimiter) -> None:
    """Periodically deletes old rate-minute buckets, replacing the inline
    per-request cleanup that used to run on every single allow_request()
    call (an extra DB round-trip on every incoming message for a cleanup
    that only needs to happen occasionally)."""
    while True:
        await asyncio.sleep(120)
        try:
            await limiter.cleanup_old_buckets()
        except Exception:
            logger.exception("rate_limit_cleanup_failed")


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
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    tasks = [
        asyncio.create_task(
            _supervised_worker(bot, pool, queue, limiter, downloader, settings, index)
        )
        for index in range(settings.worker_concurrency)
    ]
    tasks.append(asyncio.create_task(stuck_job_recovery_loop(queue, settings)))
    tasks.append(asyncio.create_task(rate_limit_cleanup_loop(limiter)))
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
