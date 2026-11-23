"""Glue between the ladder and the memory storage: plan the start, then record the result."""

from collections.abc import Callable
from urllib.parse import urlparse

from robin_scraping_api.memory.base import DomainMemory, DomainRecord, MemoryConfig
from robin_scraping_api.memory.policy import (
    StartPlan,
    apply_result,
    choose_start,
    describe_update,
)
from robin_scraping_api.tiers.models import Outcome, Tier


def domain_of(*, url: str) -> str:
    """Return the lowercase host name of a URL, or an empty string."""
    return (urlparse(url).hostname or "").lower()


class DomainMemoryService:
    """Plan the start tier and record the outcome. The clock and the storage are injected."""

    def __init__(
        self,
        *,
        memory: DomainMemory,
        clock: Callable[[], float],
        config: MemoryConfig | None = None,
    ) -> None:
        """Store the storage, the clock (seconds) and the tuning."""
        self._memory: DomainMemory = memory
        self._clock: Callable[[], float] = clock
        self._config: MemoryConfig = config or MemoryConfig()

    def plan(self, *, url: str, min_tier: Tier, max_tier: Tier) -> StartPlan:
        """Read the record of the URL domain and choose the start tier. Reads storage."""
        domain: str = domain_of(url=url)
        record: DomainRecord | None = self._memory.get(domain=domain) if domain else None
        return choose_start(
            domain=domain,
            record=record,
            now=self._clock(),
            config=self._config,
            min_tier=min_tier,
            max_tier=max_tier,
        )

    def record(
        self, *, url: str, plan: StartPlan, outcome: Outcome, tier_used: Tier | None
    ) -> str:
        """Save what the run showed. Writes storage. Return a sentence for the process list."""
        domain: str = domain_of(url=url)
        if not domain:
            return "Memory: the URL has no host name, so nothing is saved."
        before: DomainRecord | None = self._memory.get(domain=domain)
        after: DomainRecord | None = apply_result(
            domain=domain,
            record=before,
            plan=plan,
            outcome=outcome,
            tier_used=tier_used,
            now=self._clock(),
        )
        if after is not None:
            self._memory.save(record=after)
        return describe_update(domain=domain, before=before, after=after)
