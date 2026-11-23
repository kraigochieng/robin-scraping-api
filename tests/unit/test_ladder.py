"""Tests for the ladder with fake tiers, and for the pure next_tier function."""

from collections.abc import Callable

import pytest
from factories import make_result, page, words
from pydantic import SecretStr

from robin_scraping_api.errors import ProfileBusyError, TierFetchError
from robin_scraping_api.tiers.ladder import (
    Ladder,
    LadderRequest,
    first_tier,
    next_tier,
)
from robin_scraping_api.tiers.models import FetchResult, Outcome, Tier, TierRequest

URL: str = "http://127.0.0.1/page"
GOOD: str = page(body=f"<main><h1>Title</h1><p>{words(count=120)}</p></main>")
BLOCKED: str = page(body='<div id="cf-chl-widget"></div>')
SPA: str = page(body='<div id="root"></div>')
LOGIN: str = page(body="<p>Sign in to continue reading.</p>")
THIN: str = page(body="<p>few words</p>")
THIN_WITH_AMP: str = page(head='<link rel="amphtml" href="/amp">', body="<p>few words</p>")

OUTCOME_HTML: dict[Outcome, tuple[int, str]] = {
    Outcome.OK: (200, GOOD),
    Outcome.BLOCKED: (403, BLOCKED),
    Outcome.NEEDS_JS: (200, SPA),
    Outcome.LOGIN_WALL: (200, LOGIN),
    Outcome.THIN: (200, THIN),
}


class Script:
    """Fake tiers: each tier returns a scripted result and the calls are recorded."""

    def __init__(self, *, steps: dict[Tier, FetchResult | Exception | Outcome]) -> None:
        """Store what each tier returns."""
        self.steps = steps
        self.calls: list[Tier] = []
        self.requests: list[TierRequest] = []

    def runner(self, *, tier: Tier) -> Callable[[TierRequest], FetchResult]:
        """Return the fake runner for one tier."""

        def run(request: TierRequest) -> FetchResult:
            self.calls.append(tier)
            self.requests.append(request)
            step = self.steps[tier]
            if isinstance(step, Exception):
                raise step
            if isinstance(step, Outcome):
                status, html = OUTCOME_HTML[step]
                return make_result(html=html, status=status, tier=tier)
            return step

        return run

    def ladder(self) -> Ladder:
        """Build a ladder over the fake runners."""
        return Ladder(runners={tier: self.runner(tier=tier) for tier in self.steps})


ALL_OK: dict[Tier, FetchResult | Exception | Outcome] = {tier: Outcome.OK for tier in Tier}


def run(*, steps: dict[Tier, FetchResult | Exception | Outcome], **options: object):
    """Run a ladder over scripted steps and return the script and the result."""
    script = Script(steps={**{tier: Outcome.THIN for tier in Tier}, **steps})
    result = script.ladder().run(request=LadderRequest(url=URL, **options))
    return script, result


def test_stops_at_first_ok() -> None:
    """An ok result at tier 1 ends the run with one attempt."""
    script, result = run(steps={Tier.HTTP: Outcome.OK})
    assert script.calls == [Tier.HTTP]
    assert result.outcome == Outcome.OK
    assert result.tier_used == Tier.HTTP
    assert len(result.attempts) == 1


