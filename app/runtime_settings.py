import time
from dataclasses import dataclass

import asyncpg

from .config import Settings


@dataclass(slots=True)
class RateLimitDef:
    key: str
    label: str
    help: str
    min_value: int
    max_value: int


# Every admin-tunable rate limit lives here. `key` matches the corresponding
# Settings field name so get_int() can fall back to it as the default.
RATE_LIMIT_DEFS: list[RateLimitDef] = [
    RateLimitDef(
        key="requests_per_minute",
        label="Daqiqalik so‘rov limiti",
        help="Bir foydalanuvchi bir daqiqada nechta so‘rov yubora oladi.",
        min_value=1,
        max_value=1000,
    ),
    RateLimitDef(
        key="max_active_jobs_per_user",
        label="Faol yuklashlar limiti",
        help="Bir foydalanuvchida bir vaqtda nechta yuklash faol bo‘lishi mumkin.",
        min_value=1,
        max_value=50,
    ),
    RateLimitDef(
        key="daily_download_limit",
        label="Kunlik yuklash limiti",
        help="Bir foydalanuvchi bir kunda nechta media yuklay oladi.",
        min_value=1,
        max_value=10000,
    ),
    RateLimitDef(
        key="max_queue_size",
        label="Navbat hajmi limiti",
        help="Navbatda bir vaqtda nechta ish kutishi mumkin (undan ko‘pi rad etiladi).",
        min_value=1,
        max_value=100000,
    ),
]

RATE_LIMIT_DEFS_BY_KEY: dict[str, RateLimitDef] = {item.key: item for item in RATE_LIMIT_DEFS}

_CACHE_TTL_SECONDS = 60
_cache: dict[str, int] = {}
_cache_expires_at: float = 0.0


async def _refresh_cache(pool: asyncpg.Pool) -> None:
    global _cache, _cache_expires_at
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT setting_key, setting_value FROM mediahub_runtime_settings")
    _cache = {row["setting_key"]: row["setting_value"] for row in rows}
    _cache_expires_at = time.monotonic() + _CACHE_TTL_SECONDS


async def get_int(pool: asyncpg.Pool, key: str, settings: Settings) -> int:
    """Returns the admin-customized value for `key` if one was saved,
    otherwise the .env default from Settings. Unknown keys fall back to 0
    rather than raising, since a rate limit read must never crash a
    download request over a typo'd key."""
    if time.monotonic() >= _cache_expires_at:
        await _refresh_cache(pool)
    if key in _cache:
        return _cache[key]
    return getattr(settings, key, 0)


async def set_int(pool: asyncpg.Pool, key: str, value: int, updated_by: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mediahub_runtime_settings (setting_key, setting_value, updated_by, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (setting_key)
            DO UPDATE SET setting_value = $2, updated_by = $3, updated_at = now()
            """,
            key,
            value,
            updated_by,
        )
    global _cache_expires_at
    _cache_expires_at = 0.0  # force refresh on next read


async def reset_int(pool: asyncpg.Pool, key: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM mediahub_runtime_settings WHERE setting_key = $1", key)
    global _cache_expires_at
    _cache_expires_at = 0.0


async def get_customized_keys(pool: asyncpg.Pool) -> set[str]:
    if time.monotonic() >= _cache_expires_at:
        await _refresh_cache(pool)
    return set(_cache.keys())


async def get_bool(pool: asyncpg.Pool, key: str, default: bool) -> bool:
    """Boolean settings reuse the same integer-valued table (stored as 0/1)
    rather than adding a separate schema for a single flag."""
    if time.monotonic() >= _cache_expires_at:
        await _refresh_cache(pool)
    if key in _cache:
        return bool(_cache[key])
    return default


async def set_bool(pool: asyncpg.Pool, key: str, value: bool, updated_by: int) -> None:
    await set_int(pool, key, 1 if value else 0, updated_by)
