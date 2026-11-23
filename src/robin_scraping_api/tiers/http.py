"""Tiers 1 and 3: plain HTTP fetch with Chrome impersonation, with or without a proxy."""

import time
from collections.abc import Callable

from scrapling.fetchers import Fetcher

from robin_scraping_api.errors import TierFetchError
from robin_scraping_api.tiers.models import FetchResult, Tier, TierRequest
from robin_scraping_api.tiers.redact import redact_proxy

HttpGet = Callable[..., object]


def fetch_http(
    *,
    request: TierRequest,
    tier: Tier,
    get: HttpGet | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FetchResult:
    """Fetch the URL over HTTP. Has a network side effect. Raises TierFetchError."""
    proxy_value: str | None = request.proxy.get_secret_value() if request.proxy else None
    send: HttpGet = get or Fetcher.get
    started: float = clock()
    try:
        response = send(
            request.url,
            impersonate="chrome",
            follow_redirects=True,
            retries=1,
            timeout=request.timeout_seconds,
            **({"proxy": proxy_value} if proxy_value else {}),
        )
    except Exception as error:  # noqa: BLE001 - library errors vary; converted at the boundary
        raise TierFetchError(
            tier_label=tier.label,
            reason=redact_proxy(
                text=f"{type(error).__name__}: {error}",
                secrets=[proxy_value] if proxy_value else None,
            ),
        ) from error
    elapsed_ms: int = int((clock() - started) * 1000)
    encoding: str = getattr(response, "encoding", None) or "utf-8"
    return FetchResult(
        status=int(getattr(response, "status")),
        headers={str(key): str(value) for key, value in dict(getattr(response, "headers", {})).items()},
        html=bytes(getattr(response, "body")).decode(encoding, errors="replace"),
        final_url=str(getattr(response, "url", request.url)),
        tier=tier,
        elapsed_ms=elapsed_ms,
    )