@pytest.mark.parametrize(
    ("steps", "options", "expected_calls", "expected_outcome"),
    [
        ({Tier.HTTP: Outcome.NEEDS_JS, Tier.BROWSER: Outcome.OK}, {}, [Tier.HTTP, Tier.BROWSER], Outcome.OK),
        ({Tier.HTTP: Outcome.BLOCKED, Tier.HTTP_PROXY: Outcome.OK}, {"proxy": SecretStr("http://p:1")}, [Tier.HTTP, Tier.HTTP_PROXY], Outcome.OK),
        ({Tier.HTTP: Outcome.BLOCKED, Tier.HTTP_PROXY: Outcome.BLOCKED, Tier.BROWSER_STEALTH_PROXY: Outcome.OK}, {"proxy": SecretStr("http://p:1")}, [Tier.HTTP, Tier.HTTP_PROXY, Tier.BROWSER_STEALTH_PROXY], Outcome.OK),
        ({Tier.HTTP: Outcome.BLOCKED, Tier.BROWSER_STEALTH_PROXY: Outcome.OK}, {}, [Tier.HTTP, Tier.BROWSER_STEALTH_PROXY], Outcome.OK),
        ({Tier.HTTP: Outcome.LOGIN_WALL, Tier.BROWSER: Outcome.OK}, {"profile_path": "/profiles/a"}, [Tier.HTTP, Tier.BROWSER], Outcome.OK),
        ({Tier.HTTP: Outcome.LOGIN_WALL}, {}, [Tier.HTTP], Outcome.LOGIN_WALL),
        ({Tier.HTTP: Outcome.THIN, Tier.BROWSER: Outcome.OK}, {}, [Tier.HTTP, Tier.BROWSER], Outcome.OK),
        ({Tier.HTTP: TierFetchError(tier_label="http", reason="boom"), Tier.BROWSER: Outcome.OK}, {}, [Tier.HTTP, Tier.BROWSER], Outcome.OK),
    ],
    ids=["needs_js->browser", "blocked->proxy", "blocked->proxy->stealth", "blocked-no-proxy->stealth", "login_wall->browser", "login_wall-no-profile-stops", "thin-no-hints->browser", "error->next-usable"],
)
def test_jump_per_outcome(steps, options, expected_calls, expected_outcome) -> None:
    """Each diagnosis sends the run to the right next tier."""
    script, result = run(steps=steps, **options)
    assert script.calls == expected_calls
    assert result.outcome == expected_outcome


def test_thin_with_hints_goes_to_alternates_then_browser() -> None:
    """A thin page with an AMP link tries tier 2 first, then the browser."""
    thin_with_hints = make_result(html=THIN_WITH_AMP, tier=Tier.HTTP)
    script, result = run(steps={Tier.HTTP: thin_with_hints, Tier.ALTERNATES: Outcome.THIN, Tier.BROWSER: Outcome.OK})
    assert script.calls == [Tier.HTTP, Tier.ALTERNATES, Tier.BROWSER]
    assert result.tier_used == Tier.BROWSER


def test_thin_with_hints_stops_at_alternates_when_ok() -> None:
    """An ok alternate ends the run and the browser never runs."""
    script, result = run(steps={Tier.HTTP: make_result(html=THIN_WITH_AMP), Tier.ALTERNATES: Outcome.OK})
    assert script.calls == [Tier.HTTP, Tier.ALTERNATES]


def test_respects_min_tier() -> None:
    """With min_tier=4 the run starts at the browser and never uses tier 1."""
    script, _ = run(steps={Tier.BROWSER: Outcome.OK}, min_tier=Tier.BROWSER)
    assert script.calls == [Tier.BROWSER]


def test_respects_max_tier() -> None:
    """With max_tier=1 a blocked page is not escalated and the last failure is returned."""
    script, result = run(steps={Tier.HTTP: Outcome.BLOCKED}, max_tier=Tier.HTTP, proxy=SecretStr("http://p:1"))
    assert script.calls == [Tier.HTTP]
    assert result.outcome == Outcome.BLOCKED
    assert result.final is not None and result.final.status == 403


def test_min_tier_above_unusable_tiers_skips_to_usable() -> None:
    """min_tier=3 without a proxy starts at tier 4."""
    script, _ = run(steps={Tier.BROWSER: Outcome.OK}, min_tier=Tier.HTTP_PROXY)
    assert script.calls == [Tier.BROWSER]


