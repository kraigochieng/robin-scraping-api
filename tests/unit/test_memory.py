"""Tests for the domain memory with a fake clock. Storage tests use a temporary SQLite file."""

from pathlib import Path

import pytest

from robin_scraping_api.memory.base import DomainRecord, MemoryConfig
from robin_scraping_api.memory.policy import StartPlan, apply_result, choose_start, describe_update
from robin_scraping_api.memory.service import DomainMemoryService, domain_of
from robin_scraping_api.memory.sqlite import SqliteDomainMemory
from robin_scraping_api.tiers.models import Outcome, Tier

CONFIG: MemoryConfig = MemoryConfig(ttl_seconds=100, probe_every=3, failure_threshold=2)
DOMAIN: str = "example.test"


class FakeClock:
    """A clock that moves only when the test moves it."""

    def __init__(self, *, now: float = 1000.0) -> None:
        """Start at a fixed time."""
        self.now = now

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now

    def advance(self, *, seconds: float) -> None:
        """Move the fake time forward."""
        self.now += seconds


def record(*, tier: Tier, last_success: float = 1000.0, failures: int = 0, since_probe: int = 0) -> DomainRecord:
    """Build a record."""
    return DomainRecord(domain=DOMAIN, tier=int(tier), last_success=last_success, failure_count=failures, requests_since_probe=since_probe)


def plan_for(*, found: DomainRecord | None, now: float = 1000.0, min_tier: Tier = Tier.HTTP, max_tier: Tier = Tier.BROWSER_STEALTH_PROXY) -> StartPlan:
    """Call choose_start with test defaults."""
    return choose_start(domain=DOMAIN, record=found, now=now, config=CONFIG, min_tier=min_tier, max_tier=max_tier)


START_CASES: list[tuple[str, DomainRecord | None, float, Tier, bool]] = [
    ("no record", None, 1000, Tier.HTTP, False),
    ("remembered browser", record(tier=Tier.BROWSER), 1050, Tier.BROWSER, False),
    ("ttl expired probes from cheapest", record(tier=Tier.BROWSER), 1101, Tier.HTTP, True),
    ("ttl edge not expired", record(tier=Tier.BROWSER), 1100, Tier.BROWSER, False),
    ("probe after N requests", record(tier=Tier.BROWSER, since_probe=3), 1010, Tier.HTTP, True),
    ("below N requests", record(tier=Tier.BROWSER, since_probe=2), 1010, Tier.BROWSER, False),
    ("demote after failures", record(tier=Tier.BROWSER, failures=2), 1010, Tier.BROWSER_STEALTH_PROXY, False),
    ("demote skips alternates", record(tier=Tier.HTTP, failures=2), 1010, Tier.HTTP_PROXY, False),
    ("demote caps at top tier", record(tier=Tier.BROWSER_STEALTH_PROXY, failures=5), 1010, Tier.BROWSER_STEALTH_PROXY, False),
    ("below failure threshold stays", record(tier=Tier.BROWSER, failures=1), 1010, Tier.BROWSER, False),
    ("demotion beats ttl probe", record(tier=Tier.BROWSER, failures=2), 5000, Tier.BROWSER_STEALTH_PROXY, False),
    ("remembered http never probes", record(tier=Tier.HTTP), 9999, Tier.HTTP, False),
    ("remembered alternates starts at http", record(tier=Tier.ALTERNATES), 1010, Tier.HTTP, False),
]


@pytest.mark.parametrize(("name", "found", "now", "expected_tier", "expected_probe"), START_CASES, ids=[case[0] for case in START_CASES])
def test_choose_start(name: str, found: DomainRecord | None, now: float, expected_tier: Tier, expected_probe: bool) -> None:
    """Each memory situation gives its start tier."""
    plan = plan_for(found=found, now=now)
    assert (plan.start_tier, plan.is_probe) == (expected_tier, expected_probe)
    assert plan.reason.startswith("Memory:")


