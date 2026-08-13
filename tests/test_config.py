import os

from app.config import Settings


def _base_env() -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "PUBLIC_BASE_URL": "https://example.com",
        "TELEGRAM_WEBHOOK_SECRET": "0123456789abcdef",
    }


def test_admin_id_set_parses_comma_separated_ids(monkeypatch) -> None:
    for key, value in _base_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ADMIN_IDS", "111, 222,333")
    settings = Settings()
    assert settings.admin_id_set == {111, 222, 333}


def test_admin_id_set_empty_by_default(monkeypatch) -> None:
    for key, value in _base_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    settings = Settings()
    assert settings.admin_id_set == set()


def test_instagram_cookies_file_reads_from_environment(monkeypatch) -> None:
    for key, value in _base_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("INSTAGRAM_COOKIES_FILE", "/srv/secrets/instagram-cookies.txt")

    settings = Settings()

    assert settings.instagram_cookies_file == "/srv/secrets/instagram-cookies.txt"
