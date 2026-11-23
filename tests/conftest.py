"""Shared pytest fixtures: network guard and browser-test gate."""

import os
from collections.abc import Iterator

import pytest
from scrapling.fetchers import Fetcher
from urllib.parse import urlparse
from fixture_server import FixtureServer, serve
from pytest_socket import enable_socket, socket_allow_hosts

LOOPBACK_HOSTS: list[str] = ["127.0.0.1", "::1"]


@pytest.fixture(autouse=True)
def block_non_loopback_network() -> Iterator[None]:
    """Fail any test that opens a connection to a host other than loopback."""
    socket_allow_hosts(allowed=LOOPBACK_HOSTS, allow_unix_socket=True)
    yield
    enable_socket()


@pytest.fixture(autouse=True)
def block_non_loopback_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail when Fetcher.get targets a non-loopback URL or proxy.

    The HTTP client of Scrapling uses libcurl, which does not pass through the
    Python socket layer, so the socket guard alone cannot see its connections.
    """
    real_get = Fetcher.get

    def guarded_get(url: str, **kwargs: object) -> object:
        """Check the host of the URL and of the proxy, then call the real method."""
        hosts: list[str | None] = [urlparse(url).hostname]
        proxy: object = kwargs.get("proxy")
        if proxy:
            hosts.append(urlparse(str(proxy)).hostname)
        for host in hosts:
            if host not in ("127.0.0.1", "::1"):
                raise AssertionError(f"test tried a non-loopback HTTP request to {host}")
        return real_get(url, **kwargs)

    monkeypatch.setattr(Fetcher, "get", staticmethod(guarded_get))


@pytest.fixture
def fixture_server() -> Iterator[FixtureServer]:
    """Run the local fixture server for one test."""
    yield from serve()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip tests marked `browser` unless RUN_BROWSER_TESTS=1."""
    if os.environ.get("RUN_BROWSER_TESTS") == "1":
        return
    skip_browser = pytest.mark.skip(reason="set RUN_BROWSER_TESTS=1 to run")
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip_browser)
