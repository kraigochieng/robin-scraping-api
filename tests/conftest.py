"""Shared pytest fixtures: network guard and browser-test gate."""

import os
from collections.abc import Iterator

import pytest
from pytest_socket import enable_socket, socket_allow_hosts

LOOPBACK_HOSTS: list[str] = ["127.0.0.1", "::1"]


@pytest.fixture(autouse=True)
def block_non_loopback_network() -> Iterator[None]:
    """Fail any test that opens a connection to a host other than loopback."""
    socket_allow_hosts(allowed=LOOPBACK_HOSTS, allow_unix_socket=True)
    yield
    enable_socket()


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
