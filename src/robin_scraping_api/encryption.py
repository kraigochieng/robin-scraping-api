"""Build the Fernet cipher from the profiles encryption key."""

from cryptography.fernet import Fernet

from robin_scraping_api.errors import InvalidEncryptionKeyError


def build_fernet(*, key: str) -> Fernet:
    """Return a Fernet cipher for the key, or raise InvalidEncryptionKeyError."""
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as error:
        raise InvalidEncryptionKeyError(
            "PROFILES_ENCRYPTION_KEY is not a valid Fernet key. "
            "Generate one with: python -c "
            "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        ) from error
