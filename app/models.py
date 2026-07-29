from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg


@dataclass(slots=True)
class DownloadJob:
    job_id: UUID
    user_id: int
    chat_id: int
    status_message_id: int
    source_url: str
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        user_id: int,
        chat_id: int,
        status_message_id: int,
        source_url: str,
    ) -> "DownloadJob":
        return cls(
            job_id=uuid4(),
            user_id=user_id,
            chat_id=chat_id,
            status_message_id=status_message_id,
            source_url=source_url,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    def from_row(cls, row: asyncpg.Record) -> "DownloadJob":
        return cls(
            job_id=row["job_id"],
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            status_message_id=row["status_message_id"],
            source_url=row["source_url"],
            created_at=row["created_at"].isoformat(),
        )
