from fastapi import FastAPI

from .config import Settings
from .db import create_pool


app = FastAPI(title="MediaHub API", version="0.2.0")


@app.get("/health")
async def health() -> dict[str, str]:
    settings = Settings()
    pool = await create_pool(settings)
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "database": "ok"}
    finally:
        await pool.close()
