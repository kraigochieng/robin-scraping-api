"""Pure rules of the domain memory: where to start, and what to remember. No input or output."""

from pydantic import BaseModel, ConfigDict

from robin_scraping_api.memory.base import DomainRecord, MemoryConfig
from robin_scraping_api.tiers.models import Outcome, Tier
from robin_scraping_api.tiers.narrative import describe_tier


class StartPlan(BaseModel):
    """The tier to start at, whether this run is a probe, and the reason in plain words."""

    model_config = ConfigDict(frozen=True)

    start_tier: Tier
    is_probe: bool
    reason: str


def choose_start(
    *,
    domain: str,
    record: DomainRecord | None,
    now: float,
    config: MemoryConfig,
    min_tier: Tier,
    max_tier: Tier,
) -> StartPlan:
    """Return where the ladder starts. The request min_tier is a floor, max_tier a cap."""
    if record is None:
        return StartPlan(
            start_tier=min_tier,
            is_probe=False,
            reason=f"Memory: no record for {domain} yet, so the ladder starts at {describe_tier(tier=min_tier)}.",
        )

    remembered: Tier = Tier(record.tier)
    probe_reason: str | None = None
    base: Tier = remembered
    reason: str = f"Memory: {domain} worked at {describe_tier(tier=remembered)} last time, so the ladder starts there."

    if record.failure_count >= config.failure_threshold:
        demoted: int = int(remembered) + 1
        if demoted == int(Tier.ALTERNATES):
            demoted += 1
        base = Tier(min(demoted, int(Tier.BROWSER_STEALTH_PROXY)))
        reason = (
            f"Memory: {describe_tier(tier=remembered)} failed {record.failure_count} times in a row for {domain}, "
            f"so the ladder starts at {describe_tier(tier=base)}."
        )
    elif remembered > min_tier and now - record.last_success > config.ttl_seconds:
        probe_reason = (
            f"Memory: the record for {domain} is older than {config.ttl_seconds:g} seconds, "
            f"so the ladder probes cheaper tiers and starts at {describe_tier(tier=min_tier)}."
        )
    elif remembered > min_tier and record.requests_since_probe >= config.probe_every:
        probe_reason = (
            f"Memory: {record.requests_since_probe} requests passed for {domain} without a probe, "
            f"so the ladder probes cheaper tiers and starts at {describe_tier(tier=min_tier)}."
        )

    if probe_reason is not None:
        return StartPlan(start_tier=min_tier, is_probe=True, reason=probe_reason)

    if base == Tier.ALTERNATES:
        base = Tier.HTTP
        reason += " Tier 2 needs the page from tier 1, so tier 1 runs first."

    start: Tier = min(max(base, min_tier), max_tier)
    return StartPlan(start_tier=start, is_probe=False, reason=reason)


def apply_result(
    *,
    domain: str,
    record: DomainRecord | None,
    plan: StartPlan,
    outcome: Outcome,
    tier_used: Tier | None,
    now: float,
) -> DomainRecord | None:
    """Return the record to save after a run, or None when there is nothing to save."""
    since_probe: int = 0 if plan.is_probe else (record.requests_since_probe + 1 if record else 0)
    if outcome == Outcome.OK and tier_used is not None:
        return DomainRecord(
            domain=domain,
            tier=int(tier_used),
            last_success=now,
            failure_count=0,
            requests_since_probe=since_probe,
        )
    if record is None:
        return None
    return record.model_copy(
        update={"failure_count": record.failure_count + 1, "requests_since_probe": since_probe}
    )


def describe_update(*, domain: str, before: DomainRecord | None, after: DomainRecord | None) -> str:
    """Return one sentence that tells what the memory now holds for the domain."""
    if after is None:
        return f"Memory: nothing saved for {domain}, because no tier gave good content."
    if after.failure_count > 0:
        return (
            f"Memory: no tier gave good content for {domain}. "
            f"The failure count is now {after.failure_count}."
        )
    if before is not None and before.tier != after.tier:
        return (
            f"Memory: {domain} now works at {describe_tier(tier=Tier(after.tier))}, "
            f"before it was {describe_tier(tier=Tier(before.tier))}."
        )
    return f"Memory: saved {describe_tier(tier=Tier(after.tier))} for {domain}."
