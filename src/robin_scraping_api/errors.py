"""Domain errors of the scraping API."""


class ScrapingError(Exception):
    """Base class for every expected failure of this project."""


class ProfileBusyError(ScrapingError):
    """Another request holds the lock of this profile and the wait timed out."""

    def __init__(self, *, profile_name: str, waited_seconds: float) -> None:
        """Store the profile name and the wait time as typed fields."""
        super().__init__(
            f"Profile '{profile_name}' is in use by another request. "
            f"Waited {waited_seconds:g} seconds."
        )
        self.profile_name: str = profile_name
        self.waited_seconds: float = waited_seconds


class InvalidEncryptionKeyError(ScrapingError):
    """The profiles encryption key is not a valid Fernet key."""
