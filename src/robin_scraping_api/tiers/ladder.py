"""The escalation ladder: run tiers cheapest first and move by diagnosis."""

import time
from collections.abc import Callable, Mapping

from pydantic import BaseModel, ConfigDict, SecretStr

from robin_scraping_api.errors import TierFetchError
from robin_scraping_api.tiers.alternates import discover_alternates
from robin_scraping_api.tiers.classify import ClassifyConfig, Diagnosis, diagnose
from robin_scraping_api.tiers.models import (
    Attempt,
    FetchResult,
    Outcome,
    Tier,
    TierRequest,
)
from robin_scraping_api.tiers.narrative import (
    narrate_attempt,
    narrate_decision,
    narrate_skips,
)
from robin_scraping_api.tiers.redact import redact_proxy

TierRunner = Callable[[TierRequest], FetchResult]

PREFERRED_TARGETS: dict[Outcome, tuple[Tier, ...]] = {
    Outcome.NEEDS_JS: (Tier.BROWSER,),
    Outcome.BLOCKED: (Tier.HTTP_PROXY, Tier.BROWSER_STEALTH_PROXY),
    Outcome.LOGIN_WALL: (Tier.BROWSER,),
    Outcome.THIN: (Tier.ALTERNATES, Tier.BROWSER),
}


class LadderRequest(BaseModel):
    """The input of one ladder run."""

    model_config = ConfigDict(frozen=True)

    url: str
    min_tier: Tier = Tier.HTTP
    max_tier: Tier = Tier.BROWSER_STEALTH_PROXY
    proxy: SecretStr | None = None
    profile_path: str | None = None
    expected_title: str | None = None
    timeout_seconds: float = 30.0


