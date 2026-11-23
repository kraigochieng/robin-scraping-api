"""Find JSON responses that hold the page content. Pure: no input or output."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from robin_scraping_api.tiers.models import ApiCandidate

MAXIMUM_BODY_BYTES: int = 2_000_000
MINIMUM_SENTENCE_LENGTH: int = 30
MAXIMUM_SENTENCE_LENGTH: int = 200
MATCH_OG_TITLE: str = "og_title"
MATCH_FIRST_SENTENCE: str = "first_sentence"


@dataclass(frozen=True)
class CapturedResponse:
    """One XHR or fetch response seen by the browser."""

    url: str
    status: int
    content_type: str
    body: str


def _normalise(*, text: str) -> str:
    """Lowercase the text and collapse white space."""
    return re.sub(r"\s+", " ", text).strip().lower()


def og_title(*, html: str) -> str:
    """Return the og:title of the page, or an empty string."""
    tag: Tag | None = BeautifulSoup(html, "html.parser").find("meta", property="og:title")
    return str(tag.get("content") or "").strip() if tag else ""


def first_sentence(*, html: str) -> str:
    """Return the first sentence of the first long paragraph, or an empty string."""
    soup: BeautifulSoup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    for paragraph in soup.find_all("p"):
        text: str = re.sub(r"\s+", " ", paragraph.get_text(" ", strip=True))
        if len(text) < MINIMUM_SENTENCE_LENGTH:
            continue
        sentence: str = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
        return sentence[:MAXIMUM_SENTENCE_LENGTH]
    return ""


def _iter_strings(*, value: object) -> Iterator[str]:
    """Yield every string inside a parsed JSON value, keys excluded."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _iter_strings(value=child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_strings(value=child)


def _is_json_text(*, response: CapturedResponse) -> object | None:
    """Return the parsed JSON of the response body, or None when it is not JSON."""
    if len(response.body) > MAXIMUM_BODY_BYTES:
        return None
    try:
        return json.loads(response.body)
    except json.JSONDecodeError:
        return None


def find_api_candidates(
    *, captured: list[CapturedResponse], html: str
) -> list[ApiCandidate]:
    """Return captured JSON responses whose strings contain the og:title or first sentence."""
    needles: dict[str, str] = {
        MATCH_OG_TITLE: _normalise(text=og_title(html=html)),
        MATCH_FIRST_SENTENCE: _normalise(text=first_sentence(html=html)),
    }
    needles = {name: value for name, value in needles.items() if value}
    if not needles:
        return []
    found: list[ApiCandidate] = []
    for response in captured:
        if not 200 <= response.status < 300:
            continue
        parsed: object | None = _is_json_text(response=response)
        if parsed is None:
            continue
        texts: list[str] = [_normalise(text=value) for value in _iter_strings(value=parsed)]
        matched: list[str] = [
            name for name, needle in needles.items() if any(needle in text for text in texts)
        ]
        if matched:
            found.append(
                ApiCandidate(
                    url=response.url,
                    status=response.status,
                    matched_on=matched,
                    size_bytes=len(response.body.encode("utf-8")),
                )
            )
    return found
