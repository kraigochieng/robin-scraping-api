"""Tests for the per-profile lock registry and the 409 mapping."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from robin_scraping_api.errors import ProfileBusyError
from robin_scraping_api.main import app
from robin_scraping_api.profile_locks import ProfileLockRegistry
from robin_scraping_api.services import fetch as fetch_service
from robin_scraping_api.settings import settings


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


def test_api_returns_409_with_retry_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request for a busy profile gets 409 and a Retry-After header."""
    (tmp_path / "busy").mkdir()
    monkeypatch.setattr(fetch_service, "PROFILES_DIR", tmp_path)
    monkeypatch.setattr(settings, "profile_lock_timeout_seconds", 0.2)
    release = threading.Event()
    entered = threading.Event()

    def slow_browse(*, url: str, session_kwargs: dict[str, object]) -> SimpleNamespace:
        entered.set()
        release.wait(timeout=5)
        return SimpleNamespace(
            status=200, reason="OK", body=b"<html><body><main>hi</main></body></html>"
        )

    monkeypatch.setattr(fetch_service, "_browse", slow_browse)
    client = TestClient(app)
    results: list[int] = []
    worker = threading.Thread(
        target=lambda: results.append(
            client.get("/fetch", params={"url": "http://127.0.0.1/", "profile_name": "busy"}).status_code
        )
    )
    worker.start()
    assert entered.wait(timeout=5)

    second = client.get(
        "/fetch", params={"url": "http://127.0.0.1/", "profile_name": "busy"}
    )
    release.set()
    worker.join()

    assert second.status_code == 409
    assert "Retry-After" in second.headers
    assert results == [200]


def test_api_missing_profile_is_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A profile that does not exist still returns 404."""
    monkeypatch.setattr(fetch_service, "PROFILES_DIR", tmp_path)
    response = TestClient(app).get(
        "/fetch", params={"url": "http://127.0.0.1/", "profile_name": "nope"}
    )
    assert response.status_code == 404
