from app.downloader import MediaItem, ResolveResult


def test_resolve_result_defaults_to_not_partial() -> None:
    result = ResolveResult(items=[MediaItem(url="https://x/1.jpg", filename="1.jpg", media_type="photo")])
    assert result.partial is False


def test_resolve_result_can_be_marked_partial() -> None:
    result = ResolveResult(
        items=[MediaItem(url="https://x/1.jpg", filename="1.jpg", media_type="photo")],
        partial=True,
    )
    assert result.partial is True
    assert len(result.items) == 1
