import asyncio


class WorkerActivityTracker:
    """In-process counter of how many workers are currently processing a
    job. Used only in standalone mode (bot + workers in one process) to let
    an incoming request skip the queue and run immediately when no worker
    is busy, instead of always paying for an enqueue -> poll -> claim
    round-trip through Postgres even when nothing is competing for
    capacity.

    This is intentionally NOT shared across processes (e.g. via Postgres)
    — in webhook mode, the bot and workers are separate processes/services
    with no way to know each other's in-memory state without another
    round-trip, which would defeat the purpose. In that mode, everything
    always goes through the queue as before.
    """

    def __init__(self) -> None:
        self._active_count = 0
        self._lock = asyncio.Lock()

    @property
    def is_idle(self) -> bool:
        return self._active_count == 0

    async def enter(self) -> None:
        async with self._lock:
            self._active_count += 1

    async def exit(self) -> None:
        async with self._lock:
            self._active_count = max(0, self._active_count - 1)
