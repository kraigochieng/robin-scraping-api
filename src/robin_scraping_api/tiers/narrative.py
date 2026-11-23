"""Plain-English sentences that tell a person how the ladder moved. Pure."""

from robin_scraping_api.tiers.models import Outcome, Tier

WHY_MOVE: dict[Outcome, str] = {
    Outcome.OK: "the content is good",
    Outcome.NEEDS_JS: "the page needs JavaScript to show its content",
    Outcome.BLOCKED: "the site blocked the plain request",
    Outcome.LOGIN_WALL: "the page needs a login, and a saved profile can supply it",
    Outcome.THIN: "the page has too little content, so a copy or a browser may have more",
    Outcome.ERROR: "the tier failed to fetch the page",
}


def describe_tier(*, tier: Tier) -> str:
    """Return the tier as 'tier 1 (http)'."""
    return f"tier {int(tier)} ({tier.label})"


def narrate_attempt(
    *, tier: Tier, status: int | None, elapsed_ms: int, outcome: Outcome, reason: str
) -> str:
    """Describe one attempt: what the tier did and what the diagnosis was."""
    got: str = f"got status {status}" if status is not None else "got no response"
    return (
        f"Tried {describe_tier(tier=tier)} in {elapsed_ms} ms and {got}. "
        f"Diagnosis: {outcome.value}, because {reason}."
    )


def narrate_skips(
    *, outcome: Outcome, has_proxy: bool, has_profile: bool, has_alternate_hints: bool
) -> list[str]:
    """List the tiers that this outcome would use but that cannot run, with the reason."""
    skips: list[str] = []
    if outcome == Outcome.BLOCKED and not has_proxy:
        skips.append(f"Skipped {describe_tier(tier=Tier.HTTP_PROXY)}: no proxy is set.")
    if outcome == Outcome.LOGIN_WALL and not has_profile:
        skips.append(
            f"Skipped {describe_tier(tier=Tier.BROWSER)}: no profile_name was given, so there is no saved login."
        )
    if outcome == Outcome.THIN and not has_alternate_hints:
        skips.append(
            f"Skipped {describe_tier(tier=Tier.ALTERNATES)}: the page does not point to an AMP, feed, API or print copy."
        )
    return skips


def narrate_decision(*, outcome: Outcome, current: Tier, next_tier: Tier | None) -> str:
    """Describe whether the ladder stops or moves, and why."""
    if outcome == Outcome.OK:
        return f"Stopped at {describe_tier(tier=current)}: the content is good."
    if next_tier is None:
        return (
            f"Stopped: no other allowed tier can help with {outcome.value}. "
            "The last result is returned."
        )
    return (
        f"Moving from {describe_tier(tier=current)} to {describe_tier(tier=next_tier)} "
        f"because {WHY_MOVE[outcome]}."
    )
