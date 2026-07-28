from app.models import DownloadJob


def test_download_job_round_trip() -> None:
    job = DownloadJob.create(
        job_id="job-1",
        user_id=42,
        chat_id=42,
        status_message_id=10,
        source_url="https://www.instagram.com/reel/ABC123/",
    )
    restored = DownloadJob.from_json(job.to_json())
    assert restored == job

