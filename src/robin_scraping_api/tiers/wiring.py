"""Build the default tier runners from settings. Wiring only, no logic."""

from robin_scraping_api.profile_locks import ProfileLockRegistry, profile_locks
from robin_scraping_api.tiers.alternates import fetch_alternates
from robin_scraping_api.tiers.browser import SessionFactory, fetch_browser
from robin_scraping_api.tiers.classify import ClassifyConfig, diagnose
from robin_scraping_api.tiers.http import HttpGet, fetch_http
from robin_scraping_api.tiers.ladder import Ladder, TierRunner
from robin_scraping_api.tiers.models import FetchResult, Outcome, Tier, TierRequest


def build_ladder(
    *,
    classify_config: ClassifyConfig,
    lock_timeout_seconds: float,
    locks: ProfileLockRegistry = profile_locks,
    get: HttpGet | None = None,
    session_factory: SessionFactory | None = None,
) -> Ladder:
    """Create a ladder whose tiers use the real fetchers, or the injected ones."""

    def accept(result: FetchResult) -> bool:
        """Accept an alternate copy only when it classifies as ok."""
        return diagnose(result=result, config=classify_config).outcome == Outcome.OK

    def http_runner(tier: Tier) -> TierRunner:
        """Return a runner that fetches over HTTP as the given tier."""
        return lambda request: fetch_http(request=request, tier=tier, get=get)

    def browser_runner(tier: Tier) -> TierRunner:
        """Return a runner that loads the page in the browser as the given tier."""
        return lambda request: fetch_browser(
            request=request,
            tier=tier,
            locks=locks,
            lock_timeout_seconds=lock_timeout_seconds,
            session_factory=session_factory,
        )

    def alternates_runner(request: TierRequest) -> FetchResult:
        """Fetch an alternate copy of the page."""
        return fetch_alternates(
            request=request, fetch_one=http_runner(Tier.ALTERNATES), accept=accept
        )

    return Ladder(
        runners={
            Tier.HTTP: http_runner(Tier.HTTP),
            Tier.ALTERNATES: alternates_runner,
            Tier.HTTP_PROXY: http_runner(Tier.HTTP_PROXY),
            Tier.BROWSER: browser_runner(Tier.BROWSER),
            Tier.BROWSER_STEALTH_PROXY: browser_runner(Tier.BROWSER_STEALTH_PROXY),
        },
        classify_config=classify_config,
    )
