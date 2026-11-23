"""Integration tests: the real HTTP tiers against the local fixture server.

No browser runs. A fake browser factory fails the test if a browser tier is reached
when it must not be. Hit counters prove which tiers ran and in which order.
"""

import pytest
from fixture_server import FixtureServer
from pydantic import SecretStr

from robin_scraping_api.tiers.classify import ClassifyConfig
from robin_scraping_api.tiers.ladder import Ladder, LadderRequest, LadderResult
from robin_scraping_api.tiers.models import Outcome, Tier
from robin_scraping_api.tiers.wiring import build_ladder


class BrowserMustNotRun:
    """A session factory that fails the test when called."""

    def __call__(self, **kwargs: object) -> object:
        """Fail: this test must not reach a browser tier."""
        raise AssertionError("a browser tier ran in an HTTP-only test")


@pytest.fixture
def ladder() -> Ladder:
    """A real ladder whose browser tiers fail the test if they run."""
    return build_ladder(
        classify_config=ClassifyConfig(),
        lock_timeout_seconds=1,
        session_factory=BrowserMustNotRun(),
    )


def run(*, ladder: Ladder, server: FixtureServer, path: str, **options: object) -> LadderResult:
    """Run the ladder against one fixture path."""
    return ladder.run(request=LadderRequest(url=server.base_url + path, **options))


@pytest.mark.parametrize("path", ["/article/plain", "/article/jsonld", "/article/next"])
def test_static_pages_use_tier_1_with_one_request(ladder: Ladder, fixture_server: FixtureServer, path: str) -> None:
    """A complete static page is served by tier 1 with exactly one request."""
    result = run(ladder=ladder, server=fixture_server, path=path)
    assert result.tier_used == Tier.HTTP
    assert result.outcome == Outcome.OK
    assert fixture_server.hits[path] == 1
    assert fixture_server.total_hits() == 1


def test_redirect_chain_is_followed_by_tier_1(ladder: Ladder, fixture_server: FixtureServer) -> None:
    """Redirects are followed inside tier 1: three requests, one attempt."""
    result = run(ladder=ladder, server=fixture_server, path="/redirect/start")
    assert result.tier_used == Tier.HTTP
    assert result.final is not None and result.final.final_url.endswith("/article/plain")
    assert [fixture_server.hits[path] for path in ("/redirect/start", "/redirect/middle", "/article/plain")] == [1, 1, 1]
    assert len(result.attempts) == 1


@pytest.mark.parametrize(
    ("path", "status"),
    [("/challenge/200", 200), ("/challenge/403", 403), ("/status/429", 429), ("/status/503", 503)],
)
def test_blocked_without_proxy_stops_when_browser_is_not_allowed(
    ladder: Ladder, fixture_server: FixtureServer, path: str, status: int
) -> None:
    """Without a proxy there is no tier 3. With max_tier=3 the run stops after one request."""
    result = run(ladder=ladder, server=fixture_server, path=path, max_tier=Tier.HTTP_PROXY)
    assert result.outcome == Outcome.BLOCKED
    assert result.final is not None and result.final.status == status
    assert fixture_server.total_hits() == 1
    assert "Skipped tier 3 (http_proxy): no proxy is set." in result.process


def test_blocked_escalates_to_proxy_tier(ladder: Ladder, fixture_server: FixtureServer) -> None:
    """A blocked tier 1 moves to tier 3, which sends the request through the proxy."""
    result = run(
        ladder=ladder,
        server=fixture_server,
        path="/needs-proxy",
        proxy=SecretStr(fixture_server.base_url),
        max_tier=Tier.HTTP_PROXY,
    )
    assert [(attempt.tier, attempt.outcome) for attempt in result.attempts] == [
        (1, Outcome.BLOCKED),
        (3, Outcome.OK),
    ]
    assert result.tier_used == Tier.HTTP_PROXY
    assert fixture_server.hits["/needs-proxy"] == 2
    assert fixture_server.proxied_hits["/needs-proxy"] == 1


@pytest.mark.parametrize(
    ("path", "alternate_path", "kind"),
    [
        ("/amp-source/story", "/amp/story", "amp"),
        ("/rss-source/story-two", "/feed.xml", "feed"),
        ("/wp-source/my-post", "/wp-json/wp/v2/posts", "wp_json"),
    ],
)
def test_thin_page_escalates_to_alternates(
    ladder: Ladder, fixture_server: FixtureServer, path: str, alternate_path: str, kind: str
) -> None:
    """A thin page with an alternate hint is completed by tier 2, with no extra requests."""
    result = run(ladder=ladder, server=fixture_server, path=path, max_tier=Tier.HTTP_PROXY)
    assert result.tier_used == Tier.ALTERNATES
    assert result.outcome == Outcome.OK
    assert result.final is not None and result.final.extra["alternate_kind"] == kind
    assert [attempt.tier for attempt in result.attempts] == [1, 2]
    assert fixture_server.hits[path] == 1
    assert fixture_server.hits[alternate_path] == 1
    assert fixture_server.total_hits() == 2


def test_thin_page_without_hints_makes_no_alternate_request(ladder: Ladder, fixture_server: FixtureServer) -> None:
    """With no hints, tier 2 is skipped and no other URL is requested."""
    result = run(ladder=ladder, server=fixture_server, path="/thin", max_tier=Tier.HTTP_PROXY)
    assert result.outcome == Outcome.THIN
    assert fixture_server.total_hits() == 1


def test_paywall_without_profile_stops(ladder: Ladder, fixture_server: FixtureServer) -> None:
    """A paywall stub is a login wall, and without a profile the ladder stops."""
    result = run(ladder=ladder, server=fixture_server, path="/paywall")
    assert result.outcome == Outcome.LOGIN_WALL
    assert fixture_server.total_hits() == 1
    assert any("no profile_name was given" in line for line in result.process)


def test_login_page_is_a_login_wall(ladder: Ladder, fixture_server: FixtureServer) -> None:
    """A page with a password form is diagnosed as a login wall."""
    assert run(ladder=ladder, server=fixture_server, path="/login").outcome == Outcome.LOGIN_WALL


def test_spa_shell_needs_js_and_stops_without_browser(ladder: Ladder, fixture_server: FixtureServer) -> None:
    """An empty SPA shell is needs_js. With max_tier=3 no browser runs and nothing else is fetched."""
    result = run(ladder=ladder, server=fixture_server, path="/spa", max_tier=Tier.HTTP_PROXY)
    assert result.outcome == Outcome.NEEDS_JS
    assert fixture_server.total_hits() == 1
    assert fixture_server.hits["/api/article.json"] == 0


def test_unknown_path_is_an_error_outcome(ladder: Ladder, fixture_server: FixtureServer) -> None:
    """A 404 is an error, and the ladder tries the next usable tier only."""
    result = run(ladder=ladder, server=fixture_server, path="/status/404", max_tier=Tier.HTTP_PROXY)
    assert result.outcome == Outcome.ERROR
    assert fixture_server.total_hits() == 1


def test_connection_refused_is_an_error_attempt(ladder: Ladder) -> None:
    """A dead port gives an error attempt with a reason, not an exception."""
    result = ladder.run(request=LadderRequest(url="http://127.0.0.1:1/x", max_tier=Tier.HTTP))
    assert result.final is None
    assert result.attempts[0].outcome == Outcome.ERROR
    assert result.attempts[0].reason