class LadderResult(BaseModel):
    """The result of a ladder run. The trace is always present."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    final: FetchResult | None
    outcome: Outcome
    attempts: list[Attempt]
    process: list[str]

    @property
    def tier_used(self) -> Tier | None:
        """Return the tier of the final result, or None when no tier answered."""
        return self.final.tier if self.final else None


def _is_usable(
    *, tier: Tier, has_proxy: bool, has_profile: bool, has_alternate_hints: bool
) -> bool:
    """Return True when the tier has what it needs to run."""
    if tier == Tier.ALTERNATES:
        return has_alternate_hints
    if tier == Tier.HTTP_PROXY:
        return has_proxy
    return True


def first_tier(
    *, min_tier: Tier, max_tier: Tier, has_proxy: bool, has_profile: bool
) -> Tier | None:
    """Return the cheapest usable tier inside the allowed range. Pure."""
    for tier in Tier:
        if min_tier <= tier <= max_tier and _is_usable(
            tier=tier,
            has_proxy=has_proxy,
            has_profile=has_profile,
            has_alternate_hints=False,
        ):
            return tier
    return None


def next_tier(
    *,
    outcome: Outcome,
    current: Tier,
    visited: frozenset[Tier],
    has_proxy: bool,
    has_profile: bool,
    has_alternate_hints: bool,
    min_tier: Tier,
    max_tier: Tier,
) -> Tier | None:
    """Return the tier to try after an outcome, or None to stop. Pure.

    A tier never runs twice, so the number of attempts never exceeds the number of tiers.
    """
    if outcome == Outcome.OK:
        return None
    if outcome == Outcome.ERROR:
        preferred: tuple[Tier, ...] = tuple(tier for tier in Tier if tier > current)
    else:
        preferred = PREFERRED_TARGETS[outcome]
    for tier in preferred:
        if tier in visited or not min_tier <= tier <= max_tier:
            continue
        if outcome == Outcome.LOGIN_WALL and not has_profile:
            continue
        if _is_usable(
            tier=tier,
            has_proxy=has_proxy,
            has_profile=has_profile,
            has_alternate_hints=has_alternate_hints,
        ):
            return tier
    return None


class Ladder:
    """Run tiers in order of diagnosis. Running has side effects through the tier runners."""

    def __init__(
        self,
        *,
        runners: Mapping[Tier, TierRunner],
        classify_config: ClassifyConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Store the runner of each tier, the thresholds and the clock."""
        self._runners: Mapping[Tier, TierRunner] = runners
        self._classify_config: ClassifyConfig = classify_config or ClassifyConfig()
        self._clock: Callable[[], float] = clock

    def run(self, *, request: LadderRequest) -> LadderResult:
        """Run the ladder for one URL and return the last result with a full trace."""
        has_proxy: bool = request.proxy is not None
        has_profile: bool = request.profile_path is not None
        secrets: list[str] = [request.proxy.get_secret_value()] if request.proxy else []

        visited: set[Tier] = set()
        attempts: list[Attempt] = []
        process: list[str] = []
        hint_html: str | None = None
        last_result: FetchResult | None = None
        previous_outcome: Outcome | None = None
        outcome: Outcome = Outcome.ERROR

        tier: Tier | None = first_tier(
            min_tier=request.min_tier,
            max_tier=request.max_tier,
            has_proxy=has_proxy,
            has_profile=has_profile,
        )
        if tier is None:
            process.append("No tier is allowed by min_tier, max_tier and the proxy setting.")

        while tier is not None:
            visited.add(tier)
            tier_request: TierRequest = TierRequest(
                url=request.url,
                proxy=request.proxy if tier in (Tier.HTTP_PROXY, Tier.BROWSER_STEALTH_PROXY) else None,
                profile_path=request.profile_path if tier in (Tier.BROWSER, Tier.BROWSER_STEALTH_PROXY) else None,
                hint_html=hint_html,
                wait_for_network_idle=tier == Tier.BROWSER and previous_outcome == Outcome.NEEDS_JS,
                timeout_seconds=request.timeout_seconds,
            )
            started: float = self._clock()
            result: FetchResult | None = None
            try:
                result = self._runners[tier](tier_request)
                diagnosis: Diagnosis = diagnose(
                    result=result,
                    expected_title=request.expected_title,
                    config=self._classify_config,
                )
            except TierFetchError as error:
                diagnosis = Diagnosis(
                    outcome=Outcome.ERROR,
                    reason=redact_proxy(text=error.reason, secrets=secrets),
                )
            elapsed_ms: int = result.elapsed_ms if result else int((self._clock() - started) * 1000)

            outcome = diagnosis.outcome
            attempts.append(
                Attempt(
                    tier=int(tier),
                    tier_name=tier.label,
                    outcome=outcome,
                    reason=diagnosis.reason,
                    ms=elapsed_ms,
                    status=result.status if result else None,
                )
            )
            process.append(
                redact_proxy(
                    text=narrate_attempt(
                        tier=tier,
                        status=result.status if result else None,
                        elapsed_ms=elapsed_ms,
                        outcome=outcome,
                        reason=diagnosis.reason,
                    ),
                    secrets=secrets,
                )
            )
            if result is not None:
                last_result = result
                if result.html:
                    hint_html = result.html

            has_hints: bool = bool(hint_html) and bool(
                discover_alternates(html=hint_html or "", url=request.url)
            )
            chosen: Tier | None = next_tier(
                outcome=outcome,
                current=tier,
                visited=frozenset(visited),
                has_proxy=has_proxy,
                has_profile=has_profile,
                has_alternate_hints=has_hints,
                min_tier=request.min_tier,
                max_tier=request.max_tier,
            )
            process.extend(
                narrate_skips(
                    outcome=outcome,
                    has_proxy=has_proxy,
                    has_profile=has_profile,
                    has_alternate_hints=has_hints,
                )
            )
            process.append(narrate_decision(outcome=outcome, current=tier, next_tier=chosen))
            previous_outcome = outcome
            tier = chosen

        return LadderResult(
            final=last_result, outcome=outcome, attempts=attempts, process=process
        )
