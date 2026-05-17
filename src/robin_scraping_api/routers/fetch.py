from fastapi import APIRouter, Query
from robin_scraping_api.services import fetch as fetch_service

from robin_scraping_api.schemas import OutputFormat, ScrapeResponse

router = APIRouter()


@router.get(
    "/fetch",
    response_model=ScrapeResponse,
    summary="Scrape a URL",
    description=(
        "Fetches a page using a stealthy browser session and returns its content. "
        "Pass `profile_name` to reuse a persistent browser profile (e.g. for authenticated sessions). "
        "Use `clean=false` to get the raw full-page output. "
        "Use `format` to control the output format: `markdown` (default), `html`, or `text`."
    ),
    responses={
        404: {"description": "Profile not found."},
    },
)
def fetch_url(
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
):
    return fetch_service.fetch(url, profile_name, clean, format)
