from fastapi import FastAPI
from redis.asyncio import Redis

from .config import Settings


app = FastAPI(title="MediaHub API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    settings = Settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.ping()
        return {"status": "ok", "redis": "ok"}
    finally:
        await redis.aclose()

