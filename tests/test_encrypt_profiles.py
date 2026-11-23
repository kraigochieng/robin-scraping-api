"""Tests for the profile encryption command."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from robin_scraping_api.encrypt_profiles import encrypt_profiles
from robin_scraping_api.errors import InvalidEncryptionKeyError


def test_module_imports() -> None:
    """Importing the module must not raise ImportError."""
    import robin_scraping_api.encrypt_profiles  # noqa: F401


def test_round_trip(tmp_path: Path) -> None:
    """Each file is written encrypted with an .enc suffix and decrypts to the original."""
    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "alice" / "Default").mkdir(parents=True)
    (profiles_dir / "alice" / "Default" / "Cookies").write_bytes(b"secret-cookie")
    encrypted_dir = tmp_path / "profiles_encrypted"
    key = Fernet.generate_key().decode()

    encrypt_profiles(profiles_dir=profiles_dir, encrypted_dir=encrypted_dir, key=key)

    encrypted_file = encrypted_dir / "alice" / "Default" / "Cookies.enc"
    assert encrypted_file.read_bytes() != b"secret-cookie"
    assert Fernet(key.encode()).decrypt(encrypted_file.read_bytes()) == b"secret-cookie"


def test_stale_output_is_removed(tmp_path: Path) -> None:
    """A rerun deletes files from the previous run."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    encrypted_dir = tmp_path / "out"
    encrypted_dir.mkdir()
    (encrypted_dir / "stale.enc").write_bytes(b"old")

    encrypt_profiles(
        profiles_dir=profiles_dir,
        encrypted_dir=encrypted_dir,
        key=Fernet.generate_key().decode(),
    )

    assert not (encrypted_dir / "stale.enc").exists()


def test_invalid_key_fails_before_touching_output(tmp_path: Path) -> None:
    """A bad key raises the custom error and leaves the output directory alone."""
    encrypted_dir = tmp_path / "out"
    encrypted_dir.mkdir()
    (encrypted_dir / "keep.enc").write_bytes(b"keep")

    with pytest.raises(InvalidEncryptionKeyError):
        encrypt_profiles(
            profiles_dir=tmp_path, encrypted_dir=encrypted_dir, key="change-me"
        )

    assert (encrypted_dir / "keep.enc").exists()
