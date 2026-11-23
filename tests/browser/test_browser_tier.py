"""Browser tests. Skipped unless RUN_BROWSER_TESTS=1. They use the local fixture server only."""

import pytest
from fixture_server import FixtureServer

from robin_scraping_api.profile_locks import ProfileLockRegistry
from robin_scraping_api.tiers.browser import fetch_browser
from robin_scraping_api.tiers.models import Tier, TierRequest

pytestmark = pytest.mark.browser


def load(*, server: FixtureServer, path: str, wait_for_network_idle: bool) -> str:
    """Load a fixture page in the real browser tier and return its HTML."""
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
    return result.html


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
