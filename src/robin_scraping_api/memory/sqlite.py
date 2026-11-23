"""SQLite storage of domain records. This class is the data access layer of the memory."""

import sqlite3
from contextlib import closing
from pathlib import Path

from robin_scraping_api.memory.base import DomainRecord

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS domain_memory (
    domain TEXT PRIMARY KEY,
    tier INTEGER NOT NULL,
    last_success REAL NOT NULL,
    failure_count INTEGER NOT NULL,
    requests_since_probe INTEGER NOT NULL
)
"""


class SqliteDomainMemory:
    """Keep domain records in one SQLite file. Reads and writes have a storage side effect."""

    def __init__(self, *, path: Path) -> None:
        """Create the file and the table when they do not exist."""
        self._path: Path = path
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """Open a new connection. One connection per call keeps threads apart."""
        return sqlite3.connect(self._path, timeout=5)

    def get(self, *, domain: str) -> DomainRecord | None:
        """Return the record of the domain, or None."""
        with closing(self._connect()) as connection:
            row: tuple[str, int, float, int, int] | None = connection.execute(
                "SELECT domain, tier, last_success, failure_count, requests_since_probe "
                "FROM domain_memory WHERE domain = ?",
                (domain,),
            ).fetchone()
        if row is None:
            return None
        return DomainRecord(
            domain=row[0],
            tier=row[1],
            last_success=row[2],
            failure_count=row[3],
            requests_since_probe=row[4],
        )

    def save(self, *, record: DomainRecord) -> None:
        """Insert or replace the record of its domain."""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO domain_memory "
                "(domain, tier, last_success, failure_count, requests_since_probe) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(domain) DO UPDATE SET tier = excluded.tier, "
                "last_success = excluded.last_success, "
                "failure_count = excluded.failure_count, "
                "requests_since_probe = excluded.requests_since_probe",
                (
                    record.domain,
                    record.tier,
                    record.last_success,
                    record.failure_count,
                    record.requests_since_probe,
                ),
            )
