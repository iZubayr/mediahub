import asyncio
import logging

import asyncpg
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    CallbackQuery,
    KeyboardButton,
    Message,
    MenuButtonCommands,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from .admin import create_admin_router, is_admin
from .config import Settings
from .db import create_pool
from .downloader import InstagramDownloader
from .errors import QueueFull
from .force_sub import ForceSubscribeMiddleware
from .limits import RateLimiter
from .logging_config import configure_logging
from .models import DownloadJob
from .queue import DownloadQueue
from .runtime_settings import get_int
from .texts import get_text
from .ui_constants import ADMIN_PANEL_BUTTON_TEXT
from .users import upsert_user
from .validation import extract_urls, validate_instagram_url
from .worker_state import WorkerActivityTracker


logger = logging.getLogger(__name__)


USER_COMMANDS = [
    BotCommand(command="start", description="Botni boshlash"),
    BotCommand(command="help", description="Yordam"),
]

ADMIN_EXTRA_COMMANDS = [
    BotCommand(command="admin", description="🛠 Admin panel"),
]


def admin_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=ADMIN_PANEL_BUTTON_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
    )


async def setup_menu_button(bot: Bot, settings: Settings) -> None:
    """Configures the ☰ menu button next to the message input. For everyone,
    it shows the default command list (/start, /help). For each admin ID
    individually, it additionally lists /admin — so tapping ☰ then "Admin
    panel" opens the same inline-button panel /admin does, without typing
    anything, and without exposing that option to non-admin users (Telegram
    command scopes are per-chat, so a chat-specific command list is only
    ever visible to that one user).
    """
    await bot.set_my_commands(commands=USER_COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    for admin_id in settings.admin_id_set:
        try:
            await bot.set_my_commands(
                commands=USER_COMMANDS + ADMIN_EXTRA_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            # Most common cause: this admin has never started a chat with
            # the bot yet, so Telegram has no chat to scope commands to.
            # Not fatal — falls back to the default list until they do.
            logger.warning("menu_button_setup_failed_for_admin admin_id=%s", admin_id, exc_info=True)


def create_dispatcher(
    settings: Settings,
    pool: asyncpg.Pool,
    activity_tracker: WorkerActivityTracker | None = None,
    downloader: InstagramDownloader | None = None,
) -> Dispatcher:
    """`activity_tracker` and `downloader` are only passed in standalone
    mode (see app/standalone.py), where the bot and workers share one
    process and one event loop. When present, an incoming link is executed
    immediately in-process instead of going through the Postgres queue, but
    ONLY if no worker is currently busy — this avoids the enqueue -> poll
    -> claim round-trip's latency when there's no actual contention to
    manage, while still falling back to the normal queue under load so
    concurrent requests don't overwhelm the process.

    In webhook mode (both args None), everything always goes through the
    queue as before, since the webhook process and worker Service have no
    shared in-memory state to check.
    """
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
            await upsert_user(
                pool, message.from_user.id, message.from_user.username, message.from_user.first_name
            )
        return await handler(message, data)

    @router.callback_query(F.data == "force_sub_check")
    async def force_sub_recheck(callback: CallbackQuery) -> None:
        # If this handler runs at all, ForceSubscribeMiddleware already
        # confirmed membership for this callback (it would have blocked the
        # request otherwise), so we just confirm to the user.
        if callback.message is not None:
            text = await get_text(pool, "force_sub_confirmed")
            await callback.message.answer(text)
        await callback.answer()

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        text = await get_text(pool, "start")
        if message.from_user is not None and is_admin(settings, message.from_user.id):
            await message.answer(text, reply_markup=admin_reply_keyboard())
        else:
            await message.answer(text)

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        requests_per_minute, daily_download_limit = await asyncio.gather(
            get_int(pool, "requests_per_minute", settings),
            get_int(pool, "daily_download_limit", settings),
        )
        text = await get_text(
            pool,
            "help",
            requests_per_minute=requests_per_minute,
            daily_download_limit=daily_download_limit,
        )
        await message.answer(text)

    @router.message(F.text)
    async def link_handler(message: Message, bot: Bot) -> None:
        if message.from_user is None or message.text is None:
            return

        user_id = message.from_user.id
        source_urls = extract_urls(message.text)
        if not source_urls:
            await message.answer(await get_text(pool, "invalid_link"))
            return

        valid_urls: list[str] = []
        for raw_url in source_urls:
            try:
                # Stories need an Instagram session. Only the account owner
                # and admins may submit them; all other users keep receiving
                # the standard "Story not supported" validation message.
                valid_urls.append(
                    validate_instagram_url(
                        raw_url,
                        allow_stories=is_admin(settings, user_id),
                    )
                )
            except Exception as validation_error:
                # A message with several links where only some are valid
                # Instagram URLs still processes the valid ones; the
                # rejection message is shown once, keyed to whichever URL
                # failed first, so the user knows something was skipped
                # without a wall of repeated errors for a 10-link message.
                if len(source_urls) == 1:
                    await message.answer(
                        str(validation_error) or await get_text(pool, "invalid_instagram_url")
                    )
                    return

        if not valid_urls:
            await message.answer(await get_text(pool, "invalid_instagram_url"))
            return

        await asyncio.gather(
            *(
                _process_single_link(
                    message, bot, pool, queue, limiter, settings, activity_tracker, downloader, source_url
                )
                for source_url in valid_urls
            )
        )

    async def _process_single_link(
        message: Message,
        bot: Bot,
        pool: asyncpg.Pool,
        queue: DownloadQueue,
        limiter: RateLimiter,
        settings: Settings,
        activity_tracker: WorkerActivityTracker | None,
        downloader: InstagramDownloader | None,
        source_url: str,
    ) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id

        try:
            allowed_per_minute, allowed_per_day, queued_text = await asyncio.gather(
                limiter.allow_request(user_id),
                limiter.allow_daily_download(user_id),
                get_text(pool, "queued"),
            )
            if not allowed_per_minute:
                if allowed_per_day:
                    # The daily counter was incremented in parallel above,
                    # but this request is being rejected on the per-minute
                    # limit — undo that increment so a per-minute rejection
                    # never silently burns a daily download credit.
                    await limiter.release_daily_download(user_id)
                await message.answer(await get_text(pool, "rate_limited"))
                return
            if not allowed_per_day:
                await message.answer(await get_text(pool, "daily_limit_reached"))
                return
        except asyncpg.PostgresError:
            logger.exception("rate_limit_db_error user_id=%s", user_id)
            await message.answer(await get_text(pool, "server_busy"))
            return

        status_message = await message.answer(queued_text)
        job = DownloadJob.create(
            user_id=user_id,
            chat_id=message.chat.id,
            status_message_id=status_message.message_id,
            source_url=source_url,
        )

        try:
            has_slot = await limiter.acquire_job_slot(user_id, job.job_id)
            if not has_slot:
                await status_message.edit_text(await get_text(pool, "too_many_active"))
                return

            if activity_tracker is not None and downloader is not None and activity_tracker.is_idle:
                # Fast path: nothing else is running right now, so skip the
                # queue entirely and start processing immediately.
                from .worker import process_job  # local import: avoids a

                # bot.py <-> worker.py circular import at module load time
                async def _run_direct() -> None:
                    await activity_tracker.enter()
                    try:
                        await process_job(bot, pool, queue, limiter, downloader, settings, job)
                    finally:
                        await activity_tracker.exit()

                asyncio.ensure_future(_run_direct())
                return

            await queue.enqueue(job)
        except QueueFull:
            await limiter.release_job_slot(user_id, job.job_id)
            await status_message.edit_text(await get_text(pool, "queue_full"))
        except asyncpg.PostgresError:
            await limiter.release_job_slot(user_id, job.job_id)
            logger.exception("enqueue_db_error job_id=%s", job.job_id)
            await status_message.edit_text(await get_text(pool, "server_busy_enqueue"))
        except Exception:
            await limiter.release_job_slot(user_id, job.job_id)
            logger.exception("enqueue_error job_id=%s", job.job_id)
            await status_message.edit_text(await get_text(pool, "unexpected_error"))

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
    await setup_menu_button(bot, settings)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
