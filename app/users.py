from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg


async def upsert_user(
    pool: asyncpg.Pool, user_id: int, username: str | None, first_name: str | None = None
) -> None:
    """Records that this user has interacted with the bot. Called from every
    incoming message so the broadcast list always reflects real users, with
    no separate "registration" step to forget."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mediahub_users (user_id, username, first_name, first_seen_at, last_seen_at)
            VALUES ($1, $2, $3, now(), now())
            ON CONFLICT (user_id)
            DO UPDATE SET username = $2, first_name = $3, last_seen_at = now()
            """,
            user_id,
            username,
            first_name,
        )


async def mark_blocked(pool: asyncpg.Pool, user_id: int, blocked: bool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE mediahub_users SET is_blocked = $2 WHERE user_id = $1",
            user_id,
            blocked,
        )


async def count_users(pool: asyncpg.Pool) -> dict[str, int]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE NOT is_blocked) AS active,
                count(*) FILTER (WHERE last_seen_at > now() - interval '1 day') AS today
            FROM mediahub_users
            """
        )
    return {"total": row["total"], "active": row["active"], "today": row["today"]}


async def iter_broadcast_targets(pool: asyncpg.Pool, batch_size: int = 200):
    """Yields user_ids in batches, oldest-registered first, skipping accounts
    already known to have blocked the bot. A generator (rather than loading
    everyone into one list) keeps memory bounded for large user counts."""
    last_id = 0
    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id FROM mediahub_users
                WHERE NOT is_blocked AND user_id > $1
                ORDER BY user_id
                LIMIT $2
                """,
                last_id,
                batch_size,
            )
        if not rows:
            return
        yield [row["user_id"] for row in rows]
        last_id = rows[-1]["user_id"]


async def create_broadcast(pool: asyncpg.Pool, admin_id: int, text: str, total: int) -> UUID:
    broadcast_id = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mediahub_broadcasts (broadcast_id, admin_id, text, total)
            VALUES ($1, $2, $3, $4)
            """,
            broadcast_id,
            admin_id,
            text,
            total,
        )
    return broadcast_id


async def finish_broadcast(pool: asyncpg.Pool, broadcast_id: UUID, sent: int, failed: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE mediahub_broadcasts
            SET sent = $2, failed = $3, finished_at = now()
            WHERE broadcast_id = $1
            """,
            broadcast_id,
            sent,
            failed,
        )
