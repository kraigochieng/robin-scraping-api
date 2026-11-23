"""Types of the domain memory: the stored record, the storage interface, the tuning."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class DomainRecord(BaseModel):
    """What the memory knows about one domain."""

    model_config = ConfigDict(frozen=True)

    domain: str
    tier: int
    last_success: float
    failure_count: int = 0
    requests_since_probe: int = 0


class MemoryConfig(BaseModel):
    """Tuning of the memory policy."""

    model_config = ConfigDict(frozen=True)

    ttl_seconds: float = 24 * 3600
    probe_every: int = 20
    failure_threshold: int = 3


class DomainMemory(Protocol):
    """Storage of domain records. A SQLite class is the default; others can replace it."""

    def get(self, *, domain: str) -> DomainRecord | None:
        """Return the record of the domain, or None."""
        ...

    def save(self, *, record: DomainRecord) -> None:
        """Insert or replace the record of its domain."""
        ...
