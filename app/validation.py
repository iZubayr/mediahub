import re
from urllib.parse import urlparse

from .errors import InvalidInstagramUrl


ALLOWED_HOSTS = {"instagram.com", "www.instagram.com", "instagr.am", "www.instagr.am"}
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


def extract_url(text: str) -> str | None:
    match = URL_PATTERN.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,!?)]}")


def extract_urls(text: str) -> list[str]:
    """Returns every URL found in `text`, in the order they appear.
    Duplicates are removed (keeping first occurrence) so pasting the same
    link twice doesn't queue it twice."""
    seen: set[str] = set()
    urls: list[str] = []
    for match in URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(".,!?)]}")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def validate_instagram_url(value: str, *, allow_stories: bool = False) -> str:
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower().rstrip(".")

    if parsed.scheme not in {"http", "https"} or host not in ALLOWED_HOSTS:
        raise InvalidInstagramUrl("Faqat Instagram havolalari qo‘llab-quvvatlanadi.")

    if not parsed.path or parsed.path == "/":
        raise InvalidInstagramUrl("Media post yoki Reel havolasini yuboring.")

    if parsed.path.startswith("/stories/") and not allow_stories:
        raise InvalidInstagramUrl(
            "Story’lar qo‘llab-quvvatlanmaydi — ular Instagram login talab qiladi. "
            "Post yoki Reel havolasini yuboring."
        )

    supported_prefixes = ("/p/", "/reel/", "/reels/", "/tv/")
    if allow_stories:
        supported_prefixes += ("/stories/",)
    if not parsed.path.startswith(supported_prefixes):
        raise InvalidInstagramUrl("Bu Instagram havolasi media postga o‘xshamaydi.")

    return value.strip()
