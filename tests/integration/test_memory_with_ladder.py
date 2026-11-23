"""Integration: the memory makes the second request skip tiers that failed the first time."""

from pathlib import Path

from fastapi.testclient import TestClient
from fixture_server import FixtureServer
from unit.test_memory import CONFIG, FakeClock

from robin_scraping_api.main import app
from robin_scraping_api.memory.service import DomainMemoryService
from robin_scraping_api.memory.sqlite import SqliteDomainMemory
from robin_scraping_api.routers.fetch import get_ladder, get_memory_service
from robin_scraping_api.tiers.classify import ClassifyConfig
from robin_scraping_api.tiers.wiring import build_ladder


def test_second_request_starts_at_remembered_tier_then_probes(tmp_path: Path, fixture_server: FixtureServer) -> None:
    """Request 1 learns tier 3. Request 2 skips tier 1. After the TTL, request 3 probes tier 1 again."""
    clock = FakeClock()
    app.dependency_overrides[get_ladder] = lambda: build_ladder(classify_config=ClassifyConfig(), lock_timeout_seconds=1)
    app.dependency_overrides[get_memory_service] = lambda: DomainMemoryService(
        memory=SqliteDomainMemory(path=tmp_path / "m.sqlite3"), clock=clock, config=CONFIG
    )
    client = TestClient(app)
    params = {"url": fixture_server.base_url + "/needs-proxy", "proxy": fixture_server.base_url, "max_tier": 3}
    try:
        first = client.get("/fetch", params=params).json()
        assert first["tier_used"] == 3
        assert fixture_server.hits["/needs-proxy"] == 2
        assert fixture_server.proxied_hits["/needs-proxy"] == 1

        clock.advance(seconds=10)
        second = client.get("/fetch", params=params).json()
        assert second["tier_used"] == 3
        assert fixture_server.hits["/needs-proxy"] == 3
        assert fixture_server.proxied_hits["/needs-proxy"] == 2
        assert any("worked at tier 3 (http_proxy) last time" in line for line in second["process"])

        clock.advance(seconds=500)
        third = client.get("/fetch", params=params).json()
        assert fixture_server.hits["/needs-proxy"] == 5
        assert any("probes cheaper tiers" in line for line in third["process"])
        assert third["tier_used"] == 3
    finally:
        app.dependency_overrides.clear()
