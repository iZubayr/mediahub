from unittest.mock import MagicMock, patch

import pytest

from app.downloader import InstagramDownloader
from app.errors import UnsupportedMedia


def _downloader() -> InstagramDownloader:
    settings = MagicMock()
    settings.max_media_size_bytes = 100 * 1024 * 1024
    return InstagramDownloader(settings)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.instagram.com/p/ABC123def/", "ABC123def"),
        ("https://instagram.com/reel/XYZ_789-x/", "XYZ_789-x"),
        ("https://www.instagram.com/reels/QWE456/", "QWE456"),
        ("https://www.instagram.com/tv/RTY000/", "RTY000"),
        ("https://www.instagram.com/username/", None),
        ("not-a-url", None),
    ],
)
def test_extract_shortcode(url: str, expected: str | None) -> None:
    assert InstagramDownloader._extract_shortcode(url) == expected


def test_instaloader_sidecar_recovers_all_carousel_images() -> None:
    downloader = _downloader()

    fake_node_1 = MagicMock(is_video=False, display_url="https://x/1.jpg", video_url=None)
    fake_node_2 = MagicMock(is_video=False, display_url="https://x/2.jpg", video_url=None)
    fake_node_3 = MagicMock(is_video=True, display_url=None, video_url="https://x/3.mp4")

    fake_post = MagicMock()
    fake_post.typename = "GraphSidecar"
    fake_post.get_sidecar_nodes.return_value = [fake_node_1, fake_node_2, fake_node_3]

    with patch("app.downloader.instaloader.Post.from_shortcode", return_value=fake_post):
        info = downloader._extract_via_instaloader("https://www.instagram.com/p/ABC123/")

    assert "entries" in info
    assert len(info["entries"]) == 3
    assert info["entries"][0]["url"] == "https://x/1.jpg"
    assert info["entries"][2]["vcodec"] == "h264"  # the video entry


def test_instaloader_single_image_post_returns_one_entry() -> None:
    downloader = _downloader()

    fake_post = MagicMock()
    fake_post.typename = "GraphImage"
    fake_post.is_video = False
    fake_post.url = "https://x/only.jpg"

    with patch("app.downloader.instaloader.Post.from_shortcode", return_value=fake_post):
        info = downloader._extract_via_instaloader("https://www.instagram.com/p/ABC123/")

    assert "entries" not in info
    assert info["url"] == "https://x/only.jpg"


def test_instaloader_failure_raises_unsupported_media_for_fallback_chain() -> None:
    downloader = _downloader()

    with patch(
        "app.downloader.instaloader.Post.from_shortcode",
        side_effect=RuntimeError("blocked"),
    ):
        with pytest.raises(UnsupportedMedia):
            downloader._extract_via_instaloader("https://www.instagram.com/p/ABC123/")


def test_instaloader_no_shortcode_raises_unsupported_media() -> None:
    downloader = _downloader()
    with pytest.raises(UnsupportedMedia):
        downloader._extract_via_instaloader("https://www.instagram.com/username/")
