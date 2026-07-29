import time
from datetime import datetime, timezone
from uuid import UUID

import asyncpg

from .config import Settings


class RateLimiter:
    """Postgres-backed replacement for the original Redis rate limiter.

    Uses UPSERT (INSERT ... ON CONFLICT) instead of Redis INCR/EXPIRE, and a
    plain row-count check instead of the Lua SISMEMBER/SADD script. Old
    minute/day buckets are cleaned up opportunistically on each call so the
    tables don't grow forever.
    """

    def __init__(self, pool: asyncpg.Pool, settings: Settings) -> None:
        self.pool = pool
        self.settings = settings

    async def allow_request(self, user_id: int) -> bool:
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
            # Best-effort cleanup of old buckets (older than 5 minutes).
            await conn.execute(
                "DELETE FROM mediahub_rate_minute WHERE bucket < $1",
                bucket - 5,
            )
        return value <= self.settings.requests_per_minute

    async def allow_daily_download(self, user_id: int) -> bool:
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
                if value <= self.settings.daily_download_limit:
                    return True
                await conn.execute(
                    "UPDATE mediahub_rate_daily SET count = count - 1 "
                    "WHERE user_id = $1 AND day = $2",
                    user_id,
                    day,
                )
        return False

    async def acquire_job_slot(self, user_id: int, job_id: UUID) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                count = await conn.fetchval(
                    "SELECT count(*) FROM mediahub_active_jobs WHERE user_id = $1 FOR UPDATE",
                    user_id,
                )
                if count >= self.settings.max_active_jobs_per_user:
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
