import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

from .config import Settings


logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS mediahub_jobs (
    job_id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    status_message_id BIGINT NOT NULL,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_mediahub_jobs_status_created
    ON mediahub_jobs (status, created_at);

CREATE TABLE IF NOT EXISTS mediahub_active_jobs (
    user_id BIGINT NOT NULL,
    job_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, job_id)
);

CREATE TABLE IF NOT EXISTS mediahub_rate_minute (
    user_id BIGINT NOT NULL,
    bucket BIGINT NOT NULL,
    count INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, bucket)
);

CREATE TABLE IF NOT EXISTS mediahub_rate_daily (
    user_id BIGINT NOT NULL,
    day DATE NOT NULL,
    count INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS mediahub_users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_blocked BOOLEAN NOT NULL DEFAULT false
);

-- Added after first release: older deployments already have this table
-- without first_name, so add it if missing rather than assuming a fresh
-- CREATE TABLE always ran.
ALTER TABLE mediahub_users ADD COLUMN IF NOT EXISTS first_name TEXT;

CREATE TABLE IF NOT EXISTS mediahub_download_history (
    history_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    source_url TEXT NOT NULL,
    media_type TEXT,
    item_count INT NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mediahub_download_history_user_created
    ON mediahub_download_history (user_id, created_at DESC);

-- Only users an admin explicitly adds here have their downloads recorded
-- in mediahub_download_history. Keeps that table small and intentional
-- (a handful of watched users) instead of logging every download from
-- every user, which would grow unbounded on a free-tier database.
CREATE TABLE IF NOT EXISTS mediahub_watched_users (
    user_id BIGINT PRIMARY KEY,
    added_by BIGINT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mediahub_broadcasts (
    broadcast_id UUID PRIMARY KEY,
    admin_id BIGINT NOT NULL,
    text TEXT NOT NULL,
    total INT NOT NULL DEFAULT 0,
    sent INT NOT NULL DEFAULT 0,
    failed INT NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mediahub_force_sub_channels (
    channel_id BIGSERIAL PRIMARY KEY,
    chat_ref TEXT NOT NULL UNIQUE,
    title TEXT,
    invite_link TEXT,
    added_by BIGINT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mediahub_texts (
    text_key TEXT PRIMARY KEY,
    text_value TEXT NOT NULL,
    updated_by BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mediahub_runtime_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value INT NOT NULL,
    updated_by BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def create_pool(settings: Settings) -> asyncpg.Pool:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=max(settings.worker_concurrency + 2, 5),
        command_timeout=30,
        # Recycle connections that have sat idle for a while. Supabase's
        # pooler (and network paths in general) can silently drop
        # long-idle connections; without this, asyncpg only discovers a
        # dead connection when a query on it fails, which is exactly the
        # kind of "worked, then went quiet for hours, then errors on the
        # next request" symptom this guards against.
        max_inactive_connection_lifetime=300,
        # Supabase's pooler (pgbouncer) does not support prepared statements
        # in transaction/session pool mode; each pooled connection may be
        # handed to a different backend session between queries, so a
        # statement prepared on one backend can collide with or vanish from
        # another. Disabling asyncpg's statement cache avoids
        # DuplicatePreparedStatementError entirely. See:
        # https://magicstack.github.io/asyncpg/current/faq.html#why-am-i-getting-prepared-statement-errors
        statement_cache_size=0,
    )
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    logger.info("database_pool_ready")
    return pool


# Errors that mean "this specific connection is dead/stale", as opposed to
# a real query problem (bad SQL, constraint violation, etc). Retrying with a
# fresh connection from the pool is safe and usually succeeds immediately,
# since it's the pooler dropping an idle connection, not the database itself
# being down.
_TRANSIENT_CONNECTION_ERRORS = (
    asyncpg.ConnectionDoesNotExistError,
    asyncpg.InterfaceError,
    asyncpg.TooManyConnectionsError,
    ConnectionResetError,
    OSError,
)


@asynccontextmanager
async def acquire_with_retry(
    pool: asyncpg.Pool, attempts: int = 2, backoff_seconds: float = 0.5
) -> AsyncIterator[asyncpg.pool.PoolConnectionProxy]:
    """Like `pool.acquire()`, but transparently retries once if the pooled
    connection turns out to be stale (Supabase's Session pooler can drop an
    idle connection without asyncpg noticing until the next query runs on
    it). Use this in places doing a single, retry-safe read; for multi-step
    transactions, catching _TRANSIENT_CONNECTION_ERRORS around the whole
    `async with pool.acquire()` block at the call site is more appropriate,
    since a transaction can't be transparently resumed mid-way.
    """
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            async with pool.acquire() as conn:
                yield conn
                return
        except _TRANSIENT_CONNECTION_ERRORS as exc:
            last_error = exc
            logger.warning(
                "db_connection_retry attempt=%s/%s error=%s",
                attempt + 1,
                attempts,
                type(exc).__name__,
            )
            if attempt < attempts - 1:
                await asyncio.sleep(backoff_seconds)
    assert last_error is not None
    raise last_error
