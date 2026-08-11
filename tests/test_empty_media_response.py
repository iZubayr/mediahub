from unittest.mock import MagicMock, patch

from yt_dlp.utils import DownloadError

from app.downloader import InstagramDownloader


def _downloader() -> InstagramDownloader:
    settings = MagicMock()
    settings.max_media_size_bytes = 100 * 1024 * 1024
    return InstagramDownloader(settings)


def test_empty_media_response_retries_and_succeeds() -> None:
    """Regression test for the exact production bug: yt-dlp's first attempt
    raises "Instagram sent an empty media response", but a retry a few
    seconds later succeeds (this has been observed to be intermittent).
    The retry must be attempted before falling through to instaloader."""
    downloader = _downloader()

    call_count = {"n": 0}

    def fake_extract_info(self, url, download=False):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise DownloadError(
                "ERROR: [Instagram] DbyKmUPoLA0: Instagram sent an empty media response. "
                "Check if this post is accessible in your browser without being logged-in."
            )
        return {"id": "x", "url": "https://x/video.mp4", "ext": "mp4", "vcodec": "h264"}

    with (
        patch("app.downloader.YoutubeDL.extract_info", fake_extract_info),
        patch("app.downloader.time.sleep"),  # skip the real 3s delay in tests
    ):
        info, partial = downloader._extract_info("https://www.instagram.com/reel/DbyKmUPoLA0/")

    assert call_count["n"] == 2
    assert info["url"] == "https://x/video.mp4"
    assert partial is False


def test_empty_media_response_falls_through_to_instaloader_when_retry_fails() -> None:
    """If the retry ALSO fails, the fallback chain (instaloader, then Open
    Graph) must still be tried, exactly as it is for the "no video
    formats" error."""
    downloader = _downloader()

    def always_fails(self, url, download=False):
        raise DownloadError(
            "ERROR: [Instagram] ABC123: Instagram sent an empty media response."
        )

    fake_post = MagicMock()
    fake_post.typename = "GraphImage"
    fake_post.is_video = False
    fake_post.url = "https://x/recovered.jpg"

    with (
        patch("app.downloader.YoutubeDL.extract_info", always_fails),
        patch("app.downloader.time.sleep"),
        patch("app.downloader.instaloader.Post.from_shortcode", return_value=fake_post),
    ):
        info, partial = downloader._extract_info("https://www.instagram.com/p/ABC123/")

    assert info["url"] == "https://x/recovered.jpg"


def test_empty_media_response_maps_to_actionable_error_when_all_fallbacks_fail() -> None:
    downloader = _downloader()
    error = DownloadError("ERROR: [Instagram] ABC123: Instagram sent an empty media response.")
    mapped = downloader._map_download_error(error)
    message = str(mapped)
    assert "vaqtincha" in message or "qayta urinib" in message
