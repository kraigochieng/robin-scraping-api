import logging

from bs4 import BeautifulSoup
from fastapi import HTTPException
from markdownify import markdownify
from scrapling.fetchers import StealthySession

from robin_scraping_api.config import PROFILES_DIR
from robin_scraping_api.logging_config import setup_logging
from robin_scraping_api.schemas import OutputFormat, ScrapeResponse

setup_logging()

logger = logging.getLogger(__name__)


def _clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    for tag in soup.find_all(
        True,
        id=lambda v: (
            v and any(x in v.lower() for x in ("cookie", "consent", "banner", "gdpr"))
        ),
    ):
        tag.decompose()

    for tag in soup.find_all(
        True,
        class_=lambda v: (
            v
            and any(
                x in " ".join(v).lower()
                for x in ("cookie", "consent", "banner", "gdpr")
            )
        ),
    ):
        tag.decompose()

    for img in soup.find_all("img"):
        if img.get("src", "").startswith("data:"):
            img.decompose()

    return soup


def _render(root, fmt: OutputFormat) -> str:
    if fmt == "markdown":
        return markdownify(str(root), heading_style="ATX")
    if fmt == "html":
        return str(root)
    return root.get_text(separator="\n", strip=True)


def fetch(
    url: str,
    profile_name: str | None = None,
    clean: bool = True,
    fmt: OutputFormat = "markdown",
) -> ScrapeResponse:
    user_data_dir = None

    if profile_name:
        profile_path = PROFILES_DIR / profile_name
        if not profile_path.exists():
            logger.warning("Profile '%s' not found", profile_name)
            raise HTTPException(
                status_code=404, detail=f"Profile '{profile_name}' not found."
            )
        user_data_dir = str(profile_path)

    logger.info(
        "Fetching url=%s profile=%s clean=%s format=%s",
        url,
        profile_name or "none",
        clean,
        fmt,
    )

    session_kwargs = {"headless": True}
    if user_data_dir:
        session_kwargs["user_data_dir"] = user_data_dir

    with StealthySession(**session_kwargs) as browser:
        page = browser.fetch(url, network_idle=True)

    logger.info("Fetched url=%s status=%s", url, page.status)

    soup = BeautifulSoup(page.body, "html.parser")

    if clean:
        soup = _clean_soup(soup)
        root = soup.find("main") or soup.find("body") or soup
    else:
        root = soup.find("body") or soup

    return ScrapeResponse(
        url=url,
        status=page.status,
        profile=profile_name,
        clean=clean,
        format=fmt,
        content=_render(root, fmt),
    )
