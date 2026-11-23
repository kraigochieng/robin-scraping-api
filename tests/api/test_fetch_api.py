"""API tests: FastAPI TestClient with a fake ladder, plus a few runs over the fixture server."""

import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from factories import make_result, page, words
from fastapi.testclient import TestClient
from fixture_server import FixtureServer

from robin_scraping_api.errors import TierFetchError
from robin_scraping_api.main import app
from robin_scraping_api.routers.fetch import get_ladder
from robin_scraping_api.services import fetch as fetch_service
from robin_scraping_api.settings import settings
from robin_scraping_api.tiers.classify import ClassifyConfig
from robin_scraping_api.tiers.ladder import LadderRequest, LadderResult
from robin_scraping_api.tiers.models import Attempt, Outcome, Tier
from robin_scraping_api.tiers.wiring import build_ladder

ARTICLE: str = page(body=f"<nav>Menu</nav><main><h1>Title</h1><p>{words(count=120)}</p></main><footer>Foot</footer>")
OLD_FIELDS: set[str] = {"url", "status_code", "status_message", "profile", "clean", "format", "content"}
NEW_FIELDS: set[str] = {"tier_used", "outcome", "process", "attempts"}


class FakeLadder:
    """A ladder that returns a fixed result and records the requests."""

    def __init__(self, *, result: LadderResult) -> None:
        """Store the result."""
        self.result = result
        self.requests: list[LadderRequest] = []

    def run(self, *, request: LadderRequest) -> LadderResult:
        """Record the request and return the fixed result."""
        self.requests.append(request)
        return self.result


