from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")

    # Supabase Postgres connection (replaces Redis on AlwaysData Free/Shared,
    # where compiling and running a standalone Redis service is not reliable
    # within the account's RAM limits). Use the "Session pooler" or "Transaction
    # pooler" connection string from Supabase Project Settings > Database.
    database_url: str = Field(default="", alias="DATABASE_URL")

    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")
    webhook_path: str = Field(default="/telegram/webhook", alias="WEBHOOK_PATH")
    telegram_webhook_secret: str = Field(default="", alias="TELEGRAM_WEBHOOK_SECRET")
    webhook_host: str = Field(default="0.0.0.0", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8080, alias="WEBHOOK_PORT")

    max_queue_size: int = Field(default=500, alias="MAX_QUEUE_SIZE")
    worker_concurrency: int = Field(default=4, alias="WORKER_CONCURRENCY")
    # How long a worker sleeps between polls when the queue is empty. Since
    # Postgres has no native BRPOPLPUSH-style blocking pop, workers poll on
    # an interval instead of blocking on Redis.
    poll_interval_seconds: float = Field(default=1.5, alias="POLL_INTERVAL_SECONDS")
    # If a job stays "processing" longer than this without completing
    # (worker crash, restart, etc.), it is treated as stuck and requeued.
    stuck_job_timeout_seconds: int = Field(default=600, alias="STUCK_JOB_TIMEOUT_SECONDS")

    requests_per_minute: int = Field(default=10, alias="REQUESTS_PER_MINUTE")
    max_active_jobs_per_user: int = Field(default=2, alias="MAX_ACTIVE_JOBS_PER_USER")
    daily_download_limit: int = Field(default=100, alias="DAILY_DOWNLOAD_LIMIT")

    max_media_size_mb: int = Field(default=50, alias="MAX_MEDIA_SIZE_MB")
    download_timeout_seconds: int = Field(default=120, alias="DOWNLOAD_TIMEOUT_SECONDS")
    upload_timeout_seconds: int = Field(default=180, alias="UPLOAD_TIMEOUT_SECONDS")
    retry_attempts: int = Field(default=2, alias="RETRY_ATTEMPTS")
    temp_dir: str = Field(default="/tmp/mediahub", alias="TEMP_DIR")

    # Optional Netscape-format cookies from a dedicated Instagram account.
    # This is only needed for posts that Instagram lets a logged-in account
    # view but deliberately hides from anonymous server requests.
    instagram_cookies_file: str = Field(default="", alias="INSTAGRAM_COOKIES_FILE")

    # Admin panel: comma-separated Telegram numeric user IDs, e.g. "111,222".
    # These are the only accounts allowed to use /admin, /broadcast, /stats,
    # and to add/remove force-subscribe channels.
    admin_ids: str = Field(default="", alias="ADMIN_IDS")

    @property
    def admin_id_set(self) -> set[int]:
        return {
            int(part.strip())
            for part in self.admin_ids.split(",")
            if part.strip().lstrip("-").isdigit()
        }

    @property
    def max_media_size_bytes(self) -> int:
        return self.max_media_size_mb * 1024 * 1024

    @property
    def webhook_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/{self.webhook_path.lstrip('/')}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
