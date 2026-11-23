"""Browser tests. Skipped unless RUN_BROWSER_TESTS=1. They use the local fixture server only."""

import pytest
from fixture_server import FixtureServer

from robin_scraping_api.profile_locks import ProfileLockRegistry
from robin_scraping_api.tiers.browser import fetch_browser
from robin_scraping_api.tiers.models import FetchResult, Tier, TierRequest

pytestmark = pytest.mark.browser


def load_result(*, server: FixtureServer, path: str, wait_for_network_idle: bool) -> FetchResult:
    """Load a fixture page in the real browser tier and return the result."""
    result = fetch_browser(
        request=TierRequest(
            url=server.base_url + path,
            wait_for_network_idle=wait_for_network_idle,
            timeout_seconds=30,
        ),
        tier=Tier.BROWSER,
        locks=ProfileLockRegistry(),
        lock_timeout_seconds=1,
    )
    return result


def load(*, server: FixtureServer, path: str, wait_for_network_idle: bool) -> str:
    """Load a fixture page in the real browser tier and return its HTML."""
    return load_result(server=server, path=path, wait_for_network_idle=wait_for_network_idle).html


def test_spa_shell_renders(fixture_server: FixtureServer) -> None:
    """The browser runs the page script and the article from /api/article.json appears."""
    html = load(server=fixture_server, path="/spa", wait_for_network_idle=True)
    assert "The Harbour Reopens" in html
    assert "reopened on Monday" in html
    assert fixture_server.hits["/api/article.json"] == 1


def test_images_and_fonts_are_not_loaded(fixture_server: FixtureServer) -> None:
    """Blocked resource types never reach the server."""
    load(server=fixture_server, path="/spa", wait_for_network_idle=True)
    assert fixture_server.hits["/assets/pixel.png"] == 0
    assert fixture_server.hits["/assets/font.woff2"] == 0


def test_xhr_api_candidate_is_captured(fixture_server: FixtureServer) -> None:
    """The article JSON that the SPA fetched is reported as a candidate API."""
    result = load_result(server=fixture_server, path="/spa", wait_for_network_idle=True)
    urls = [candidate.url for candidate in result.api_candidates]
    assert urls == [fixture_server.base_url + "/api/article.json"]
    assert "og_title" in result.api_candidates[0].matched_on
