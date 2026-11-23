"""Tests for the autouse network guard."""

import socket

import pytest
from pytest_socket import SocketConnectBlockedError


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1::1"])
def test_external_address_is_blocked(address: str) -> None:
    """A connection to a non-loopback address must fail."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as client:
        with pytest.raises(SocketConnectBlockedError):
            client.connect((address, 80))


def test_loopback_address_is_allowed() -> None:
    """A connection to loopback passes the guard (it may be refused by the OS)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        with pytest.raises(ConnectionRefusedError):
            client.connect(("127.0.0.1", 1))
