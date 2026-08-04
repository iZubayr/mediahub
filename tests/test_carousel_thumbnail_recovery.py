from unittest.mock import MagicMock, patch

import pytest

from app.downloader import InstagramDownloader


def _downloader() -> InstagramDownloader:
    settings = MagicMock()
    settings.max_media_size_bytes = 100 * 1024 * 1024
    return InstagramDownloader(settings)


@pytest.mark.asyncio
async def test_carousel_image_slide_recovered_from_thumbnails() -> None:
    """Core regression test: a carousel with 2 video slides and 1 image
    slide must return all 3 items -- the image slide should be recovered
    from its 'thumbnails' data (which yt-dlp's Instagram extractor already
    populates for every slide) rather than being dropped because it has no
    'formats' entry."""
    downloader = _downloader()

    fake_info = {
        "entries": [
            {"id": "vid1", "url": "https://x/video1.mp4", "ext": "mp4", "vcodec": "h264"},
            {
                "id": "img1",
                "formats": [],
                "thumbnails": [
                    {"url": "https://x/small.jpg", "width": 150},
                    {"url": "https://x/large.jpg", "width": 1080},
                ],
            },
            {"id": "vid2", "url": "https://x/video2.mp4", "ext": "mp4", "vcodec": "h264"},
        ]
    }

    with patch("app.downloader.YoutubeDL.extract_info", lambda self, url, download=False: fake_info):
        result = await downloader.resolve("https://www.instagram.com/p/ABC123/")

    assert result.partial is False
    assert len(result.items) == 3
    # The image slide should now have a usable url pulled from the
    # highest-resolution thumbnail.
    assert result.items[1].url == "https://x/large.jpg"
    assert result.items[1].media_type == "photo"


@pytest.mark.asyncio
async def test_carousel_with_all_video_slides_untouched() -> None:
    downloader = _downloader()

    fake_info = {
        "entries": [
            {"id": "vid1", "url": "https://x/video1.mp4", "ext": "mp4", "vcodec": "h264"},
            {"id": "vid2", "url": "https://x/video2.mp4", "ext": "mp4", "vcodec": "h264"},
        ]
    }

    with patch("app.downloader.YoutubeDL.extract_info", lambda self, url, download=False: fake_info):
        result = await downloader.resolve("https://www.instagram.com/p/ABC123/")

    assert result.items[0].url == "https://x/video1.mp4"
    assert result.items[1].url == "https://x/video2.mp4"


@pytest.mark.asyncio
async def test_single_image_post_recovered_from_thumbnails() -> None:
    """Regression test for the exact production bug: a plain (non-carousel)
    image post whose info dict has no 'entries' key at all must ALSO be
    recovered from its thumbnails, not just carousel slides. Previously,
    thumbnail recovery only ran inside the `if entries:` branch, so a
    single-post info dict with empty formats fell straight through to
    UnsupportedMedia("Media uchun to'g'ridan-to'g'ri URL topilmadi.")."""
    downloader = _downloader()

    fake_info = {
        "id": "img1",
        "formats": [],
        "thumbnails": [
            {"url": "https://x/small.jpg", "width": 150},
            {"url": "https://x/large.jpg", "width": 1080},
        ],
    }

    with patch("app.downloader.YoutubeDL.extract_info", lambda self, url, download=False: fake_info):
        result = await downloader.resolve("https://www.instagram.com/p/ABC123/")

    assert len(result.items) == 1
    assert result.items[0].url == "https://x/large.jpg"
    assert result.items[0].media_type == "photo"


@pytest.mark.asyncio
async def test_single_video_post_untouched() -> None:
    downloader = _downloader()

    fake_info = {"id": "vid1", "url": "https://x/video1.mp4", "ext": "mp4", "vcodec": "h264"}

    with patch("app.downloader.YoutubeDL.extract_info", lambda self, url, download=False: fake_info):
        result = await downloader.resolve("https://www.instagram.com/p/ABC123/")

    assert len(result.items) == 1
    assert result.items[0].url == "https://x/video1.mp4"
    assert result.items[0].media_type == "video"


@pytest.mark.asyncio
async def test_image_entry_without_thumbnails_raises_unsupported_media() -> None:
    """If an entry truly has no formats AND no thumbnails, resolve() must
    raise a clear error rather than crashing with a KeyError somewhere
    downstream."""
    from app.errors import UnsupportedMedia

    downloader = _downloader()

    fake_info = {"id": "broken", "formats": [], "thumbnails": []}

    with patch("app.downloader.YoutubeDL.extract_info", lambda self, url, download=False: fake_info):
        with pytest.raises(UnsupportedMedia):
            await downloader.resolve("https://www.instagram.com/p/ABC123/")


def test_ignore_no_formats_error_option_is_set() -> None:
    """Confirms the CORRECT yt-dlp option is passed to YoutubeDL. This is
    the actual mechanism raise_no_formats() checks -- an earlier, incorrect
    fix attempt set `ignoreerrors="only_download"` instead, which controls
    a completely different stage (the download step, not format-selection
    during extraction) and did not actually prevent the "No video formats
    found!" error from aborting extraction."""
    downloader = _downloader()
    captured_options = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured_options.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"id": "x", "url": "https://x/1.mp4"}

    with patch("app.downloader.YoutubeDL", FakeYoutubeDL):
        downloader._extract_info("https://www.instagram.com/p/ABC123/")

    assert captured_options.get("ignore_no_formats_error") is True


def test_no_hardcoded_user_agent_in_extraction_options() -> None:
    """Regression test: extraction options must NOT set a fixed
    'http_headers' User-Agent. yt-dlp's Instagram extractor manages its own
    (regularly updated) User-Agent internally since 2024; overriding it
    with a stale hardcoded string makes every request more fingerprintable
    to Instagram's anti-bot systems."""
    downloader = _downloader()
    captured_options = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured_options.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"id": "x", "url": "https://x/1.mp4"}

    with patch("app.downloader.YoutubeDL", FakeYoutubeDL):
        downloader._extract_info("https://www.instagram.com/p/ABC123/")

    assert "http_headers" not in captured_options
