"""Per-profile locks. Two requests must not share one browser user_data_dir."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from robin_scraping_api.errors import ProfileBusyError


class ProfileLockRegistry:
    """Hand out one lock for each profile name. Acquiring has a side effect (blocks)."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._locks: dict[str, threading.Lock] = {}
        self._registry_guard: threading.Lock = threading.Lock()

    def _lock_for(self, *, profile_name: str) -> threading.Lock:
        """Return the lock of the profile, create it on first use."""
        with self._registry_guard:
            return self._locks.setdefault(profile_name, threading.Lock())

    @contextmanager
    def hold(self, *, profile_name: str, timeout_seconds: float) -> Iterator[None]:
        """Hold the profile lock, wait up to the timeout, else raise ProfileBusyError."""
        lock = self._lock_for(profile_name=profile_name)
        if not lock.acquire(timeout=timeout_seconds):
            raise ProfileBusyError(
                profile_name=profile_name, waited_seconds=timeout_seconds
            )
        try:
            yield
        finally:
            lock.release()


profile_locks: ProfileLockRegistry = ProfileLockRegistry()
