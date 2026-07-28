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
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .config import Settings
from .errors import (
    AuthenticationRequired,
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


@dataclass(slots=True)
class MediaItem:
    url: str
    filename: str
    media_type: str
    size: int | None = None
    headers: dict[str, str] = field(default_factory=dict)


class InstagramDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def resolve(self, source_url: str) -> list[MediaItem]:
        try:
            info = await asyncio.to_thread(self._extract_info, source_url)
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
        return items

    def _extract_info(self, source_url: str) -> dict[str, Any]:
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": False,
            "format": "best[ext=mp4]/best",
            "http_headers": {"User-Agent": self._user_agent()},
        }
        if self.settings.instagram_cookies_file:
            cookie_file = Path(self.settings.instagram_cookies_file)
            if cookie_file.is_file():
                options["cookiefile"] = str(cookie_file)

        with YoutubeDL(options) as ydl:
            try:
                info = ydl.extract_info(source_url, download=False)
            except DownloadError as exc:
                # yt-dlp's Instagram extractor treats image-only posts as
                # "no video". Public pages still expose an og:image tag,
                # which is a useful streamable fallback for single-image posts.
                if "there is no video in this post" in str(exc).lower():
                    return self._extract_open_graph(source_url)
                raise
        if not isinstance(info, dict):
            raise MediaNotFound("Media ma’lumotlari topilmadi.")
        return info

    def _extract_open_graph(self, source_url: str) -> dict[str, Any]:
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
            if "story" in message:
                return AuthenticationRequired(
                    "Story olish uchun Instagram login cookie kerak. Public story ham login talab qilishi mumkin."
                )
            return PrivateMedia("Bu kontentga kirish uchun Instagram login talab qilinmoqda.")
        if "private" in message:
            return PrivateMedia("Private kontentni yuklab bo‘lmaydi.")
        if any(word in message for word in ("not found", "does not exist", "unable to download webpage")):
            return MediaNotFound("Media topilmadi yoki o‘chirilgan.")
        if "there is no video in this post" in message:
            return UnsupportedMedia(
                "Bu postdagi media rasm yoki qo‘llab-quvvatlanmaydigan turda."
            )
        return UnsupportedMedia("Instagram media ma’lumotlarini olishning imkoni bo‘lmadi.")
