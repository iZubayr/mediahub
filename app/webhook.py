import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from aiogram import Bot
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request

from .bot import create_dispatcher, setup_menu_button
from .config import Settings
from .db import create_pool
from .logging_config import configure_logging


logger = logging.getLogger(__name__)
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    if not settings.public_base_url.startswith("https://"):
        raise RuntimeError("PUBLIC_BASE_URL must start with https:// for Telegram webhook")
    if len(settings.telegram_webhook_secret) < 16:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET must contain at least 16 characters")

    pool = await create_pool(settings)
    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = create_dispatcher(settings, pool)
    await bot.set_webhook(
        url=settings.webhook_url,
        secret_token=settings.telegram_webhook_secret,
        allowed_updates=dispatcher.resolve_used_update_types(),
    )
    await setup_menu_button(bot, settings)
    app.state.bot = bot
    app.state.dispatcher = dispatcher
    app.state.pool = pool
    logger.info("webhook_configured url=%s", settings.webhook_url)
    try:
        yield
    finally:
        await bot.delete_webhook(drop_pending_updates=False)
        await bot.session.close()
        await pool.close()


app = FastAPI(title="MediaHub Webhook", version="0.3.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    async with app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok", "database": "ok", "mode": "webhook"}


@app.post(settings.webhook_path)
async def telegram_webhook(request: Request) -> dict[str, bool]:
    received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(
        hashlib.sha256(received_secret.encode()).digest(),
        hashlib.sha256(settings.telegram_webhook_secret.encode()).digest(),
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        update = Update.model_validate(
            await request.json(),
            context={"bot": app.state.bot},
        )
    except Exception as exc:
        logger.warning("invalid_telegram_update error=%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Invalid Telegram update") from exc

    await app.state.dispatcher.feed_update(app.state.bot, update)
    return {"ok": True}
