"""Tiers 4 and 5: the stealth browser, with an optional saved profile and proxy."""

import time
from collections.abc import Callable

from scrapling.fetchers import StealthySession

from robin_scraping_api.errors import ProfileBusyError, TierFetchError
from robin_scraping_api.profile_locks import ProfileLockRegistry
from robin_scraping_api.tiers.models import FetchResult, Tier, TierRequest
from robin_scraping_api.tiers.redact import redact_proxy

SessionFactory = Callable[..., object]


def fetch_browser(
    *,
    request: TierRequest,
    tier: Tier,
    locks: ProfileLockRegistry,
    lock_timeout_seconds: float,
    session_factory: SessionFactory | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FetchResult:
    """Load the page in a stealth browser. Has side effects (process, network, profile files).

    Tier 4 is headless. Tier 5 is headful. Images, fonts and media are not loaded.
    The browser waits for network idle only when the request asks for it.
    A profile is locked for the whole session. Raises ProfileBusyError or TierFetchError.
    """
    proxy_value: str | None = request.proxy.get_secret_value() if request.proxy else None
    session_arguments: dict[str, object] = {
        "headless": tier != Tier.BROWSER_STEALTH_PROXY,
        "disable_resources": True,
        "timeout": int(request.timeout_seconds * 1000),
    }
    if proxy_value:
        session_arguments["proxy"] = proxy_value
    if request.profile_path:
        session_arguments["user_data_dir"] = request.profile_path
    factory: SessionFactory = session_factory or StealthySession

    started: float = clock()
    try:
        if request.profile_path:
            with locks.hold(
                profile_name=request.profile_path, timeout_seconds=lock_timeout_seconds
            ):
                page = _load(factory=factory, arguments=session_arguments, request=request)
        else:
            page = _load(factory=factory, arguments=session_arguments, request=request)
    except ProfileBusyError:
        raise
    except Exception as error:  # noqa: BLE001 - browser errors vary; converted at the boundary
        raise TierFetchError(
            tier_label=tier.label,
            reason=redact_proxy(
                text=f"{type(error).__name__}: {error}",
                secrets=[proxy_value] if proxy_value else None,
            ),
        ) from error
    return FetchResult(
        status=int(getattr(page, "status")),
        headers={str(key): str(value) for key, value in dict(getattr(page, "headers", {}) or {}).items()},
        html=bytes(getattr(page, "body")).decode(getattr(page, "encoding", None) or "utf-8", errors="replace"),
        final_url=str(getattr(page, "url", request.url)),
        tier=tier,
        elapsed_ms=int((clock() - started) * 1000),
    )


def _load(*, factory: SessionFactory, arguments: dict[str, object], request: TierRequest) -> object:
    """Open one session, load the page and close the session."""
    with factory(**arguments) as browser:
        return browser.fetch(request.url, network_idle=request.wait_for_network_idle)
