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
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")
    webhook_path: str = Field(default="/telegram/webhook", alias="WEBHOOK_PATH")
    telegram_webhook_secret: str = Field(default="", alias="TELEGRAM_WEBHOOK_SECRET")
    webhook_host: str = Field(default="0.0.0.0", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8080, alias="WEBHOOK_PORT")

    queue_name: str = Field(default="mediahub:downloads", alias="QUEUE_NAME")
    processing_queue_name: str = Field(
        default="mediahub:downloads:processing", alias="PROCESSING_QUEUE_NAME"
    )
    max_queue_size: int = Field(default=500, alias="MAX_QUEUE_SIZE")
    worker_concurrency: int = Field(default=4, alias="WORKER_CONCURRENCY")

    requests_per_minute: int = Field(default=10, alias="REQUESTS_PER_MINUTE")
    max_active_jobs_per_user: int = Field(default=2, alias="MAX_ACTIVE_JOBS_PER_USER")
    daily_download_limit: int = Field(default=100, alias="DAILY_DOWNLOAD_LIMIT")

    max_media_size_mb: int = Field(default=50, alias="MAX_MEDIA_SIZE_MB")
    download_timeout_seconds: int = Field(default=120, alias="DOWNLOAD_TIMEOUT_SECONDS")
    upload_timeout_seconds: int = Field(default=180, alias="UPLOAD_TIMEOUT_SECONDS")
    retry_attempts: int = Field(default=2, alias="RETRY_ATTEMPTS")
    temp_dir: str = Field(default="/tmp/mediahub", alias="TEMP_DIR")
    instagram_cookies_file: str = Field(default="", alias="INSTAGRAM_COOKIES_FILE")

    @property
    def max_media_size_bytes(self) -> int:
        return self.max_media_size_mb * 1024 * 1024

    @property
    def webhook_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/{self.webhook_path.lstrip('/')}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
