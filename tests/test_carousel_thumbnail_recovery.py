from unittest.mock import MagicMock, patch

from app.downloader import InstagramDownloader


def _downloader() -> InstagramDownloader:
    settings = MagicMock()
    settings.max_media_size_bytes = 100 * 1024 * 1024
    return InstagramDownloader(settings)


def test_carousel_image_slide_recovered_from_thumbnails() -> None:
    """Core regression test: a carousel with 2 video slides and 1 image
    slide must return all 3 items — the image slide should be recovered
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

    def fake_extract_info(self, url, download=False):
        return fake_info

    with patch("app.downloader.YoutubeDL.extract_info", fake_extract_info):
        info, partial = downloader._extract_info("https://www.instagram.com/p/ABC123/")

    assert partial is False
    entries = info["entries"]
    assert len(entries) == 3
    # The image slide should now have a usable url pulled from the
    # highest-resolution thumbnail.
    assert entries[1]["url"] == "https://x/large.jpg"
    assert entries[1]["vcodec"] == "none"


def test_carousel_with_all_video_slides_untouched() -> None:
    downloader = _downloader()

    fake_info = {
        "entries": [
            {"id": "vid1", "url": "https://x/video1.mp4", "ext": "mp4", "vcodec": "h264"},
            {"id": "vid2", "url": "https://x/video2.mp4", "ext": "mp4", "vcodec": "h264"},
        ]
    }

    with patch("app.downloader.YoutubeDL.extract_info", lambda self, url, download=False: fake_info):
        info, partial = downloader._extract_info("https://www.instagram.com/p/ABC123/")

    assert info["entries"][0]["url"] == "https://x/video1.mp4"
    assert info["entries"][1]["url"] == "https://x/video2.mp4"


def test_image_entry_without_thumbnails_is_left_unrecovered() -> None:
    """If an entry truly has no formats AND no thumbnails, it's left as-is
    (resolve() downstream will skip/error on it) rather than crashing here."""
    downloader = _downloader()

    fake_info = {
        "entries": [
            {"id": "broken", "formats": [], "thumbnails": []},
        ]
    }

    with patch("app.downloader.YoutubeDL.extract_info", lambda self, url, download=False: fake_info):
        info, partial = downloader._extract_info("https://www.instagram.com/p/ABC123/")

    assert "url" not in info["entries"][0]


def test_ignoreerrors_option_is_set_to_only_download() -> None:
    """Confirms the ignoreerrors option is actually passed to YoutubeDL —
    without it, one bad slide aborts the whole carousel extraction."""
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

    assert captured_options.get("ignoreerrors") == "only_download"
