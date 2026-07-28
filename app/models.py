from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any


@dataclass(slots=True)
class DownloadJob:
    job_id: str
    user_id: int
    chat_id: int
    status_message_id: int
    source_url: str
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        user_id: int,
        chat_id: int,
        status_message_id: int,
        source_url: str,
    ) -> "DownloadJob":
        return cls(
            job_id=job_id,
            user_id=user_id,
            chat_id=chat_id,
            status_message_id=status_message_id,
            source_url=source_url,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "DownloadJob":
        data: dict[str, Any] = json.loads(value)
        return cls(**data)

