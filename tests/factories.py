"""Small builders for test inputs."""

from robin_scraping_api.tiers.models import FetchResult, Tier

PROSE: str = (
    "The harbour reopened on Monday after three years of repairs and the fishing crews "
    "gathered on the new quay at dawn to watch the first boats come in. "
)


def words(*, count: int) -> str:
    """Return text with exactly this many words."""
    return " ".join(["word"] * count)


def page(*, body: str, head: str = "", title: str = "Title") -> str:
    """Wrap body markup in a minimal HTML page."""
    return f"<!doctype html><html><head><title>{title}</title>{head}</head><body>{body}</body></html>"


def make_result(*, html: str = "", status: int = 200, tier: Tier = Tier.HTTP) -> FetchResult:
    """Build a FetchResult with default headers and timing."""
    return FetchResult(
        status=status,
        headers={},
        html=html,
        final_url="http://127.0.0.1/page",
        tier=tier,
        elapsed_ms=5,
    )
