"""Remove proxy credentials from text before it reaches a log or a trace."""

import re

_URL_CREDENTIALS: re.Pattern[str] = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s@]+@")


def redact_proxy(*, text: str, secrets: list[str] | None = None) -> str:
    """Replace user:password in URLs, and every listed secret, with a mask."""
    masked: str = _URL_CREDENTIALS.sub(r"\g<scheme>***:***@", text)
    for secret in secrets or []:
        if secret:
            masked = masked.replace(secret, "***")
    return masked
