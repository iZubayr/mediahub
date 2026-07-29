from dataclasses import dataclass

import asyncpg


@dataclass(slots=True)
class ForceSubChannel:
    channel_id: int
    chat_ref: str
    title: str | None
    invite_link: str | None
    added_by: int


def normalize_chat_ref(raw: str) -> str | None:
    """Accepts @username, t.me/username links, or numeric chat ids
    (private channels are always negative, e.g. -1001234567890) and returns
    a normalized reference suitable for Bot.get_chat_member, or None if the
    input doesn't look like any of those."""
    value = raw.strip()
    if not value:
        return None

    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if value.lower().startswith(prefix):
            value = "@" + value[len(prefix):].lstrip("/")
            break

    if value.startswith("@"):
        username = value[1:]
        if username and all(ch.isalnum() or ch == "_" for ch in username):
            return "@" + username
        return None

    if value.lstrip("-").isdigit():
        return value

    return None


async def list_channels(pool: asyncpg.Pool) -> list[ForceSubChannel]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM mediahub_force_sub_channels ORDER BY added_at"
        )
    return [
        ForceSubChannel(
            channel_id=row["channel_id"],
            chat_ref=row["chat_ref"],
            title=row["title"],
            invite_link=row["invite_link"],
            added_by=row["added_by"],
        )
        for row in rows
    ]


async def add_channel(
    pool: asyncpg.Pool,
    chat_ref: str,
    title: str | None,
    invite_link: str | None,
    added_by: int,
) -> ForceSubChannel | None:
    """Returns None if this chat_ref is already in the list (unique constraint)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mediahub_force_sub_channels (chat_ref, title, invite_link, added_by)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (chat_ref) DO NOTHING
            RETURNING *
            """,
            chat_ref,
            title,
            invite_link,
            added_by,
        )
    if row is None:
        return None
    return ForceSubChannel(
        channel_id=row["channel_id"],
        chat_ref=row["chat_ref"],
        title=row["title"],
        invite_link=row["invite_link"],
        added_by=row["added_by"],
    )


async def remove_channel(pool: asyncpg.Pool, chat_ref: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM mediahub_force_sub_channels WHERE chat_ref = $1",
            chat_ref,
        )
    return result.split()[-1] != "0"


async def remove_channel_by_index(pool: asyncpg.Pool, index: int) -> ForceSubChannel | None:
    """1-based index into the list as shown by /channels, for convenience
    so the admin can type '/removechannel 2' instead of the exact ref."""
    channels = await list_channels(pool)
    if index < 1 or index > len(channels):
        return None
    target = channels[index - 1]
    removed = await remove_channel(pool, target.chat_ref)
    return target if removed else None
