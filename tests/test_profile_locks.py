"""Tests for the per-profile lock registry and the 409 mapping."""

import threading
import time

import pytest

from robin_scraping_api.errors import ProfileBusyError
from robin_scraping_api.profile_locks import ProfileLockRegistry


def test_same_profile_second_holder_times_out() -> None:
    """A second holder of one profile raises ProfileBusyError after the timeout."""
    registry = ProfileLockRegistry()
    with registry.hold(profile_name="a", timeout_seconds=1):
        started = time.monotonic()
        with pytest.raises(ProfileBusyError) as caught:
            with registry.hold(profile_name="a", timeout_seconds=0.2):
                pass
    assert time.monotonic() - started >= 0.2
    assert caught.value.profile_name == "a"


def test_second_holder_waits_then_succeeds() -> None:
    """A second holder gets the lock when the first releases inside the timeout."""
    registry = ProfileLockRegistry()
    order: list[str] = []

    def first() -> None:
        with registry.hold(profile_name="a", timeout_seconds=1):
            order.append("first-in")
            time.sleep(0.2)
            order.append("first-out")

    worker = threading.Thread(target=first)
    worker.start()
    time.sleep(0.05)
    with registry.hold(profile_name="a", timeout_seconds=2):
        order.append("second-in")
    worker.join()
    assert order == ["first-in", "first-out", "second-in"]


def test_different_profiles_do_not_block_each_other() -> None:
    """Locks of two profiles are independent."""
    registry = ProfileLockRegistry()
    with registry.hold(profile_name="a", timeout_seconds=1):
        with registry.hold(profile_name="b", timeout_seconds=0.1):
            pass


def test_lock_is_released_after_error() -> None:
    """An exception inside the block still releases the lock."""
    registry = ProfileLockRegistry()
    with pytest.raises(RuntimeError):
        with registry.hold(profile_name="a", timeout_seconds=1):
            raise RuntimeError("boom")
    with registry.hold(profile_name="a", timeout_seconds=0.1):
        pass
