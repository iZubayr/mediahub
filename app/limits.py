import time
from datetime import datetime, timezone
from uuid import UUID

import asyncpg

from .config import Settings
from .runtime_settings import get_int


class RateLimiter:
    """Postgres-backed replacement for the original Redis rate limiter.

    Uses UPSERT (INSERT ... ON CONFLICT) instead of Redis INCR/EXPIRE, and a
    plain row-count check instead of the Lua SISMEMBER/SADD script. Old
    minute/day buckets are cleaned up opportunistically on each call so the
    tables don't grow forever.

    Limit VALUES are read via runtime_settings.get_int(), which returns an
    admin-customized override if one was saved via the admin panel,
    otherwise the .env default — so admins can tune limits live without a
    redeploy.
    """

    def __init__(self, pool: asyncpg.Pool, settings: Settings) -> None:
        self.pool = pool
        self.settings = settings

    async def allow_request(self, user_id: int) -> bool:
        limit = await get_int(self.pool, "requests_per_minute", self.settings)
        bucket = int(time.time() // 60)
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(
                """
                INSERT INTO mediahub_rate_minute (user_id, bucket, count)
                VALUES ($1, $2, 1)
                ON CONFLICT (user_id, bucket)
                DO UPDATE SET count = mediahub_rate_minute.count + 1
                RETURNING count
                """,
                user_id,
                bucket,
            )
        return value <= limit

    async def cleanup_old_buckets(self) -> None:
        """Deletes rate-minute buckets older than 5 minutes. This used to
        run inline on every allow_request() call, adding an extra DB
        round-trip to every single incoming message for a cleanup that only
        needs to happen occasionally. Call this periodically (e.g. from a
        background loop) instead."""
        bucket = int(time.time() // 60)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM mediahub_rate_minute WHERE bucket < $1",
                bucket - 5,
            )

    async def allow_daily_download(self, user_id: int) -> bool:
        limit = await get_int(self.pool, "daily_download_limit", self.settings)
        day = datetime.now(timezone.utc).date()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                value = await conn.fetchval(
                    """
                    INSERT INTO mediahub_rate_daily (user_id, day, count)
                    VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, day)
                    DO UPDATE SET count = mediahub_rate_daily.count + 1
                    RETURNING count
                    """,
                    user_id,
                    day,
                )
                if value <= limit:
                    return True
                await conn.execute(
                    "UPDATE mediahub_rate_daily SET count = count - 1 "
                    "WHERE user_id = $1 AND day = $2",
                    user_id,
                    day,
                )
        return False

    async def release_daily_download(self, user_id: int) -> None:
        """Rolls back one daily-download increment. Used when
        allow_daily_download() succeeded but the request is being rejected
        for an unrelated reason (e.g. the per-minute limit, checked in
        parallel) — so a rejected request never silently consumes a daily
        download credit."""
        day = datetime.now(timezone.utc).date()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE mediahub_rate_daily SET count = count - 1 "
                "WHERE user_id = $1 AND day = $2",
                user_id,
                day,
            )

    async def acquire_job_slot(self, user_id: int, job_id: UUID) -> bool:
        limit = await get_int(self.pool, "max_active_jobs_per_user", self.settings)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Postgres disallows FOR UPDATE combined with an aggregate
                # like count(*), so lock the matching rows and count them in
                # Python instead of in SQL.
                rows = await conn.fetch(
                    "SELECT 1 FROM mediahub_active_jobs WHERE user_id = $1 FOR UPDATE",
                    user_id,
                )
                if len(rows) >= limit:
                    return False
                await conn.execute(
                    "INSERT INTO mediahub_active_jobs (user_id, job_id) VALUES ($1, $2) "
                    "ON CONFLICT DO NOTHING",
                    user_id,
                    job_id,
                )
        return True

    async def release_job_slot(self, user_id: int, job_id: UUID) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM mediahub_active_jobs WHERE user_id = $1 AND job_id = $2",
                user_id,
                job_id,
            )
