import logging

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
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_blocked BOOLEAN NOT NULL DEFAULT false
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
"""


async def create_pool(settings: Settings) -> asyncpg.Pool:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=max(settings.worker_concurrency + 2, 5),
        command_timeout=30,
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