def test_request_min_tier_is_a_floor() -> None:
    """A min_tier above the remembered tier wins. A probe starts at min_tier."""
    assert plan_for(found=record(tier=Tier.HTTP), min_tier=Tier.BROWSER).start_tier == Tier.BROWSER
    assert plan_for(found=record(tier=Tier.BROWSER_STEALTH_PROXY), now=5000, min_tier=Tier.BROWSER).start_tier == Tier.BROWSER


def test_request_max_tier_is_a_cap() -> None:
    """A remembered tier above max_tier is lowered to max_tier."""
    assert plan_for(found=record(tier=Tier.BROWSER), max_tier=Tier.HTTP_PROXY).start_tier == Tier.HTTP_PROXY


def test_reasons_are_plain_sentences() -> None:
    """The reason says what the memory knew."""
    assert plan_for(found=record(tier=Tier.BROWSER)).reason == "Memory: example.test worked at tier 4 (browser) last time, so the ladder starts there."
    assert "older than 100 seconds" in plan_for(found=record(tier=Tier.BROWSER), now=5000).reason
    assert "failed 2 times in a row" in plan_for(found=record(tier=Tier.BROWSER, failures=2)).reason


NOW: float = 2000.0
PROBE: StartPlan = StartPlan(start_tier=Tier.HTTP, is_probe=True, reason="r")
NORMAL: StartPlan = StartPlan(start_tier=Tier.BROWSER, is_probe=False, reason="r")


def test_success_creates_record() -> None:
    """The first success is stored with the tier that worked."""
    saved = apply_result(domain=DOMAIN, record=None, plan=NORMAL, outcome=Outcome.OK, tier_used=Tier.BROWSER, now=NOW)
    assert saved == DomainRecord(domain=DOMAIN, tier=4, last_success=NOW, failure_count=0, requests_since_probe=0)


def test_success_resets_failures_and_counts_requests() -> None:
    """Success clears the failure count and counts the request since the last probe."""
    saved = apply_result(domain=DOMAIN, record=record(tier=Tier.BROWSER, failures=2, since_probe=1), plan=NORMAL, outcome=Outcome.OK, tier_used=Tier.BROWSER, now=NOW)
    assert saved is not None and (saved.failure_count, saved.requests_since_probe, saved.last_success) == (0, 2, NOW)


def test_probe_success_lowers_tier_and_resets_counter() -> None:
    """A probe that works at a cheaper tier lowers the remembered tier."""
    saved = apply_result(domain=DOMAIN, record=record(tier=Tier.BROWSER, since_probe=3), plan=PROBE, outcome=Outcome.OK, tier_used=Tier.HTTP, now=NOW)
    assert saved is not None and (saved.tier, saved.requests_since_probe) == (1, 0)


def test_success_at_higher_tier_raises_remembered_tier() -> None:
    """When only a dearer tier works now, the memory moves up."""
    saved = apply_result(domain=DOMAIN, record=record(tier=Tier.HTTP), plan=NORMAL, outcome=Outcome.OK, tier_used=Tier.BROWSER, now=NOW)
    assert saved is not None and saved.tier == 4


def test_failure_increments_count_and_keeps_tier() -> None:
    """A failed run adds one failure and keeps the tier and last_success."""
    saved = apply_result(domain=DOMAIN, record=record(tier=Tier.BROWSER), plan=NORMAL, outcome=Outcome.BLOCKED, tier_used=Tier.BROWSER, now=NOW)
    assert saved is not None and (saved.failure_count, saved.tier, saved.last_success) == (1, 4, 1000.0)


def test_failure_without_record_saves_nothing() -> None:
    """With no record and no success there is nothing to remember."""
    assert apply_result(domain=DOMAIN, record=None, plan=NORMAL, outcome=Outcome.ERROR, tier_used=None, now=NOW) is None


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (None, None, "Memory: nothing saved for example.test, because no tier gave good content."),
        (None, record(tier=Tier.HTTP), "Memory: saved tier 1 (http) for example.test."),
        (record(tier=Tier.BROWSER), record(tier=Tier.HTTP), "Memory: example.test now works at tier 1 (http), before it was tier 4 (browser)."),
        (record(tier=Tier.BROWSER), record(tier=Tier.BROWSER, failures=2), "Memory: no tier gave good content for example.test. The failure count is now 2."),
    ],
)
def test_describe_update(before: DomainRecord | None, after: DomainRecord | None, expected: str) -> None:
    """The update sentence tells what changed."""
    assert describe_update(domain=DOMAIN, before=before, after=after) == expected