def test_empty_range_returns_error_with_explanation() -> None:
    """When no tier is usable the result is an error with a process line."""
    script, result = run(steps={}, min_tier=Tier.HTTP_PROXY, max_tier=Tier.HTTP_PROXY)
    assert script.calls == []
    assert result.final is None
    assert result.outcome == Outcome.ERROR
    assert result.process


def test_never_exceeds_tier_count_and_never_repeats() -> None:
    """When every tier fails, each tier runs at most once."""
    steps = {tier: Outcome.BLOCKED for tier in Tier}
    script, result = run(steps=steps, proxy=SecretStr("http://p:1"), profile_path="/p")
    assert len(script.calls) <= len(Tier)
    assert len(script.calls) == len(set(script.calls))
    assert len(result.attempts) == len(script.calls)


@pytest.mark.parametrize("outcome", [Outcome.BLOCKED, Outcome.NEEDS_JS, Outcome.LOGIN_WALL, Outcome.THIN])
def test_all_fail_returns_last_failure(outcome: Outcome) -> None:
    """When nothing works, the last attempt is returned and the outcome says why."""
    steps = {tier: outcome for tier in Tier}
    script, result = run(steps=steps, proxy=SecretStr("http://p:1"), profile_path="/p")
    assert result.outcome == outcome
    assert result.final is not None
    assert result.final.tier == script.calls[-1]
    assert result.attempts[-1].outcome == outcome


def test_all_tiers_raise_gives_no_result() -> None:
    """When every tier raises, final is None and the trace explains each failure."""
    boom = TierFetchError(tier_label="x", reason="down")
    script, result = run(steps={tier: boom for tier in Tier}, proxy=SecretStr("http://p:1"))
    assert result.final is None
    assert result.outcome == Outcome.ERROR
    assert all(attempt.outcome == Outcome.ERROR for attempt in result.attempts)
    assert len(result.attempts) >= 1


def test_trace_is_always_present_and_readable() -> None:
    """Every run has attempts and plain-English process lines."""
    _, result = run(steps={Tier.HTTP: Outcome.BLOCKED, Tier.BROWSER_STEALTH_PROXY: Outcome.OK})
    assert [attempt.tier for attempt in result.attempts] == [1, 5]
    text = " ".join(result.process)
    assert "Tried tier 1 (http)" in text
    assert "Moving from tier 1 (http) to tier 5 (browser_stealth_proxy)" in text
    assert "Skipped tier 3 (http_proxy): no proxy is set." in text
    assert result.process[-1] == "Stopped at tier 5 (browser_stealth_proxy): the content is good."


def test_proxy_goes_only_to_proxy_tiers() -> None:
    """Tiers 1, 2 and 4 never receive the proxy."""
    script, _ = run(steps={tier: Outcome.BLOCKED for tier in Tier}, proxy=SecretStr("http://p:1"))
    for tier, request in zip(script.calls, script.requests, strict=True):
        assert (request.proxy is not None) == (tier in (Tier.HTTP_PROXY, Tier.BROWSER_STEALTH_PROXY))


def test_network_idle_only_after_needs_js() -> None:
    """The browser waits for network idle only when the page needed JavaScript."""
    script, _ = run(steps={Tier.HTTP: Outcome.NEEDS_JS, Tier.BROWSER: Outcome.OK})
    assert script.requests[-1].wait_for_network_idle is True
    script, _ = run(steps={Tier.HTTP: Outcome.LOGIN_WALL, Tier.BROWSER: Outcome.OK}, profile_path="/p")
    assert script.requests[-1].wait_for_network_idle is False


def test_profile_goes_only_to_browser_tiers() -> None:
    """The profile path is passed to browser tiers only."""
    script, _ = run(steps={Tier.HTTP: Outcome.LOGIN_WALL, Tier.BROWSER: Outcome.OK}, profile_path="/p")
    assert [request.profile_path for request in script.requests] == [None, "/p"]


