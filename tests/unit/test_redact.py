"""Tests for proxy credential redaction."""

import logging

import pytest
from factories import make_result

from robin_scraping_api.errors import TierFetchError
from robin_scraping_api.tiers.http import fetch_http
from robin_scraping_api.tiers.models import Tier, TierRequest
from robin_scraping_api.tiers.redact import redact_proxy


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("proxy http://user:pa55@proxy.example:8080 failed", "proxy http://***:***@proxy.example:8080 failed"),
        ("socks5://name:secret@10.0.0.1:1080", "socks5://***:***@10.0.0.1:1080"),
        ("no credentials http://proxy.example:8080", "no credentials http://proxy.example:8080"),
        ("plain text", "plain text"),
    ],
)
def test_url_credentials_are_masked(text: str, expected: str) -> None:
    """user:password in a URL is replaced."""
    assert redact_proxy(text=text) == expected


def test_listed_secret_is_masked_anywhere() -> None:
    """A secret that is not in a URL is replaced too."""
    assert redact_proxy(text="token abc123 used", secrets=["abc123"]) == "token *** used"


def test_http_tier_error_does_not_leak_proxy_credentials() -> None:
    """An error that echoes the proxy URL is redacted before it is raised."""

    def failing_get(url: str, **kwargs: object) -> object:
        raise ConnectionError(f"cannot reach {kwargs['proxy']}")

    from pydantic import SecretStr

    request = TierRequest(url="http://127.0.0.1/x", proxy=SecretStr("http://user:pa55@127.0.0.1:9"))
    with pytest.raises(TierFetchError) as caught:
        fetch_http(request=request, tier=Tier.HTTP_PROXY, get=failing_get)
    assert "pa55" not in str(caught.value)
    assert "pa55" not in caught.value.reason
    assert "***" in caught.value.reason


def test_secret_proxy_is_masked_in_repr() -> None:
    """The request repr never shows the proxy password."""
    from pydantic import SecretStr

    request = TierRequest(url="http://x", proxy=SecretStr("http://user:pa55@h:1"))
    assert "pa55" not in repr(request)
    assert "pa55" not in str(request.model_dump())


def test_ladder_trace_and_logs_do_not_leak_proxy(caplog: pytest.LogCaptureFixture) -> None:
    """Credentials in a tier error never reach the trace, the process lines or the logs."""
    from pydantic import SecretStr

    from robin_scraping_api.tiers.ladder import Ladder, LadderRequest
    from robin_scraping_api.tiers.models import Outcome

    secret_url = "http://user:pa55@127.0.0.1:9"

    def blocked(request: TierRequest) -> object:
        return make_result(html="", status=403)

    def leaking(request: TierRequest) -> object:
        raise TierFetchError(tier_label="http_proxy", reason=f"proxy {secret_url} refused")

    ladder = Ladder(
        runners={
            Tier.HTTP: blocked,
            Tier.HTTP_PROXY: leaking,
            Tier.BROWSER: leaking,
            Tier.BROWSER_STEALTH_PROXY: leaking,
        },
    )
    with caplog.at_level(logging.DEBUG):
        result = ladder.run(
            request=LadderRequest(url="http://127.0.0.1/x", proxy=SecretStr(secret_url), max_tier=Tier.BROWSER_STEALTH_PROXY)
        )
    everything = repr(result.model_dump()) + " ".join(result.process) + caplog.text
    assert "pa55" not in everything
    assert result.outcome == Outcome.ERROR