def test_sqlite_round_trip_and_upsert(tmp_path: Path) -> None:
    """A record is stored, read back and replaced."""
    memory = SqliteDomainMemory(path=tmp_path / "sub" / "m.sqlite3")
    assert memory.get(domain=DOMAIN) is None
    memory.save(record=record(tier=Tier.HTTP))
    assert memory.get(domain=DOMAIN) == record(tier=Tier.HTTP)
    memory.save(record=record(tier=Tier.BROWSER, failures=1))
    assert memory.get(domain=DOMAIN) == record(tier=Tier.BROWSER, failures=1)


def test_sqlite_persists_across_instances(tmp_path: Path) -> None:
    """A new instance on the same file sees the saved record."""
    path = tmp_path / "m.sqlite3"
    SqliteDomainMemory(path=path).save(record=record(tier=Tier.HTTP_PROXY))
    assert SqliteDomainMemory(path=path).get(domain=DOMAIN) == record(tier=Tier.HTTP_PROXY)


def test_domain_of() -> None:
    """The domain is the lowercase host name without the port."""
    assert domain_of(url="https://News.Example.TEST:8080/a?b=1") == "news.example.test"
    assert domain_of(url="not a url") == ""


def test_service_full_cycle_with_fake_clock(tmp_path: Path) -> None:
    """Learn, reuse, expire (probe), succeed cheaper, and demote after failures."""
    clock = FakeClock()
    service = DomainMemoryService(memory=SqliteDomainMemory(path=tmp_path / "m.sqlite3"), clock=clock, config=CONFIG)
    url = "http://example.test/page"
    ladder = (Tier.HTTP, Tier.BROWSER_STEALTH_PROXY)

    first = service.plan(url=url, min_tier=ladder[0], max_tier=ladder[1])
    assert first.start_tier == Tier.HTTP
    service.record(url=url, plan=first, outcome=Outcome.OK, tier_used=Tier.BROWSER)

    clock.advance(seconds=50)
    second = service.plan(url=url, min_tier=ladder[0], max_tier=ladder[1])
    assert (second.start_tier, second.is_probe) == (Tier.BROWSER, False)
    service.record(url=url, plan=second, outcome=Outcome.OK, tier_used=Tier.BROWSER)

    clock.advance(seconds=101)
    third = service.plan(url=url, min_tier=ladder[0], max_tier=ladder[1])
    assert (third.start_tier, third.is_probe) == (Tier.HTTP, True)
    sentence = service.record(url=url, plan=third, outcome=Outcome.OK, tier_used=Tier.HTTP)
    assert "now works at tier 1 (http)" in sentence

    fourth = service.plan(url=url, min_tier=ladder[0], max_tier=ladder[1])
    assert fourth.start_tier == Tier.HTTP
    for _ in range(2):
        service.record(url=url, plan=fourth, outcome=Outcome.BLOCKED, tier_used=Tier.HTTP)
    demoted = service.plan(url=url, min_tier=ladder[0], max_tier=ladder[1])
    assert demoted.start_tier == Tier.HTTP_PROXY
    assert "failed 2 times in a row" in demoted.reason


def test_service_ignores_url_without_host(tmp_path: Path) -> None:
    """A URL with no host is never stored."""
    service = DomainMemoryService(memory=SqliteDomainMemory(path=tmp_path / "m.sqlite3"), clock=FakeClock(), config=CONFIG)
    plan = service.plan(url="nohost", min_tier=Tier.HTTP, max_tier=Tier.BROWSER)
    assert plan.start_tier == Tier.HTTP
    assert "no host name" in service.record(url="nohost", plan=plan, outcome=Outcome.OK, tier_used=Tier.HTTP)
