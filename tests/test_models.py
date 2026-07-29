from uuid import UUID

from app.models import DownloadJob


def test_download_job_create() -> None:
    job = DownloadJob.create(
        user_id=42,
        chat_id=42,
        status_message_id=10,
        source_url="https://www.instagram.com/reel/ABC123/",
    )
    assert isinstance(job.job_id, UUID)
    assert job.user_id == 42
    assert job.chat_id == 42
    assert job.status_message_id == 10
    assert job.source_url == "https://www.instagram.com/reel/ABC123/"
    assert job.created_at
