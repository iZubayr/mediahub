import asyncio
import logging

from aiogram import Bot

from .bot import create_dispatcher, setup_menu_button
from .config import Settings
from .db import create_pool
from .downloader import InstagramDownloader
from .limits import RateLimiter
from .logging_config import configure_logging
from .queue import DownloadQueue
from .worker import _supervised_worker, stuck_job_recovery_loop
from .worker_state import WorkerActivityTracker


logger = logging.getLogger(__name__)


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
    """Runs everything — bot polling, N worker tasks, and stuck-job
    recovery — in one process. This avoids needing a separate AlwaysData
    Site for the webhook: only one Service needs to be configured and kept
    alive, which is simpler to operate than a Site (which serves the
    webhook over HTTP and has its own uptime/idle behavior) plus a
    Service (the worker) as two independently-managed processes.

    Trade-off versus webhook mode: polling means Telegram updates arrive
    with a small delay (long-poll interval) instead of instantly pushed,
    and this one process handles both receiving messages and running
    downloads, so a very large burst of incoming messages could compete
    for CPU/event-loop time with active downloads. For a single bot with
    moderate traffic this is a reasonable trade for operational simplicity.

    Standalone mode also enables a queue-skipping fast path: when no
    worker is currently busy, an incoming request is processed immediately
    instead of going through the enqueue -> poll -> claim round-trip
    through Postgres, saving a bit of latency when there's no real
    contention to manage. See WorkerActivityTracker and bot.py's
    link_handler for details. This optimization only exists here — webhook
    mode always uses the queue, since the webhook process and worker
    Service can't see each other's in-memory state.
    """
    configure_logging()
    settings = Settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    pool = await create_pool(settings)
    queue = DownloadQueue(pool, settings)
    await queue.recover_stuck()
    limiter = RateLimiter(pool, settings)
    downloader = InstagramDownloader(settings)
    activity_tracker = WorkerActivityTracker()

    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = create_dispatcher(settings, pool, activity_tracker, downloader)
    await setup_menu_button(bot, settings)

    worker_tasks = [
        asyncio.create_task(
            _supervised_worker(
                bot, pool, queue, limiter, downloader, settings, index, activity_tracker
            )
        )
        for index in range(settings.worker_concurrency)
    ]
    recovery_task = asyncio.create_task(stuck_job_recovery_loop(queue, settings))
    cleanup_task = asyncio.create_task(rate_limit_cleanup_loop(limiter))
    polling_task = asyncio.create_task(dispatcher.start_polling(bot))

    all_tasks = worker_tasks + [recovery_task, cleanup_task, polling_task]
    try:
        # return_exceptions=True: if polling or a worker task raises, it
        # must not silently cancel every other still-healthy task via
        # gather's default fail-fast behavior — we want the rest of the bot
        # to keep working even if one part has an unexpected problem.
        await asyncio.gather(*all_tasks, return_exceptions=True)
    finally:
        for task in all_tasks:
            task.cancel()
        await bot.session.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
