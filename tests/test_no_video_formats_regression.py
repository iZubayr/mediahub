from unittest.mock import MagicMock, patch

import pytest
from yt_dlp.utils import DownloadError

from app.downloader import InstagramDownloader


def _downloader() -> InstagramDownloader:
    settings = MagicMock()
    settings.max_media_size_bytes = 100 * 1024 * 1024
    return InstagramDownloader(settings)


def test_no_video_formats_found_triggers_fallback() -> None:
    """Regression test: this is the exact yt-dlp error message seen in
    production logs for a carousel post. It differs from "There is no
    video in this post" and must ALSO trigger the instaloader/Open Graph
    fallback chain instead of surfacing as a raw, unhelpful error."""
    downloader = _downloader()

    fake_node = MagicMock(is_video=False, display_url="https://x/1.jpg", video_url=None)
    fake_post = MagicMock()
    fake_post.typename = "GraphSidecar"
    fake_post.get_sidecar_nodes.return_value = [fake_node]

    def fake_extract_info(self, url, download=False):
        raise DownloadError(
            "ERROR: [Instagram] DbbMDJMMtW7: No video formats found!; "
            "please report this issue on https://github.com/yt-dlp/yt-dlp/issues"
        )

    with (
        patch("app.downloader.YoutubeDL.extract_info", fake_extract_info),
        patch("app.downloader.instaloader.Post.from_shortcode", return_value=fake_post),
    ):
        info, partial = downloader._extract_info("https://www.instagram.com/p/DbbMDJMMtW7/")

    assert partial is False
    assert "entries" not in info or len(info["entries"]) == 1
    assert info.get("url") == "https://x/1.jpg" or info["entries"][0]["url"] == "https://x/1.jpg"


def test_no_video_formats_found_maps_to_unsupported_media_when_all_fallbacks_fail() -> None:
    downloader = _downloader()

    error = DownloadError("ERROR: [Instagram] ABC123: No video formats found!")
    mapped = downloader._map_download_error(error)
    assert "rasm" in str(mapped) or "qo‘llab-quvvatlanmaydigan" in str(mapped)
