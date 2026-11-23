from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import SecretStr

from robin_scraping_api.errors import (
    AllTiersFailedError,
    ProfileBusyError,
    ProfileNotFoundError,
)
from robin_scraping_api.schemas import OutputFormat, ScrapeResponse
from robin_scraping_api.services import fetch as fetch_service
from robin_scraping_api.settings import settings
from robin_scraping_api.tiers.classify import ClassifyConfig
from robin_scraping_api.tiers.ladder import Ladder
from robin_scraping_api.tiers.models import Tier
from robin_scraping_api.tiers.wiring import build_ladder

router = APIRouter()


@lru_cache
def get_ladder() -> Ladder:
    """Return the shared ladder built from settings. Tests override this dependency."""
    return build_ladder(
        classify_config=ClassifyConfig(min_words=settings.classify_min_words),
        lock_timeout_seconds=settings.profile_lock_timeout_seconds,
    )


@router.get(
    "/fetch",
    response_model=ScrapeResponse,
    summary="Scrape a URL",
    description=(
        "Fetches a page with an escalation ladder. Cheap tiers run first: plain HTTP, "
        "alternate copies (AMP, feed, WordPress API, print), HTTP through a proxy. "
        "The stealth browser runs last. The `process` field tells in plain English how the ladder moved. "
        "Pass `profile_name` to reuse a persistent browser profile (e.g. for authenticated sessions). "
        "Use `clean=false` to get the raw full-page output. "
        "Use `format` to control the output format: `markdown` (default), `html`, or `text`. "
        "Use `min_tier` and `max_tier` (1-5) to limit the ladder. Use `debug=true` to get `attempts`."
    ),
    responses={
        404: {"description": "Profile not found."},
        409: {"description": "Profile is in use by another request."},
        422: {"description": "min_tier is greater than max_tier."},
        502: {"description": "No tier could fetch the page."},
    },
)
def fetch_url(
    ladder: Annotated[Ladder, Depends(get_ladder)],
    url: str = Query(
        ..., description="The URL to scrape.", examples=["https://example.com"]
    ),
    profile_name: str | None = Query(
        None,
        description="Name of a persistent browser profile to use. Omit for a stateless scrape.",
        examples=["my-profile"],
    ),
    clean: bool = Query(
        True,
        description="Remove noise (nav, footer, cookie banners, data: images) and scope to <main>. Default: true.",
    ),
    format: OutputFormat = Query(
        "markdown",
        description="Output format for the content field. One of: markdown, html, text.",
    ),
    min_tier: int = Query(1, ge=1, le=5, description="Lowest tier allowed to run (1-5)."),
    max_tier: int = Query(5, ge=1, le=5, description="Highest tier allowed to run (1-5)."),
    proxy: str | None = Query(
        None,
        description="Proxy URL for tiers 3 and 5. Overrides SCRAPING_PROXY. Credentials in a query string can appear in access logs.",
    ),
    debug: bool = Query(False, description="Include the attempts list in the response."),
) -> ScrapeResponse:
    """Parse the request, call the fetch service, and map domain errors to HTTP statuses."""
    if min_tier > max_tier:
        raise HTTPException(status_code=422, detail="min_tier must not be greater than max_tier.")
    try:
        return fetch_service.fetch(
            url=url,
            ladder=ladder,
            profile_name=profile_name,
            clean=clean,
            fmt=format,
            min_tier=Tier(min_tier),
            max_tier=Tier(max_tier),
            proxy=SecretStr(proxy) if proxy else None,
            debug=debug,
        )
    except ProfileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ProfileBusyError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
            headers={"Retry-After": str(int(settings.profile_lock_timeout_seconds))},
        ) from error
    except AllTiersFailedError as error:
        raise HTTPException(
            status_code=502, detail={"message": str(error), "process": error.process}
        ) from error