def ok_result(*, html: str = ARTICLE, tier: Tier = Tier.HTTP) -> LadderResult:
    """Build a LadderResult that holds a good page."""
    return LadderResult(
        final=make_result(html=html, tier=tier),
        outcome=Outcome.OK,
        attempts=[Attempt(tier=int(tier), tier_name=tier.label, outcome=Outcome.OK, reason="fine", ms=5, status=200)],
        process=[f"Tried tier {int(tier)} ({tier.label}) in 5 ms and got status 200. Diagnosis: ok, because fine.", "Stopped at tier 1 (http): the content is good."],
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A test client, with dependency overrides cleared afterwards."""
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(*, ladder: object) -> None:
    """Replace the ladder of the app."""
    app.dependency_overrides[get_ladder] = lambda: ladder


def test_response_keeps_old_fields_and_adds_new_ones(client: TestClient) -> None:
    """Old fields keep their names and types. New fields are additive."""
    use(ladder=FakeLadder(result=ok_result()))
    body = client.get("/fetch", params={"url": "http://127.0.0.1/page"}).json()
    assert OLD_FIELDS <= set(body)
    assert set(body) == OLD_FIELDS | NEW_FIELDS
    assert body["status_code"] == 200 and body["status_message"] == "OK"
    assert body["profile"] is None and body["clean"] is True and body["format"] == "markdown"
    assert body["tier_used"] == 1 and body["outcome"] == "ok"


def test_process_is_always_present_and_human_readable(client: TestClient) -> None:
    """The process list has plain sentences even without debug."""
    use(ladder=FakeLadder(result=ok_result()))
    body = client.get("/fetch", params={"url": "http://127.0.0.1/page"}).json()
    assert body["attempts"] is None
    assert body["process"][0].startswith("Memory: no record for 127.0.0.1")
    assert body["process"][1].startswith("Tried tier 1 (http)")


def test_debug_adds_attempts(client: TestClient) -> None:
    """debug=true adds the attempts list."""
    use(ladder=FakeLadder(result=ok_result()))
    body = client.get("/fetch", params={"url": "http://127.0.0.1/page", "debug": "true"}).json()
    assert body["attempts"] == [{"tier": 1, "tier_name": "http", "outcome": "ok", "reason": "fine", "ms": 5, "status": 200}]


def test_default_content_is_main_text_without_nav(client: TestClient) -> None:
    """clean=true returns the article text without navigation and footer."""
    use(ladder=FakeLadder(result=ok_result()))
    content = client.get("/fetch", params={"url": "http://127.0.0.1/page"}).json()["content"]
    assert "word word" in content and "Menu" not in content and "Foot" not in content


def test_clean_false_keeps_full_body(client: TestClient) -> None:
    """clean=false returns the whole body, navigation included."""
    use(ladder=FakeLadder(result=ok_result()))
    content = client.get("/fetch", params={"url": "http://127.0.0.1/page", "clean": "false", "format": "text"}).json()["content"]
    assert "Menu" in content and "Foot" in content


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"url": "http://x", "min_tier": 0},
        {"url": "http://x", "min_tier": 6},
        {"url": "http://x", "max_tier": 0},
        {"url": "http://x", "max_tier": "abc"},
        {"url": "http://x", "format": "pdf"},
        {"url": "http://x", "debug": "maybe"},
        {"url": "http://x", "min_tier": 4, "max_tier": 2},
    ],
)
def test_invalid_parameters_give_422(client: TestClient, params: dict[str, object]) -> None:
    """Bad parameters are rejected before the ladder runs."""
    fake = FakeLadder(result=ok_result())
    use(ladder=fake)
    assert client.get("/fetch", params=params).status_code == 422
    assert fake.requests == []


def test_tier_limits_and_proxy_reach_the_ladder(client: TestClient) -> None:
    """min_tier, max_tier and proxy are passed to the ladder. The proxy stays secret."""
    fake = FakeLadder(result=ok_result())
    use(ladder=fake)
    client.get("/fetch", params={"url": "http://127.0.0.1/p", "min_tier": 2, "max_tier": 4, "proxy": "http://u:pw@127.0.0.1:9"})
    request = fake.requests[0]
    assert (request.min_tier, request.max_tier) == (Tier.ALTERNATES, Tier.BROWSER)
    assert request.proxy is not None and request.proxy.get_secret_value() == "http://u:pw@127.0.0.1:9"
    assert "pw" not in repr(request)


def test_env_proxy_is_used_when_no_param(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """SCRAPING_PROXY is the default proxy."""
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "scraping_proxy", SecretStr("http://env:1"))
    fake = FakeLadder(result=ok_result())
    use(ladder=fake)
    client.get("/fetch", params={"url": "http://127.0.0.1/p"})
    assert fake.requests[0].proxy is not None and fake.requests[0].proxy.get_secret_value() == "http://env:1"


def test_missing_profile_is_404(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile that does not exist gives 404 and the ladder does not run."""
    monkeypatch.setattr(fetch_service, "PROFILES_DIR", tmp_path)
    fake = FakeLadder(result=ok_result())
    use(ladder=fake)
    response = client.get("/fetch", params={"url": "http://127.0.0.1/p", "profile_name": "nope"})
    assert response.status_code == 404
    assert fake.requests == []


def test_existing_profile_path_is_passed(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An existing profile is passed to the ladder as a path and echoed in the response."""
    (tmp_path / "alice").mkdir()
    monkeypatch.setattr(fetch_service, "PROFILES_DIR", tmp_path)
    fake = FakeLadder(result=ok_result())
    use(ladder=fake)
    body = client.get("/fetch", params={"url": "http://127.0.0.1/p", "profile_name": "alice"}).json()
    assert fake.requests[0].profile_path == str(tmp_path / "alice")
    assert body["profile"] == "alice"


def test_all_tiers_failed_is_502_with_process(client: TestClient) -> None:
    """When no tier answered, the API returns 502 with the process lines."""
    failure = LadderResult(final=None, outcome=Outcome.ERROR, attempts=[], process=["Tried tier 1 (http) in 1 ms and got no response."])
    use(ladder=FakeLadder(result=failure))
    response = client.get("/fetch", params={"url": "http://127.0.0.1/p"})
    assert response.status_code == 502
    process = response.json()["detail"]["process"]
    assert failure.process[0] in process


def test_last_failure_is_returned_with_its_outcome(client: TestClient) -> None:
    """A blocked final result is returned with status 200 envelope fields and outcome blocked."""
    blocked = LadderResult(
        final=make_result(html=page(body='<div id="cf-chl-widget"></div>'), status=403),
        outcome=Outcome.BLOCKED,
        attempts=[],
        process=["x"],
    )
    use(ladder=FakeLadder(result=blocked))
    body = client.get("/fetch", params={"url": "http://127.0.0.1/p"}).json()
    assert body["status_code"] == 403 and body["status_message"] == "Forbidden"
    assert body["outcome"] == "blocked"


@pytest.fixture
def locked_profile_ladder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real ladder: tier 1 sees a login wall, tier 4 is a slow fake browser that holds the profile lock."""
    (tmp_path / "busy").mkdir()
    monkeypatch.setattr(fetch_service, "PROFILES_DIR", tmp_path)
    monkeypatch.setattr(settings, "profile_lock_timeout_seconds", 0.3)
    release = threading.Event()
    entered = threading.Event()

    def login_get(url: str, **kwargs: object) -> object:
        return SimpleNamespace(
            status=200, headers={}, url=url, encoding="utf-8",
            body=page(body="<p>Sign in to continue reading.</p>").encode(),
        )

    class SlowSession:
        def __init__(self, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "SlowSession":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def fetch(self, url: str, **kwargs: object) -> object:
            entered.set()
            release.wait(timeout=5)
            return SimpleNamespace(status=200, headers={}, url=url, encoding="utf-8", body=ARTICLE.encode())

    ladder = build_ladder(
        classify_config=ClassifyConfig(), lock_timeout_seconds=0.3, get=login_get, session_factory=SlowSession
    )
    return ladder, entered, release


def test_same_profile_second_request_gets_409(client: TestClient, locked_profile_ladder) -> None:
    """While one request holds the profile in the browser, a second one waits, then gets 409."""
    ladder, entered, release = locked_profile_ladder
    use(ladder=ladder)
    params = {"url": "http://127.0.0.1/p", "profile_name": "busy"}
    first: list[int] = []
    worker = threading.Thread(target=lambda: first.append(client.get("/fetch", params=params).status_code))
    worker.start()
    assert entered.wait(timeout=5)

    second = client.get("/fetch", params=params)
    release.set()
    worker.join()

    assert second.status_code == 409
    assert second.headers["Retry-After"] == "0"
    assert first == [200]


def test_different_profiles_do_not_block(client: TestClient, locked_profile_ladder, tmp_path: Path) -> None:
    """A request for another profile is not blocked by the busy one."""
    ladder, entered, release = locked_profile_ladder
    (tmp_path / "other").mkdir()
    use(ladder=ladder)
    worker = threading.Thread(target=lambda: client.get("/fetch", params={"url": "http://127.0.0.1/p", "profile_name": "busy"}))
    worker.start()
    assert entered.wait(timeout=5)
    release.set()
    response = client.get("/fetch", params={"url": "http://127.0.0.1/p", "profile_name": "other"})
    worker.join()
    assert response.status_code == 200


def test_end_to_end_over_fixture_server(client: TestClient, fixture_server: FixtureServer) -> None:
    """The default ladder returns a static article from tier 1 with one request."""
    use(ladder=build_ladder(classify_config=ClassifyConfig(), lock_timeout_seconds=1))
    body = client.get("/fetch", params={"url": fixture_server.base_url + "/article/jsonld", "debug": "true"}).json()
    assert body["tier_used"] == 1 and body["outcome"] == "ok"
    assert "reopened on Monday" in body["content"]
    assert "Home" not in body["content"]
    assert fixture_server.total_hits() == 1
    assert len(body["attempts"]) == 1


def test_end_to_end_alternate_process_text(client: TestClient, fixture_server: FixtureServer) -> None:
    """The process field tells the story of a thin page completed by an AMP copy."""
    use(ladder=build_ladder(classify_config=ClassifyConfig(), lock_timeout_seconds=1))
    body = client.get("/fetch", params={"url": fixture_server.base_url + "/amp-source/story", "max_tier": 3}).json()
    assert body["tier_used"] == 2
    assert any("Moving from tier 1 (http) to tier 2 (alternates)" in line for line in body["process"])
