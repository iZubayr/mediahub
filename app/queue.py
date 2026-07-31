import logging

import asyncpg

from .config import Settings
from .errors import QueueFull
from .models import DownloadJob


logger = logging.getLogger(__name__)


class DownloadQueue:
    """Postgres-backed replacement for the original Redis list queue.

    Uses `SELECT ... FOR UPDATE SKIP LOCKED` so multiple worker processes can
    poll the same table concurrently without claiming the same job twice.
    This is the standard job-queue pattern for Postgres and needs no extra
    service beyond the Supabase database AlwaysData already has network
    access to.
    """

    def __init__(self, pool: asyncpg.Pool, settings: Settings) -> None:
        self.pool = pool
        self.settings = settings

    async def size(self) -> int:
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(
                "SELECT count(*) FROM mediahub_jobs WHERE status = 'queued'"
            )
        return int(value)

    async def enqueue(self, job: DownloadJob) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Postgres disallows FOR UPDATE combined with an aggregate
                # like count(*), so lock the matching rows and count them in
                # Python instead of in SQL.
                rows = await conn.fetch(
                    "SELECT 1 FROM mediahub_jobs WHERE status = 'queued' FOR UPDATE"
                )
                current_size = len(rows)
                if current_size >= self.settings.max_queue_size:
                    raise QueueFull("Download queue is full")
                await conn.execute(
                    """
                    INSERT INTO mediahub_jobs
                        (job_id, user_id, chat_id, status_message_id, source_url, status)
                    VALUES ($1, $2, $3, $4, $5, 'queued')
                    """,
                    job.job_id,
                    job.user_id,
                    job.chat_id,
                    job.status_message_id,
                    job.source_url,
                )
        logger.info("job_enqueued job_id=%s queue_size=%s", job.job_id, current_size + 1)

    async def claim(self) -> DownloadJob | None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT * FROM mediahub_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
                if row is None:
                    return None
                await conn.execute(
                    "UPDATE mediahub_jobs SET status = 'processing', claimed_at = now() "
                    "WHERE job_id = $1",
                    row["job_id"],
                )
        return DownloadJob.from_row(row)

    async def acknowledge(self, job: DownloadJob) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM mediahub_jobs WHERE job_id = $1", job.job_id
            )

    async def recover_stuck(self) -> int:
        """Requeue jobs that have been stuck in 'processing' too long, e.g.
        because the worker process was killed or restarted mid-job."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE mediahub_jobs
                SET status = 'queued', claimed_at = NULL
                WHERE status = 'processing'
                  AND claimed_at < now() - interval '{self.settings.stuck_job_timeout_seconds} seconds'
                """
            )
        count = int(result.split()[-1]) if result else 0
        if count:
            logger.warning("recovered_stuck_jobs count=%s", count)
        return count
