from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

OutputFormat = Literal["markdown", "html", "text"]


class ScrapeResponse(BaseModel):
    url: HttpUrl = Field(..., description="The URL that was scraped.")
    status: int = Field(
        ..., description="HTTP status code returned by the page.", examples=[200]
    )
    profile: str | None = Field(
        None, description="Browser profile used, or null if stateless."
    )
    clean: bool = Field(..., description="Whether noise removal was applied.")
    format: OutputFormat = Field(..., description="Output format of the content field.")
    content: str = Field(..., description="Page content in the requested format.")
