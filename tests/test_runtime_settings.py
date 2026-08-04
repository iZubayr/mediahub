from unittest.mock import MagicMock

import pytest

from app.runtime_settings import RATE_LIMIT_DEFS_BY_KEY, get_int


def _fake_pool_with_rows(rows: list[dict]) -> MagicMock:
    pool = MagicMock()
    conn = MagicMock()

    async def fetch(*args, **kwargs):
        return rows

    async def execute(*args, **kwargs):
        return "INSERT 0 1"

    conn.fetch = fetch
    conn.execute = execute

    class FakeAcquire:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    pool.acquire = lambda: FakeAcquire()
    return pool


@pytest.mark.asyncio
async def test_get_int_falls_back_to_settings_default_when_no_override() -> None:
    import app.runtime_settings as rs

    rs._cache = {}
    rs._cache_expires_at = 0.0

    pool = _fake_pool_with_rows([])  # no overrides saved
    settings = MagicMock()
    settings.requests_per_minute = 10

    value = await get_int(pool, "requests_per_minute", settings)
    assert value == 10


@pytest.mark.asyncio
async def test_get_int_returns_override_when_present() -> None:
    import app.runtime_settings as rs

    rs._cache = {}
    rs._cache_expires_at = 0.0

    pool = _fake_pool_with_rows(
        [{"setting_key": "requests_per_minute", "setting_value": 25}]
    )
    settings = MagicMock()
    settings.requests_per_minute = 10

    value = await get_int(pool, "requests_per_minute", settings)
    assert value == 25


def test_all_rate_limit_defs_have_valid_ranges() -> None:
    for limit_def in RATE_LIMIT_DEFS_BY_KEY.values():
        assert limit_def.min_value < limit_def.max_value
        assert limit_def.min_value >= 1


def test_rate_limit_keys_match_settings_field_names() -> None:
    """The whole runtime-override mechanism depends on
    getattr(settings, key) working -- a typo'd key here would silently
    always return 0 instead of the intended .env default."""
    from app.config import Settings

    for key in RATE_LIMIT_DEFS_BY_KEY:
        assert key in Settings.model_fields
