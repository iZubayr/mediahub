class MediaHubError(Exception):
    """Base class for expected, user-facing errors."""


class InvalidInstagramUrl(MediaHubError):
    pass


class UnsupportedMedia(MediaHubError):
    pass


class MediaNotFound(MediaHubError):
    pass


class PrivateMedia(MediaHubError):
    pass


class AuthenticationRequired(MediaHubError):
    pass


class QueueFull(MediaHubError):
    pass


class UserLimitReached(MediaHubError):
    pass


class MediaTooLarge(MediaHubError):
    pass
