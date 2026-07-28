import time

from redis.asyncio import Redis

from .config import Settings


CLAIM_JOB_SLOT_SCRIPT = """
local current = redis.call('SISMEMBER', KEYS[1], ARGV[1])
if current == 1 then
    return 1
end
local count = redis.call('SCARD', KEYS[1])
if count >= tonumber(ARGV[2]) then
    return 0
end
redis.call('SADD', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""


class RateLimiter:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings

    async def allow_request(self, user_id: int) -> bool:
        bucket = int(time.time() // 60)
        key = f"mediahub:rate:{user_id}:{bucket}"
        value = await self.redis.incr(key)
        if value == 1:
            await self.redis.expire(key, 120)
        return value <= self.settings.requests_per_minute

    async def allow_daily_download(self, user_id: int) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        key = f"mediahub:daily:{user_id}:{day}"
        value = await self.redis.incr(key)
        if value == 1:
            await self.redis.expire(key, 172800)
        if value <= self.settings.daily_download_limit:
            return True
        await self.redis.decr(key)
        return False

    async def acquire_job_slot(self, user_id: int, job_id: str) -> bool:
        key = f"mediahub:active:{user_id}"
        result = await self.redis.eval(
            CLAIM_JOB_SLOT_SCRIPT,
            1,
            key,
            job_id,
            self.settings.max_active_jobs_per_user,
            3600,
        )
        return bool(result)

    async def release_job_slot(self, user_id: int, job_id: str) -> None:
        key = f"mediahub:active:{user_id}"
        await self.redis.srem(key, job_id)

