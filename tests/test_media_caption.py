from unittest.mock import AsyncMock

import pytest

from app.texts import TEXT_DEFS_BY_KEY
from app.worker import build_caption


def test_media_caption_default_is_registered() -> None:
    assert TEXT_DEFS_BY_KEY["media_caption"].default == "MediaHub orqali yuklandi"


def test_media_caption_link_text_default_is_registered() -> None:
    assert TEXT_DEFS_BY_KEY["media_caption_link_text"].default == "Video havolasi"


def test_media_caption_formatting_single_vs_multi() -> None:
    base = TEXT_DEFS_BY_KEY["media_caption"].default
    single = base
    multi = f"{base} • 2/3"
    assert single == "MediaHub orqali yuklandi"
    assert multi == "MediaHub orqali yuklandi • 2/3"


@pytest.mark.asyncio
async def test_build_caption_wraps_source_url_in_html_link(monkeypatch) -> None:
    """The caption must be: <a href="SOURCE_URL">LINK_TEXT</a>\\nCAPTION_TEXT
    -- a hidden link to the original Instagram post using the editable link
    text, followed by the editable plain caption on its own line."""

    async def fake_get_text(pool, key, **kwargs):
        return {"media_caption_link_text": "Video havolasi", "media_caption": "MediaHub orqali yuklandi"}[key]

    monkeypatch.setattr("app.worker.get_text", fake_get_text)

    caption = await build_caption(pool=None, source_url="https://www.instagram.com/reel/ABC123/")

    assert caption == (
        '<a href="https://www.instagram.com/reel/ABC123/">Video havolasi</a>\n'
        "MediaHub orqali yuklandi"
    )


@pytest.mark.asyncio
async def test_build_caption_escapes_html_special_characters(monkeypatch) -> None:
    """If an admin's custom link text or caption contains HTML-special
    characters (<, >, &, "), they must be escaped -- otherwise a custom
    caption could break the HTML parsing of the whole message, or an admin
    could accidentally/intentionally inject markup."""

    async def fake_get_text(pool, key, **kwargs):
        return {
            "media_caption_link_text": "Click <here> & \"go\"",
            "media_caption": "Caption with <b>bold</b> & stuff",
        }[key]

    monkeypatch.setattr("app.worker.get_text", fake_get_text)

    caption = await build_caption(pool=None, source_url="https://www.instagram.com/reel/ABC123/")

    assert "<here>" not in caption
    assert "&lt;here&gt;" in caption
    assert "<b>bold</b>" not in caption
    assert "&lt;b&gt;bold&lt;/b&gt;" in caption
    # The href itself must still be intact and well-formed.
    assert '<a href="https://www.instagram.com/reel/ABC123/">' in caption
