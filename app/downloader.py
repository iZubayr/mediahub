import asyncio
from dataclasses import dataclass, field
from html import unescape
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin

import aiofiles
import httpx
import instaloader
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .config import Settings
from .errors import (
    MediaNotFound,
    MediaTooLarge,
    PrivateMedia,
    UnsupportedMedia,
)


logger = logging.getLogger(__name__)
VIDEO_EXTENSIONS = {"mp4", "m4v", "mov", "webm", "mkv", "avi"}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
SAFE_FILENAME = re.compile(r"[^a-zA-Z0-9._-]+")
META_TAG_PATTERN = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
META_PROPERTY_PATTERN = re.compile(
    r"(?:property|name)\s*=\s*([\"'])(.*?)\1",
    re.IGNORECASE | re.DOTALL,
)
META_CONTENT_PATTERN = re.compile(
    r"content\s*=\s*([\"'])(.*?)\1",
    re.IGNORECASE | re.DOTALL,
)

# yt-dlp signals "this post has no video stream" (i.e. it's an image or
# carousel post) with different message wording depending on version and
# code path. Both are observed in production logs. Any message matching one
# of these triggers the instaloader/Open Graph fallback chain instead of
# surfacing a raw yt-dlp error.
NO_VIDEO_ERROR_MARKERS = (
    "there is no video in this post",
    "no video formats found",
)


@dataclass(slots=True)
class MediaItem:
    url: str
    filename: str
    media_type: str
    size: int | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ResolveResult:
    items: list[MediaItem]
    partial: bool = False
    """True when only a single image could be recovered for a URL pattern
    that supports multiple images (carousel), meaning some images may be
    missing. False for reels/videos/single-image posts, where one item is
    the complete, expected result."""


class InstagramDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def resolve(self, source_url: str) -> ResolveResult:
        try:
            info, partial = await asyncio.to_thread(self._extract_info, source_url)
        except DownloadError as exc:
            raise self._map_download_error(exc) from exc

        entries = info.get("entries") if isinstance(info, dict) else None
        if entries:
            raw_entries = [entry for entry in entries if entry]
        else:
            raw_entries = [info]

        items: list[MediaItem] = []
        for index, entry in enumerate(raw_entries, start=1):
            item = self._to_media_item(entry, index=index)
            if item.size is not None and item.size > self.settings.max_media_size_bytes:
                raise MediaTooLarge("Media fayl belgilangan hajm limitidan katta.")
            items.append(item)

        if not items:
            raise MediaNotFound("Media topilmadi.")
        return ResolveResult(items=items, partial=partial and len(items) == 1)

    def _extract_info(self, source_url: str) -> tuple[dict[str, Any], bool]:
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": False,
            "format": "best[ext=mp4]/best",
            # Deliberately NOT setting a custom User-Agent here. yt-dlp's
            # Instagram extractor stopped hardcoding one in 2024 (see
            # yt-dlp/yt-dlp@079a7bc) and now relies on yt-dlp's own
            # `random_user_agent`, which is updated with every release to
            # track current browser versions. Overriding it with a fixed
            # string here (as this code previously did) means every request
            # carries an increasingly dated, easily-fingerprinted
            # User-Agent — worse for evading Instagram's growing anti-bot
            # measures than trusting yt-dlp's own current default.
            # Skip fetching comments — we never display them, and it's an
            # extra Instagram API round-trip per post that only adds
            # latency without benefit.
            "getcomments": False,
            # THE key option for carousels: yt-dlp raises "No video formats
            # found!" for any post/slide with no video stream (i.e. an
            # image), via YoutubeDL.raise_no_formats(), which checks
            # exactly this parameter:
            #   ignored = self.params.get('ignore_no_formats_error')
            # This is a DIFFERENT option from `ignoreerrors` (which only
            # affects the later download stage, not format-selection during
            # extraction — a subtlety that caused an earlier, incomplete
            # attempt at this same fix to not actually help). With this set,
            # an image slide's info dict is preserved (as a warning, not a
            # raised error) with an empty 'formats' list but its
            # 'thumbnails' populated, which we recover into a usable image
            # URL below. See yt-dlp/yt-dlp#7569 (upstream, marked wontfix)
            # for confirmation this is a known, common Instagram carousel
            # issue with no better upstream fix available.
            "ignore_no_formats_error": True,
        }
        # Deliberately no cookie/login support: authenticating as a real
        # Instagram account to scrape on behalf of arbitrary bot users risks
        # that account being flagged and banned by Instagram, and the bot is
        # scoped to public content only (see validation.py, which rejects
        # story URLs outright since those need a logged-in session — no
        # login-free method exists for stories; every working open-source
        # implementation found requires either a login session or cookies).

        with YoutubeDL(options) as ydl:
            try:
                info = ydl.extract_info(source_url, download=False)
            except DownloadError as exc:
                message = str(exc).lower()
                # With ignore_no_formats_error=True, a single-image post
                # (no playlist at all) still raises here in some yt-dlp
                # versions since there's no other entry to fall back to.
                # The instaloader/Open Graph fallbacks cover that case.
                # Login walls, rate limits, and deleted posts should still
                # surface as their real error rather than silently retrying
                # with something that would just fail again confusingly.
                if any(marker in message for marker in NO_VIDEO_ERROR_MARKERS):
                    logger.info("no_video_detected trying_instaloader url=%s", source_url)
                    try:
                        result = self._extract_via_instaloader(source_url)
                        entry_count = len(result.get("entries", [result]))
                        logger.info(
                            "instaloader_succeeded url=%s entries=%s", source_url, entry_count
                        )
                        return result, False
                    except UnsupportedMedia:
                        pass
                    logger.warning(
                        "instaloader_failed_trying_open_graph url=%s "
                        "(carousel posts will only recover 1 image via this path)",
                        source_url,
                    )
                    try:
                        return self._extract_open_graph(source_url), True
                    except UnsupportedMedia:
                        pass
                    logger.error("all_fallbacks_exhausted url=%s", source_url)
                raise
        if not isinstance(info, dict):
            raise MediaNotFound("Media ma’lumotlari topilmadi.")

        # With ignore_no_formats_error=True, a carousel slide that yt-dlp
        # couldn't find a video format for comes back as an entry with no
        # 'formats' but (for image slides) a populated 'thumbnails' list —
        # recover those as images instead of dropping the slide entirely.
        entries = info.get("entries")
        if entries:
            recovered = 0
            for entry in entries:
                if entry and not entry.get("formats") and not entry.get("url"):
                    thumbnails = entry.get("thumbnails") or []
                    if thumbnails:
                        # yt-dlp orders thumbnails smallest-to-largest for
                        # this extractor (see _extract_product_media's
                        # `reversed(...)` call); the last one is highest-res.
                        entry["url"] = thumbnails[-1]["url"]
                        entry["ext"] = "jpg"
                        entry["vcodec"] = "none"
                        recovered += 1
            if recovered:
                logger.info(
                    "carousel_images_recovered_from_thumbnails url=%s count=%s",
                    source_url,
                    recovered,
                )

        return info, False

    def _extract_via_instaloader(self, source_url: str) -> dict[str, Any]:
        """Recovers ALL images/videos of a carousel (sidecar) post by
        reading Instagram's GraphQL post data directly, the same data the
        official web client uses to render the swipeable carousel. Works
        without login for public posts. This is what makes multi-image
        carousels work at all — yt-dlp only looks for a video stream, and
        the plain-HTML og:image fallback can only ever see the first slide.
        """
        shortcode = self._extract_shortcode(source_url)
        if shortcode is None:
            raise UnsupportedMedia("Post havolasidan shortcode aniqlanmadi.")

        loader = instaloader.Instaloader(
            quiet=True,
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            max_connection_attempts=1,
        )
        try:
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
        except Exception as exc:
            # instaloader raises several different exception types for
            # "not found", "login required", "rate limited" etc. — all of
            # them just mean "this path didn't work", so the caller falls
            # through to the next fallback rather than needing to know
            # instaloader's specific exception hierarchy. Logged at warning
            # level (not silently swallowed) so a systematic failure — e.g.
            # Instagram blocking this server's IP — is visible in production
            # logs instead of just quietly degrading to single-image results.
            logger.warning(
                "instaloader_extraction_failed shortcode=%s error=%s: %s",
                shortcode,
                type(exc).__name__,
                exc,
            )
            raise UnsupportedMedia("instaloader orqali post o‘qib bo‘lmadi.") from exc

        entries: list[dict[str, Any]] = []
        if post.typename == "GraphSidecar":
            for index, node in enumerate(post.get_sidecar_nodes(), start=1):
                media_url = node.video_url if node.is_video else node.display_url
                if not media_url:
                    continue
                entries.append(self._instaloader_entry(media_url, node.is_video, index))
        else:
            media_url = post.video_url if post.is_video else post.url
            if media_url:
                entries.append(self._instaloader_entry(media_url, post.is_video, 1))

        if not entries:
            raise UnsupportedMedia("instaloader orqali media topilmadi.")
        return entries[0] if len(entries) == 1 else {"entries": entries}

    def _instaloader_entry(self, media_url: str, is_video: bool, index: int) -> dict[str, Any]:
        return {
            "id": f"instaloader_{index}",
            "title": f"instagram_post_{index}",
            "url": media_url,
            "ext": "mp4" if is_video else "jpg",
            "vcodec": "h264" if is_video else "none",
            "http_headers": {"User-Agent": self._user_agent()},
        }

    @staticmethod
    def _extract_shortcode(source_url: str) -> str | None:
        match = re.search(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", source_url)
        return match.group(1) if match else None

    def _extract_open_graph(self, source_url: str) -> dict[str, Any]:
        """Best-effort fallback for single-image posts that yt-dlp's video
        extractor skips. Instagram's server-rendered HTML only exposes ONE
        og:image tag even for carousel posts (the rest are loaded by
        client-side JS), so this can only ever recover the first image of a
        carousel, never all of them. Callers should treat a returned entry
        count of 1 from this path as "possibly partial" for carousel URLs.
        """
        try:
            with httpx.Client(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                response = client.get(source_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UnsupportedMedia("Instagram post sahifasini ochib bo‘lmadi.") from exc

        values: dict[str, list[str]] = {}
        for tag in META_TAG_PATTERN.findall(response.text):
            property_match = META_PROPERTY_PATTERN.search(tag)
            content_match = META_CONTENT_PATTERN.search(tag)
            property_name = (property_match.group(2) if property_match else "").lower()
            content = content_match.group(2) if content_match else None
            if not content:
                continue
            if property_name in {
                "og:image",
                "og:image:url",
                "og:image:secure_url",
                "og:video",
                "og:video:secure_url",
                "twitter:image",
                "twitter:image:src",
                "twitter:player:stream",
            }:
                values.setdefault(property_name, []).append(unescape(content))

        media_urls: list[tuple[str, str]] = []
        for key in ("og:video", "og:video:secure_url", "twitter:player:stream"):
            media_urls.extend((url, "video") for url in values.get(key, []))
        for key in (
            "og:image",
            "og:image:url",
            "og:image:secure_url",
            "twitter:image",
            "twitter:image:src",
        ):
            media_urls.extend((url, "photo") for url in values.get(key, []))

        unique_media: list[tuple[str, str]] = []
        seen: set[str] = set()
        for media_url, media_type in media_urls:
            media_url = urljoin(source_url, media_url)
            if media_url and media_url not in seen:
                unique_media.append((media_url, media_type))
                seen.add(media_url)

        if not unique_media:
            raise UnsupportedMedia(
                "Post media’si ochiq ko‘rinmadi. Post public ekanini tekshiring."
            )

        entries = []
        for index, (media_url, media_type) in enumerate(unique_media, start=1):
            entries.append(
                {
                    "id": f"open_graph_{index}",
                    "title": f"instagram_post_{index}",
                    "url": media_url,
                    "ext": "mp4" if media_type == "video" else "jpg",
                    "vcodec": "h264" if media_type == "video" else "none",
                    "http_headers": {"User-Agent": self._user_agent()},
                }
            )
        return entries[0] if len(entries) == 1 else {"entries": entries}

    def _to_media_item(self, entry: dict[str, Any], *, index: int) -> MediaItem:
        media_url = entry.get("url")
        if not media_url:
            formats = [item for item in (entry.get("formats") or []) if item.get("url")]
            if formats:
                media_url = max(
                    formats,
                    key=lambda item: (
                        int(item.get("height") or 0),
                        float(item.get("tbr") or 0),
                    ),
                ).get("url")
        if not media_url:
            raise UnsupportedMedia("Media uchun to‘g‘ridan-to‘g‘ri URL topilmadi.")

        ext = (entry.get("ext") or self._extension_from_url(media_url) or "bin").lower()
        if ext == "jpeg":
            ext = "jpg"
        media_type = self._media_type(entry, ext)
        title = str(entry.get("title") or entry.get("id") or f"instagram_media_{index}")
        title = SAFE_FILENAME.sub("_", title).strip("._")[:80] or f"media_{index}"
        filename = f"{title}.{ext}"
        size = entry.get("filesize") or entry.get("filesize_approx")
        headers = {
            str(key): str(value)
            for key, value in (entry.get("http_headers") or {}).items()
            if key.lower() in {"user-agent", "referer", "cookie"}
        }
        headers.setdefault("User-Agent", self._user_agent())
        return MediaItem(
            url=str(media_url),
            filename=filename,
            media_type=media_type,
            size=int(size) if size else None,
            headers=headers,
        )

    @staticmethod
    def _media_type(entry: dict[str, Any], ext: str) -> str:
        if entry.get("vcodec") not in (None, "none") or ext in VIDEO_EXTENSIONS:
            return "video"
        if ext in IMAGE_EXTENSIONS or entry.get("acodec") in (None, "none"):
            return "photo"
        return "document"

    @staticmethod
    def _extension_from_url(url: str) -> str | None:
        path = url.split("?", 1)[0].rsplit("/", 1)[-1]
        if "." not in path:
            return None
        return path.rsplit(".", 1)[-1]

    async def download_to_temp(self, item: MediaItem, job_id: str, index: int) -> Path:
        target_dir = Path(self.settings.temp_dir) / job_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{index}_{item.filename}"
        for attempt in range(self.settings.retry_attempts + 1):
            try:
                return await self._download_to_temp_once(item, target)
            except MediaTooLarge:
                raise
            except (httpx.HTTPError, TimeoutError) as exc:
                target.unlink(missing_ok=True)
                if attempt >= self.settings.retry_attempts:
                    raise
                logger.warning(
                    "fallback_download_retry attempt=%s job_id=%s error=%s",
                    attempt + 1,
                    job_id,
                    type(exc).__name__,
                )
                await asyncio.sleep(2**attempt)
        raise RuntimeError("fallback download retry loop exited unexpectedly")

    async def _download_to_temp_once(self, item: MediaItem, target: Path) -> Path:
        timeout = httpx.Timeout(
            connect=20.0,
            read=float(self.settings.download_timeout_seconds),
            write=30.0,
            pool=30.0,
        )

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=item.headers,
        ) as client:
            async with client.stream("GET", item.url) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.settings.max_media_size_bytes:
                    raise MediaTooLarge("Media fayl belgilangan hajm limitidan katta.")

                received = 0
                async with aiofiles.open(target, "wb") as file:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                        received += len(chunk)
                        if received > self.settings.max_media_size_bytes:
                            raise MediaTooLarge("Media fayl belgilangan hajm limitidan katta.")
                        await file.write(chunk)
        return target

    async def cleanup(self, job_id: str) -> None:
        target_dir = Path(self.settings.temp_dir) / job_id
        if not target_dir.exists():
            return
        for path in target_dir.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)
        target_dir.rmdir()

    @staticmethod
    def _user_agent() -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        )

    @staticmethod
    def _map_download_error(exc: DownloadError) -> Exception:
        message = str(exc).lower()
        if any(word in message for word in ("you need to log in", "login required", "sign in")):
            return PrivateMedia("Bu kontentga kirish uchun Instagram login talab qilinmoqda.")
        if "private" in message:
            return PrivateMedia("Private kontentni yuklab bo‘lmaydi.")
        if any(
            word in message
            for word in ("not found", "does not exist", "unable to download webpage", "404")
        ):
            return MediaNotFound("Media topilmadi yoki o‘chirilgan.")
        if any(marker in message for marker in NO_VIDEO_ERROR_MARKERS):
            return UnsupportedMedia(
                "Bu postdagi media rasm yoki qo‘llab-quvvatlanmaydigan turda."
            )
        if any(word in message for word in ("rate-limit", "rate limit", "429", "too many requests")):
            return UnsupportedMedia(
                "Instagram vaqtincha ko‘p so‘rovlarni cheklamoqda. Birozdan keyin qayta urinib ko‘ring."
            )
        if any(word in message for word in ("timed out", "timeout", "connection")):
            return UnsupportedMedia(
                "Instagram’ga ulanishda muammo yuz berdi. Qayta urinib ko‘ring."
            )
        return UnsupportedMedia("Instagram media ma’lumotlarini olishning imkoni bo‘lmadi.")
