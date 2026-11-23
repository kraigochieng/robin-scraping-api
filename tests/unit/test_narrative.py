"""Tests for the plain-English process sentences."""

from robin_scraping_api.tiers.models import Outcome, Tier
from robin_scraping_api.tiers.narrative import (
    narrate_attempt,
    narrate_decision,
    narrate_skips,
)


def test_attempt_sentence() -> None:
    """The attempt sentence names tier, time, status and diagnosis."""
    assert narrate_attempt(
        tier=Tier.HTTP, status=403, elapsed_ms=120, outcome=Outcome.BLOCKED, reason="status 403 blocks the request"
    ) == "Tried tier 1 (http) in 120 ms and got status 403. Diagnosis: blocked, because status 403 blocks the request."


def test_attempt_without_response() -> None:
    """A tier that raised says it got no response."""
    assert "got no response" in narrate_attempt(tier=Tier.BROWSER, status=None, elapsed_ms=1, outcome=Outcome.ERROR, reason="x")


def test_decision_sentences() -> None:
    """Stop and move sentences."""
    assert narrate_decision(outcome=Outcome.OK, current=Tier.HTTP, next_tier=None) == "Stopped at tier 1 (http): the content is good."
    assert narrate_decision(outcome=Outcome.NEEDS_JS, current=Tier.HTTP, next_tier=Tier.BROWSER) == (
        "Moving from tier 1 (http) to tier 4 (browser) because the page needs JavaScript to show its content."
    )
    assert "no other allowed tier can help with blocked" in narrate_decision(outcome=Outcome.BLOCKED, current=Tier.HTTP, next_tier=None)


def test_skip_sentences() -> None:
    """Each unusable tier has a reason."""
    assert narrate_skips(outcome=Outcome.BLOCKED, has_proxy=False, has_profile=False, has_alternate_hints=False) == [
        "Skipped tier 3 (http_proxy): no proxy is set."
    ]
    assert narrate_skips(outcome=Outcome.LOGIN_WALL, has_proxy=False, has_profile=False, has_alternate_hints=False)
    assert narrate_skips(outcome=Outcome.THIN, has_proxy=False, has_profile=False, has_alternate_hints=False)
    assert narrate_skips(outcome=Outcome.THIN, has_proxy=False, has_profile=False, has_alternate_hints=True) == []
