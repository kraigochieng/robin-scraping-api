"""Domain errors of the scraping API."""


class ScrapingError(Exception):
    """Base class for every expected failure of this project."""


class InvalidEncryptionKeyError(ScrapingError):
    """The profiles encryption key is not a valid Fernet key."""
