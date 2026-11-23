"""Tests for the browser tier with a fake session. No browser starts."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from robin_scraping_api.errors import ProfileBusyError, TierFetchError
from robin_scraping_api.profile_locks import ProfileLockRegistry
from robin_scraping_api.tiers.browser import fetch_browser
from robin_scraping_api.tiers.models import Tier, TierRequest


class FakeSession:
    """Records how it was created and used."""

    created: list[dict[str, object]] = []
    fetched: list[tuple[str, dict[str, object]]] = []
    failure: Exception | None = None

    def __init__(self, **kwargs: object) -> None:
        """Record the session arguments."""
        FakeSession.created.append(kwargs)

    def __enter__(self) -> "FakeSession":
        """Enter the session."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Leave the session."""

    def fetch(self, url: str, **kwargs: object) -> object:
        """Record the fetch and return a page, or raise the scripted failure."""
        FakeSession.fetched.append((url, kwargs))
        if FakeSession.failure:
            raise FakeSession.failure
        return SimpleNamespace(status=200, headers={"a": "b"}, body=b"<html>hi</html>", url=url, encoding="utf-8")


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    """Clear the recorded calls."""
    FakeSession.created = []
    FakeSession.fetched = []
    FakeSession.failure = None


def run(*, tier: Tier, request: TierRequest, locks: ProfileLockRegistry | None = None):
    """Call the browser tier with the fake session."""
    return fetch_browser(
        request=request, tier=tier, locks=locks or ProfileLockRegistry(), lock_timeout_seconds=0.1, session_factory=FakeSession
    )


def test_tier_4_is_headless_and_blocks_resources() -> None:
    """Tier 4 runs headless, blocks images, fonts and media, and does not wait for network idle."""
    result = run(tier=Tier.BROWSER, request=TierRequest(url="http://127.0.0.1/x"))
    arguments = FakeSession.created[0]
    assert arguments["headless"] is True and arguments["disable_resources"] is True
    assert FakeSession.fetched[0][1] == {"network_idle": False}
    assert (result.status, result.html, result.tier) == (200, "<html>hi</html>", Tier.BROWSER)


def test_tier_5_is_headful_with_proxy() -> None:
    """Tier 5 is headful and passes the proxy."""
    run(tier=Tier.BROWSER_STEALTH_PROXY, request=TierRequest(url="http://127.0.0.1/x", proxy=SecretStr("http://u:p@127.0.0.1:1")))
    assert FakeSession.created[0]["headless"] is False
    assert FakeSession.created[0]["proxy"] == "http://u:p@127.0.0.1:1"


def test_network_idle_follows_request() -> None:
    """wait_for_network_idle is passed to the page load."""
    run(tier=Tier.BROWSER, request=TierRequest(url="http://127.0.0.1/x", wait_for_network_idle=True))
    assert FakeSession.fetched[0][1] == {"network_idle": True}


def test_profile_is_used_and_locked() -> None:
    """The profile path becomes user_data_dir, and a held lock gives ProfileBusyError."""
    locks = ProfileLockRegistry()
    request = TierRequest(url="http://127.0.0.1/x", profile_path="/profiles/a")
    run(tier=Tier.BROWSER, request=request, locks=locks)
    assert FakeSession.created[0]["user_data_dir"] == "/profiles/a"
    with locks.hold(profile_name="/profiles/a", timeout_seconds=1):
        with pytest.raises(ProfileBusyError):
            run(tier=Tier.BROWSER, request=request, locks=locks)


def test_browser_error_is_converted_and_redacted() -> None:
    """A library error becomes TierFetchError without the proxy password."""
    FakeSession.failure = RuntimeError("proxy http://u:pa55@127.0.0.1:1 refused")
    request = TierRequest(url="http://127.0.0.1/x", proxy=SecretStr("http://u:pa55@127.0.0.1:1"))
    with pytest.raises(TierFetchError) as caught:
        run(tier=Tier.BROWSER_STEALTH_PROXY, request=request)
    assert "pa55" not in caught.value.reason
