import pytest
from yt_dlp.utils import DownloadError

from app.downloader import InstagramDownloader
from app.errors import InvalidInstagramUrl
from app.validation import extract_url, validate_instagram_url


def test_extract_url_from_text() -> None:
    text = "Mana havola: https://www.instagram.com/reel/ABC123/?igsh=abc"
    assert extract_url(text) == "https://www.instagram.com/reel/ABC123/?igsh=abc"


@pytest.mark.parametrize(
    "value",
    [
        "https://www.instagram.com/reel/ABC123/",
        "https://instagram.com/p/ABC123/",
    ],
)
def test_valid_instagram_media_urls(value: str) -> None:
    assert validate_instagram_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "https://instagram.com.evil.example/p/ABC123/",
        "https://example.com/reel/ABC123/",
        "https://www.instagram.com/username/",
        "https://www.instagram.com/stories/user/123/",
        "not-a-url",
    ],
)
def test_invalid_instagram_urls(value: str) -> None:
    with pytest.raises(InvalidInstagramUrl):
        validate_instagram_url(value)


def test_story_url_rejected_with_clear_message() -> None:
    with pytest.raises(InvalidInstagramUrl, match="Story"):
        validate_instagram_url("https://www.instagram.com/stories/someone/123456/")


def test_login_required_error_is_user_friendly() -> None:
    # Stories are rejected before reaching the downloader (see validation.py),
    # so this now covers the remaining login-wall case: private posts.
    error = InstagramDownloader._map_download_error(
        DownloadError("[instagram] You need to log in to access this content")
    )
    assert "login" in str(error).lower()
