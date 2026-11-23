"""Tests for settings defaults and the Fernet key check."""

import pytest
from cryptography.fernet import Fernet

from robin_scraping_api.encryption import build_fernet
from robin_scraping_api.errors import InvalidEncryptionKeyError
from robin_scraping_api.settings import Settings


def test_environment_defaults_to_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app starts without an ENVIRONMENT variable."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert Settings(_env_file=None).environment == "prod"


def test_environment_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ENVIRONMENT variable overrides the default."""
    monkeypatch.setenv("ENVIRONMENT", "dev")
    assert Settings(_env_file=None).environment == "dev"


def test_encryption_key_is_masked_in_repr() -> None:
    """The key never shows in the repr of the settings."""
    assert "change-me" not in repr(Settings(_env_file=None))


@pytest.mark.parametrize("bad_key", ["change-me", "", "short", "a" * 44])
def test_bad_key_is_rejected_with_clear_message(bad_key: str) -> None:
    """An invalid key raises a custom error that names the variable."""
    with pytest.raises(InvalidEncryptionKeyError, match="PROFILES_ENCRYPTION_KEY"):
        build_fernet(key=bad_key)


def test_good_key_is_accepted() -> None:
    """A generated Fernet key builds a working cipher."""
    cipher = build_fernet(key=Fernet.generate_key().decode())
    assert cipher.decrypt(cipher.encrypt(b"x")) == b"x"
