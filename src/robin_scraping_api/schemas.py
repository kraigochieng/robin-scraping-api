from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from robin_scraping_api.tiers.models import Attempt, Outcome

OutputFormat = Literal["markdown", "html", "text"]


class ScrapeResponse(BaseModel):
    url: HttpUrl = Field(..., description="The URL that was scraped.")
    status_code: int = Field(
        ..., description="HTTP status code returned by the page.", examples=[200]
    )
    status_message: str = Field(..., description="The message given by the scraper")
    profile: str | None = Field(
        None, description="Browser profile used, or null if stateless."
    )
    clean: bool = Field(..., description="Whether noise removal was applied.")
    format: OutputFormat = Field(..., description="Output format of the content field.")
    content: str = Field(..., description="Page content in the requested format.")
    tier_used: int | None = Field(
        None,
        description="Tier that produced the content: 1 http, 2 alternates, 3 http_proxy, 4 browser, 5 browser_stealth_proxy.",
    )
    outcome: Outcome | None = Field(
        None,
        description="Diagnosis of the final result: ok, needs_js, blocked, login_wall, thin or error.",
    )
    process: list[str] = Field(
        default_factory=list,
        description="Plain-English sentences that tell how the ladder moved between tiers.",
    )
    attempts: list[Attempt] | None = Field(
        None, description="One entry per tier run. Only present when debug=true."
    )
