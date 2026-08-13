import pytest
from yt_dlp.utils import DownloadError

from app.downloader import InstagramDownloader
from app.errors import InvalidInstagramUrl
from app.validation import extract_url, extract_urls, validate_instagram_url


def test_extract_url_from_text() -> None:
    text = "Mana havola: https://www.instagram.com/reel/ABC123/?igsh=abc"
    assert extract_url(text) == "https://www.instagram.com/reel/ABC123/?igsh=abc"


def test_extract_urls_returns_single_url_as_list() -> None:
    text = "Mana havola: https://www.instagram.com/reel/ABC123/"
    assert extract_urls(text) == ["https://www.instagram.com/reel/ABC123/"]


def test_extract_urls_finds_multiple_links_in_order() -> None:
    text = (
        "https://www.instagram.com/reel/AAA111/ "
        "and also https://www.instagram.com/p/BBB222/ "
        "https://www.instagram.com/reel/CCC333/"
    )
    assert extract_urls(text) == [
        "https://www.instagram.com/reel/AAA111/",
        "https://www.instagram.com/p/BBB222/",
        "https://www.instagram.com/reel/CCC333/",
    ]


def test_extract_urls_deduplicates_repeated_links() -> None:
    text = (
        "https://www.instagram.com/reel/AAA111/ "
        "https://www.instagram.com/reel/AAA111/"
    )
    assert extract_urls(text) == ["https://www.instagram.com/reel/AAA111/"]


def test_extract_urls_returns_empty_list_when_no_urls() -> None:
    assert extract_urls("no links here") == []


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


def test_story_url_is_allowed_only_when_explicitly_authorized() -> None:
    url = "https://www.instagram.com/stories/someone/123456/"

    assert validate_instagram_url(url, allow_stories=True) == url


def test_login_required_error_is_user_friendly() -> None:
    # Stories are rejected before reaching the downloader (see validation.py),
    # so this now covers the remaining login-wall case: private posts.
    error = InstagramDownloader._map_download_error(
        DownloadError("[instagram] You need to log in to access this content")
    )
    assert "login" in str(error).lower()
