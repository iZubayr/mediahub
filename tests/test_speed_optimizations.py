from unittest.mock import AsyncMock, MagicMock

import pytest

from app.limits import RateLimiter


def _fake_pool():
    pool = MagicMock()
    conn = MagicMock()

    class FakeAcquire:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    pool.acquire = lambda: FakeAcquire()
    return pool, conn


@pytest.mark.asyncio
async def test_release_daily_download_decrements_count() -> None:
    pool, conn = _fake_pool()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    settings = MagicMock()
    limiter = RateLimiter(pool, settings)

    await limiter.release_daily_download(user_id=123)

    conn.execute.assert_awaited_once()
    query = conn.execute.call_args.args[0]
    assert "count = count - 1" in query
    assert conn.execute.call_args.args[1] == 123


@pytest.mark.asyncio
async def test_allow_request_no_longer_runs_inline_cleanup() -> None:
    """Regression test for the speed optimization: allow_request() must not
    issue a DELETE cleanup query on its connection -- that cleanup was
    moved to a periodic background task (rate_limit_cleanup_loop) since it
    doesn't need to run on every single incoming message."""
    pool, conn = _fake_pool()
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[])  # runtime_settings cache refresh
    conn.execute = AsyncMock()
    settings = MagicMock()
    settings.requests_per_minute = 10

    limiter = RateLimiter(pool, settings)
    await limiter.allow_request(user_id=123)

    conn.fetchval.assert_awaited_once()
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_old_buckets_runs_delete() -> None:
    pool, conn = _fake_pool()
    conn.execute = AsyncMock(return_value="DELETE 5")
    settings = MagicMock()
    limiter = RateLimiter(pool, settings)

    await limiter.cleanup_old_buckets()

    conn.execute.assert_awaited_once()
    assert "DELETE FROM mediahub_rate_minute" in conn.execute.call_args.args[0]
