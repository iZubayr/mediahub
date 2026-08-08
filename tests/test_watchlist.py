from unittest.mock import AsyncMock, MagicMock

import pytest

from app.watchlist import (
    add_watched_user,
    is_watched,
    record_download_if_watched,
    remove_watched_user,
    search_users,
)


def _fake_pool_with_fetch(rows: list[dict]):
    pool = MagicMock()
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    class FakeAcquire:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    pool.acquire = lambda: FakeAcquire()
    return pool, conn


@pytest.mark.asyncio
async def test_search_by_numeric_id_uses_exact_match_query() -> None:
    pool, conn = _fake_pool_with_fetch(
        [{"user_id": 123, "username": "zubayr", "first_name": "Zubayr", "is_watched": False}]
    )

    results = await search_users(pool, "123")

    assert len(results) == 1
    assert results[0].user_id == 123
    query = conn.fetch.call_args.args[0]
    assert "u.user_id = $1" in query


@pytest.mark.asyncio
async def test_search_by_username_uses_ilike() -> None:
    pool, conn = _fake_pool_with_fetch(
        [{"user_id": 123, "username": "zubayr", "first_name": "Zubayr", "is_watched": True}]
    )

    results = await search_users(pool, "@zubayr")

    assert len(results) == 1
    assert results[0].is_watched is True
    query = conn.fetch.call_args.args[0]
    assert "ILIKE" in query
    # The leading @ should be stripped before building the search pattern.
    pattern_arg = conn.fetch.call_args.args[1]
    assert pattern_arg == "%zubayr%"


@pytest.mark.asyncio
async def test_add_watched_user_returns_false_when_already_present() -> None:
    pool, conn = _fake_pool_with_fetch([])
    conn.execute = AsyncMock(return_value="INSERT 0 0")  # ON CONFLICT DO NOTHING, no row inserted

    result = await add_watched_user(pool, user_id=123, added_by=555)

    assert result is False


@pytest.mark.asyncio
async def test_add_watched_user_returns_true_when_newly_added() -> None:
    pool, conn = _fake_pool_with_fetch([])
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    result = await add_watched_user(pool, user_id=123, added_by=555)

    assert result is True


@pytest.mark.asyncio
async def test_remove_watched_user_returns_true_when_removed() -> None:
    pool, conn = _fake_pool_with_fetch([])
    conn.execute = AsyncMock(return_value="DELETE 1")

    result = await remove_watched_user(pool, user_id=123)

    assert result is True


@pytest.mark.asyncio
async def test_is_watched_true_when_row_exists() -> None:
    pool, conn = _fake_pool_with_fetch([])
    conn.fetchval = AsyncMock(return_value=1)

    assert await is_watched(pool, user_id=123) is True


@pytest.mark.asyncio
async def test_is_watched_false_when_no_row() -> None:
    pool, conn = _fake_pool_with_fetch([])
    conn.fetchval = AsyncMock(return_value=None)

    assert await is_watched(pool, user_id=123) is False


@pytest.mark.asyncio
async def test_record_download_if_watched_uses_conditional_insert() -> None:
    """The whole point of this function is a single round-trip that only
    writes for watched users -- confirm the query has the EXISTS guard
    rather than doing a separate is_watched() check first."""
    pool, conn = _fake_pool_with_fetch([])

    await record_download_if_watched(
        pool, user_id=123, source_url="https://instagram.com/p/x/", media_type="video",
        item_count=1, status="completed",
    )

    conn.execute.assert_awaited_once()
    query = conn.execute.call_args.args[0]
    assert "WHERE EXISTS" in query
    assert "mediahub_watched_users" in query
