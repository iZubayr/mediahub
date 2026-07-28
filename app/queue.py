import logging

from redis.asyncio import Redis

from .config import Settings
from .errors import QueueFull
from .models import DownloadJob


logger = logging.getLogger(__name__)


class DownloadQueue:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings
        self.queue_name = settings.queue_name
        self.processing_queue_name = settings.processing_queue_name

    async def size(self) -> int:
        return int(await self.redis.llen(self.queue_name))

    async def enqueue(self, job: DownloadJob) -> None:
        current_size = await self.size()
        if current_size >= self.settings.max_queue_size:
            raise QueueFull("Download queue is full")
        await self.redis.rpush(self.queue_name, job.to_json())
        logger.info("job_enqueued job_id=%s queue_size=%s", job.job_id, current_size + 1)

    async def claim(self, timeout: int = 5) -> DownloadJob | None:
        # Moving the item to a processing list lets us recover unfinished jobs
        # after a worker restart instead of silently losing them.
        value = await self.redis.brpoplpush(
            self.queue_name,
            self.processing_queue_name,
            timeout=timeout,
        )
        if value is None:
            return None
        return DownloadJob.from_json(value)

    async def acknowledge(self, job: DownloadJob) -> None:
        await self.redis.lrem(self.processing_queue_name, 1, job.to_json())

    async def recover_processing(self) -> int:
        values = await self.redis.lrange(self.processing_queue_name, 0, -1)
        if not values:
            return 0

        await self.redis.delete(self.processing_queue_name)
        for value in reversed(values):
            await self.redis.lpush(self.queue_name, value)
        logger.warning("recovered_jobs count=%s", len(values))
        return len(values)

