import logging
from http import HTTPStatus

from bs4 import BeautifulSoup
from pydantic import SecretStr

from robin_scraping_api.config import PROFILES_DIR
from robin_scraping_api.errors import AllTiersFailedError, ProfileNotFoundError
from robin_scraping_api.logging_config import setup_logging
from robin_scraping_api.rendering import clean_soup, render_plain_text, render_root
from robin_scraping_api.schemas import OutputFormat, ScrapeResponse
from robin_scraping_api.settings import settings
from robin_scraping_api.tiers.extract import STRATEGY_CLEAN_SOUP, extract
from robin_scraping_api.tiers.ladder import Ladder, LadderRequest, LadderResult
from robin_scraping_api.tiers.models import FetchResult, Tier

setup_logging()

logger = logging.getLogger(__name__)


def _status_message(*, status: int) -> str:
    """Return the standard reason phrase of an HTTP status code."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def _legacy_content(*, html: str, clean: bool, fmt: OutputFormat) -> str:
    """Render the page body as before: scope to main when clean, else the full body."""
    soup: BeautifulSoup = BeautifulSoup(html, "html.parser")
    if clean:
        soup = clean_soup(soup=soup)
        root = soup.find("main") or soup.find("body") or soup
    else:
        root = soup.find("body") or soup
    return render_root(root=root, fmt=fmt)


def _build_content(*, final: FetchResult, clean: bool, fmt: OutputFormat) -> str:
    """Return the content: extracted article text when clean, else the full body."""
    if clean:
        extraction = extract(html=final.html, min_words=settings.classify_min_words)
        if extraction.strategy != STRATEGY_CLEAN_SOUP:
            return render_plain_text(text=extraction.text, fmt=fmt)
    return _legacy_content(html=final.html, clean=clean, fmt=fmt)


def fetch(
    *,
    url: str,
    ladder: Ladder,
    profile_name: str | None = None,
    clean: bool = True,
    fmt: OutputFormat = "markdown",
    min_tier: Tier = Tier.HTTP,
    max_tier: Tier = Tier.BROWSER_STEALTH_PROXY,
    proxy: SecretStr | None = None,
    debug: bool = False,
) -> ScrapeResponse:
    """Fetch a URL through the ladder. Has side effects through the ladder tiers."""
    profile_path: str | None = None
    if profile_name:
        candidate = PROFILES_DIR / profile_name
        if not candidate.exists():
            logger.warning("Profile '%s' not found", profile_name)
            raise ProfileNotFoundError(profile_name=profile_name)
        profile_path = str(candidate)

    logger.info(
        "Fetching url=%s profile=%s clean=%s format=%s min_tier=%s max_tier=%s",
        url,
        profile_name or "none",
        clean,
        fmt,
        int(min_tier),
        int(max_tier),
    )

    result: LadderResult = ladder.run(
        request=LadderRequest(
            url=url,
            min_tier=min_tier,
            max_tier=max_tier,
            proxy=proxy or settings.scraping_proxy,
            profile_path=profile_path,
            timeout_seconds=settings.request_timeout_seconds,
        )
    )
    for line in result.process:
        logger.info("ladder: %s", line)

    if result.final is None:
        raise AllTiersFailedError(url=url, process=result.process)

    return ScrapeResponse(
        url=url,
        status_code=result.final.status,
        status_message=_status_message(status=result.final.status),
        profile=profile_name,
        clean=clean,
        format=fmt,
        content=_build_content(final=result.final, clean=clean, fmt=fmt),
        tier_used=int(result.final.tier),
        outcome=result.outcome,
        process=result.process,
        attempts=result.attempts if debug else None,
    )
