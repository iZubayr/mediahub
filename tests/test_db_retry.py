from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from app.db import acquire_with_retry


def _fake_pool_with_acquire_sequence(side_effects: list):
    """Builds a fake asyncpg.Pool whose .acquire() context manager yields a
    connection on success, or raises the given exception on failure, one
    item from side_effects per call."""
    pool = MagicMock()
    call_count = {"n": 0}

    @asynccontextmanager
    async def fake_acquire():
        index = call_count["n"]
        call_count["n"] += 1
        effect = side_effects[index]
        if isinstance(effect, Exception):
            raise effect
        yield effect

    pool.acquire = fake_acquire
    return pool, call_count


@pytest.mark.asyncio
async def test_succeeds_immediately_when_connection_is_healthy() -> None:
    fake_conn = MagicMock()
    pool, call_count = _fake_pool_with_acquire_sequence([fake_conn])

    async with acquire_with_retry(pool) as conn:
        assert conn is fake_conn

    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_retries_once_after_transient_connection_error(monkeypatch) -> None:
    fake_conn = MagicMock()
    pool, call_count = _fake_pool_with_acquire_sequence(
        [asyncpg.InterfaceError("connection closed"), fake_conn]
    )

    from app import db as db_module

    monkeypatch.setattr(db_module.asyncio, "sleep", AsyncMock())

    async with acquire_with_retry(pool, attempts=2) as conn:
        assert conn is fake_conn

    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_reraises_after_exhausting_attempts(monkeypatch) -> None:
    pool, call_count = _fake_pool_with_acquire_sequence(
        [
            asyncpg.InterfaceError("connection closed"),
            asyncpg.InterfaceError("still closed"),
        ]
    )

    from app import db as db_module

    monkeypatch.setattr(db_module.asyncio, "sleep", AsyncMock())

    with pytest.raises(asyncpg.InterfaceError):
        async with acquire_with_retry(pool, attempts=2):
            pass

    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_non_transient_error_is_not_retried() -> None:
    """A real query/logic error (not a connection problem) should propagate
    immediately rather than being silently retried."""
    pool, call_count = _fake_pool_with_acquire_sequence(
        [ValueError("not a connection error")]
    )

    with pytest.raises(ValueError):
        async with acquire_with_retry(pool, attempts=2):
            pass

    assert call_count["n"] == 1
