import pytest


@pytest.fixture(autouse=True)
def _reset_force_sub_channel_cache():
    """The force-sub channel cache is module-level (not per-instance) so
    that admin.py's invalidate_channel_cache() can clear it after an
    add/remove regardless of which ForceSubscribeMiddleware instance is
    running in the single standalone process. That global state must be
    reset between tests to keep them isolated from each other, since
    otherwise a channel list cached by one test could leak into the next."""
    import app.force_sub as force_sub_module

    force_sub_module._cached_channels = []
    force_sub_module._cache_expires_at = 0.0
    yield
    force_sub_module._cached_channels = []
    force_sub_module._cache_expires_at = 0.0


@pytest.fixture(autouse=True)
def _reset_texts_cache():
    """Same reasoning as the force-sub cache above, applied to the
    editable-texts cache."""
    import app.texts as texts_module

    texts_module._cache = {}
    texts_module._cache_expires_at = 0.0
    yield
    texts_module._cache = {}
    texts_module._cache_expires_at = 0.0


@pytest.fixture(autouse=True)
def _reset_runtime_settings_cache():
    """Same reasoning as the force-sub cache above, applied to the
    editable rate-limits cache."""
    import app.runtime_settings as runtime_settings_module

    runtime_settings_module._cache = {}
    runtime_settings_module._cache_expires_at = 0.0
    yield
    runtime_settings_module._cache = {}
    runtime_settings_module._cache_expires_at = 0.0
