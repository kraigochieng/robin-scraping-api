"""Domain errors of the scraping API."""


class ScrapingError(Exception):
    """Base class for every expected failure of this project."""


class ProfileNotFoundError(ScrapingError):
    """The named browser profile does not exist."""

    def __init__(self, *, profile_name: str) -> None:
        """Store the profile name as a typed field."""
        super().__init__(f"Profile '{profile_name}' not found.")
        self.profile_name: str = profile_name


class TierFetchError(ScrapingError):
    """A tier could not fetch the page (network error, timeout, browser failure)."""

    def __init__(self, *, tier_label: str, reason: str) -> None:
        """Store the tier name and the redacted reason as typed fields."""
        super().__init__(f"Tier {tier_label} failed: {reason}")
        self.tier_label: str = tier_label
        self.reason: str = reason


class AllTiersFailedError(ScrapingError):
    """Every tier that ran raised an error, so there is no page to return."""

    def __init__(self, *, url: str, process: list[str]) -> None:
        """Store the URL and the plain-English process lines."""
        super().__init__(f"No tier could fetch {url}.")
        self.url: str = url
        self.process: list[str] = process


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
