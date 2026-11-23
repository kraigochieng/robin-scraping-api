"""Turn parsed HTML into the output formats of the API."""

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

from robin_scraping_api.schemas import OutputFormat

NOISE_WORDS: tuple[str, ...] = ("cookie", "consent", "banner", "gdpr")


def clean_soup(*, soup: BeautifulSoup) -> BeautifulSoup:
    """Remove navigation, scripts, cookie banners and data images from the soup."""
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    for tag in soup.find_all(
        True,
        id=lambda value: bool(
            value and any(word in value.lower() for word in NOISE_WORDS)
        ),
    ):
        tag.decompose()

    for tag in soup.find_all(
        True,
        class_=lambda value: bool(
            value and any(word in " ".join(value).lower() for word in NOISE_WORDS)
        ),
    ):
        tag.decompose()

    for image in soup.find_all("img"):
        if image.get("src", "").startswith("data:"):
            image.decompose()

    return soup


def render_root(*, root: Tag | BeautifulSoup, fmt: OutputFormat) -> str:
    """Render one parsed element as markdown, html or plain text."""
    if fmt == "markdown":
        return markdownify(str(root), heading_style="ATX")
    if fmt == "html":
        return str(root)
    return root.get_text(separator="\n", strip=True)


def render_plain_text(*, text: str, fmt: OutputFormat) -> str:
    """Render extracted article text (paragraphs split by blank lines) in a format."""
    if fmt == "html":
        paragraphs: list[str] = [part.strip() for part in text.split("\n") if part.strip()]
        return "".join(f"<p>{_escape(value=paragraph)}</p>" for paragraph in paragraphs)
    return text


def _escape(*, value: str) -> str:
    """Escape the characters that matter in HTML text."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
