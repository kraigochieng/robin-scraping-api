"""Data types shared by the tiers: tiers, outcomes, fetch results, requests."""

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, SecretStr


class Tier(IntEnum):
    """The five fetch tiers, cheapest first."""

    HTTP = 1
    ALTERNATES = 2
    HTTP_PROXY = 3
    BROWSER = 4
    BROWSER_STEALTH_PROXY = 5

    @property
    def label(self) -> str:
        """Return the lowercase name used in traces and messages."""
        return self.name.lower()


class Outcome(StrEnum):
    """The diagnosis of one fetch result."""

    OK = "ok"
    NEEDS_JS = "needs_js"
    BLOCKED = "blocked"
    LOGIN_WALL = "login_wall"
    THIN = "thin"
    ERROR = "error"


class ApiCandidate(BaseModel):
    """A JSON response seen in the browser whose body holds the page title or first sentence."""

    model_config = ConfigDict(frozen=True)

    url: str
    status: int
    matched_on: list[str]
    size_bytes: int


class Attempt(BaseModel):
    """One tier run, as shown in the debug trace."""

    model_config = ConfigDict(frozen=True)

    tier: int
    tier_name: str
    outcome: Outcome
    reason: str
    ms: int
    status: int | None = None
    api_candidates: list[ApiCandidate] = []


@dataclass(frozen=True)
class FetchResult:
    """The raw result of one tier fetch."""

    status: int
    headers: dict[str, str]
    html: str
    final_url: str
    tier: Tier
    elapsed_ms: int
    extra: dict[str, str] = field(default_factory=dict)
    api_candidates: tuple[ApiCandidate, ...] = ()


class TierRequest(BaseModel):
    """What a tier needs to run one fetch."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    url: str
    proxy: SecretStr | None = None
    profile_path: str | None = None
    hint_html: str | None = None
    wait_for_network_idle: bool = False
    timeout_seconds: float = 30.0
