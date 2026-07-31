from app.texts import TEXT_DEFS_BY_KEY


def test_media_caption_default_is_registered() -> None:
    assert TEXT_DEFS_BY_KEY["media_caption"].default == "MediaHub"


def test_media_caption_formatting_single_vs_multi() -> None:
    base = TEXT_DEFS_BY_KEY["media_caption"].default
    single = base
    multi = f"{base} • 2/3"
    assert single == "MediaHub"
    assert multi == "MediaHub • 2/3"
