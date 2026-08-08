from dataclasses import dataclass

import asyncpg


@dataclass(slots=True)
class UserSearchResult:
    user_id: int
    username: str | None
    first_name: str | None
    is_watched: bool


@dataclass(slots=True)
class HistoryEntry:
    source_url: str
    media_type: str | None
    item_count: int
    status: str
    created_at: str


async def search_users(pool: asyncpg.Pool, query: str, limit: int = 10) -> list[UserSearchResult]:
    """Searches mediahub_users by numeric ID (exact match), @username, or
    name (partial, case-insensitive match). This searches ALL users who've
    ever messaged the bot -- the watch list itself (mediahub_watched_users)
    is separate and much smaller, since only users an admin explicitly adds
    there get their downloads recorded.
    """
    query = query.strip()
    async with pool.acquire() as conn:
        if query.lstrip("-").isdigit():
            rows = await conn.fetch(
                """
                SELECT u.user_id, u.username, u.first_name,
                       (w.user_id IS NOT NULL) AS is_watched
                FROM mediahub_users u
                LEFT JOIN mediahub_watched_users w ON w.user_id = u.user_id
                WHERE u.user_id = $1
                LIMIT $2
                """,
                int(query),
                limit,
            )
        else:
            pattern = f"%{query.lstrip('@')}%"
            rows = await conn.fetch(
                """
                SELECT u.user_id, u.username, u.first_name,
                       (w.user_id IS NOT NULL) AS is_watched
                FROM mediahub_users u
                LEFT JOIN mediahub_watched_users w ON w.user_id = u.user_id
                WHERE u.username ILIKE $1 OR u.first_name ILIKE $1
                ORDER BY u.last_seen_at DESC
                LIMIT $2
                """,
                pattern,
                limit,
            )
    return [
        UserSearchResult(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            is_watched=row["is_watched"],
        )
        for row in rows
    ]


async def add_watched_user(pool: asyncpg.Pool, user_id: int, added_by: int) -> bool:
    """Returns False if the user was already on the watch list."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            INSERT INTO mediahub_watched_users (user_id, added_by)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id,
            added_by,
        )
    return result.split()[-1] != "0"


async def remove_watched_user(pool: asyncpg.Pool, user_id: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM mediahub_watched_users WHERE user_id = $1", user_id
        )
    return result.split()[-1] != "0"


async def list_watched_users(pool: asyncpg.Pool) -> list[UserSearchResult]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.user_id, u.username, u.first_name
            FROM mediahub_watched_users w
            JOIN mediahub_users u ON u.user_id = w.user_id
            ORDER BY w.added_at DESC
            """
        )
    return [
        UserSearchResult(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            is_watched=True,
        )
        for row in rows
    ]


async def is_watched(pool: asyncpg.Pool, user_id: int) -> bool:
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT 1 FROM mediahub_watched_users WHERE user_id = $1", user_id
        )
    return value is not None


async def record_download(
    pool: asyncpg.Pool,
    user_id: int,
    source_url: str,
    media_type: str | None,
    item_count: int,
    status: str,
) -> None:
    """Records one history entry. Callers should check is_watched() first
    (or better, use record_download_if_watched below) to avoid an
    unnecessary write for the common case of an unwatched user."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mediahub_download_history
                (user_id, source_url, media_type, item_count, status)
            VALUES ($1, $2, $3, $4, $5)
            """,
            user_id,
            source_url,
            media_type,
            item_count,
            status,
        )


async def record_download_if_watched(
    pool: asyncpg.Pool,
    user_id: int,
    source_url: str,
    media_type: str | None,
    item_count: int,
    status: str,
) -> None:
    """Single round-trip version: only inserts if the user is on the watch
    list, checked and written in one query so the common case (not
    watched) doesn't cost two round-trips."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mediahub_download_history
                (user_id, source_url, media_type, item_count, status)
            SELECT $1, $2, $3, $4, $5
            WHERE EXISTS (SELECT 1 FROM mediahub_watched_users WHERE user_id = $1)
            """,
            user_id,
            source_url,
            media_type,
            item_count,
            status,
        )


async def get_history(pool: asyncpg.Pool, user_id: int, limit: int = 20) -> list[HistoryEntry]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT source_url, media_type, item_count, status, created_at
            FROM mediahub_download_history
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    return [
        HistoryEntry(
            source_url=row["source_url"],
            media_type=row["media_type"],
            item_count=row["item_count"],
            status=row["status"],
            created_at=row["created_at"].isoformat(),
        )
        for row in rows
    ]