def test_profile_busy_error_propagates() -> None:
    """A busy profile is not an outcome: the error reaches the caller."""
    busy = ProfileBusyError(profile_name="/p", waited_seconds=1)
    with pytest.raises(ProfileBusyError):
        run(steps={Tier.HTTP: Outcome.LOGIN_WALL, Tier.BROWSER: busy}, profile_path="/p")


NEXT_CASES: list[tuple[Outcome, Tier, dict[str, object], Tier | None]] = [
    (Outcome.OK, Tier.HTTP, {}, None),
    (Outcome.NEEDS_JS, Tier.HTTP, {}, Tier.BROWSER),
    (Outcome.NEEDS_JS, Tier.BROWSER, {}, None),
    (Outcome.BLOCKED, Tier.HTTP, {"has_proxy": True}, Tier.HTTP_PROXY),
    (Outcome.BLOCKED, Tier.HTTP, {}, Tier.BROWSER_STEALTH_PROXY),
    (Outcome.BLOCKED, Tier.HTTP_PROXY, {"has_proxy": True}, Tier.BROWSER_STEALTH_PROXY),
    (Outcome.BLOCKED, Tier.BROWSER_STEALTH_PROXY, {"has_proxy": True, "visited": {Tier.HTTP, Tier.HTTP_PROXY}}, None),
    (Outcome.LOGIN_WALL, Tier.HTTP, {"has_profile": True}, Tier.BROWSER),
    (Outcome.LOGIN_WALL, Tier.HTTP, {}, None),
    (Outcome.THIN, Tier.HTTP, {"has_alternate_hints": True}, Tier.ALTERNATES),
    (Outcome.THIN, Tier.HTTP, {}, Tier.BROWSER),
    (Outcome.THIN, Tier.ALTERNATES, {"has_alternate_hints": True}, Tier.BROWSER),
    (Outcome.ERROR, Tier.HTTP, {}, Tier.BROWSER),
    (Outcome.ERROR, Tier.HTTP, {"has_proxy": True}, Tier.HTTP_PROXY),
    (Outcome.ERROR, Tier.BROWSER_STEALTH_PROXY, {}, None),
    (Outcome.BLOCKED, Tier.HTTP, {"has_proxy": True, "max_tier": Tier.HTTP}, None),
    (Outcome.NEEDS_JS, Tier.HTTP, {"min_tier": Tier.BROWSER_STEALTH_PROXY}, None),
]


@pytest.mark.parametrize(("outcome", "current", "options", "expected"), NEXT_CASES)
def test_next_tier_table(outcome, current, options, expected) -> None:
    """The escalation table, one row per case."""
    arguments = {
        "outcome": outcome,
        "current": current,
        "visited": frozenset({current} | set(options.get("visited", set()))),
        "has_proxy": False,
        "has_profile": False,
        "has_alternate_hints": False,
        "min_tier": Tier.HTTP,
        "max_tier": Tier.BROWSER_STEALTH_PROXY,
    }
    arguments.update({key: value for key, value in options.items() if key != "visited"})
    arguments["visited"] = frozenset({current} | set(options.get("visited", set())))
    assert next_tier(**arguments) == expected


def test_first_tier() -> None:
    """The first tier is the cheapest usable tier in range."""
    assert first_tier(min_tier=Tier.HTTP, max_tier=Tier.BROWSER, has_proxy=False, has_profile=False) == Tier.HTTP
    assert first_tier(min_tier=Tier.ALTERNATES, max_tier=Tier.BROWSER, has_proxy=False, has_profile=False) == Tier.BROWSER
    assert first_tier(min_tier=Tier.ALTERNATES, max_tier=Tier.BROWSER, has_proxy=True, has_profile=False) == Tier.HTTP_PROXY
    assert first_tier(min_tier=Tier.HTTP_PROXY, max_tier=Tier.HTTP_PROXY, has_proxy=False, has_profile=False) is None
