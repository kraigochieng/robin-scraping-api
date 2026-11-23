"""Pull the article text out of HTML. Pure: no input or output."""

import json
import re
from collections.abc import Callable, Iterator

import trafilatura
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict

from robin_scraping_api.rendering import clean_soup

ARTICLE_TYPES: frozenset[str] = frozenset(
    {"NewsArticle", "Article", "BlogPosting", "ReportageNewsArticle"}
)
STRATEGY_JSON_LD: str = "json_ld"
STRATEGY_FRAMEWORK_JSON: str = "framework_json"
STRATEGY_TRAFILATURA: str = "trafilatura"
STRATEGY_CLEAN_SOUP: str = "clean_soup"
MINIMUM_FRAMEWORK_STRING_LENGTH: int = 200
NUXT_ASSIGNMENT: re.Pattern[str] = re.compile(r"window\.__NUXT__\s*=\s*", re.DOTALL)


class Extraction(BaseModel):
    """The text found and the name of the strategy that found it."""

    model_config = ConfigDict(frozen=True)

    strategy: str
    text: str


def extract(*, html: str, min_words: int = 50) -> Extraction:
    """Try JSON-LD, framework JSON, trafilatura, then the clean-soup text."""
    soup: BeautifulSoup = BeautifulSoup(html, "html.parser")
    strategies: list[tuple[str, Callable[[], str | None]]] = [
        (STRATEGY_JSON_LD, lambda: _from_json_ld(soup=soup)),
        (STRATEGY_FRAMEWORK_JSON, lambda: _from_framework_json(soup=soup)),
        (STRATEGY_TRAFILATURA, lambda: _from_trafilatura(html=html)),
    ]
    for name, strategy in strategies:
        text: str | None = strategy()
        if text and len(text.split()) >= min_words:
            return Extraction(strategy=name, text=text)
    return Extraction(strategy=STRATEGY_CLEAN_SOUP, text=_from_clean_soup(html=html))


def _from_clean_soup(*, html: str) -> str:
    """Return the text of the cleaned page, scoped to main or body."""
    soup: BeautifulSoup = clean_soup(soup=BeautifulSoup(html, "html.parser"))
    root: Tag | BeautifulSoup = soup.find("main") or soup.find("body") or soup
    return root.get_text(separator="\n", strip=True)


def _from_trafilatura(*, html: str) -> str | None:
    """Return the main text found by trafilatura, or None."""
    return trafilatura.extract(html, include_comments=False, include_tables=False)


def _iter_json_ld_nodes(*, value: object) -> Iterator[dict[str, object]]:
    """Yield every object inside a JSON-LD value, including @graph members."""
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_ld_nodes(value=item)
    elif isinstance(value, dict):
        yield value
        yield from _iter_json_ld_nodes(value=value.get("@graph"))


def _is_article_node(*, node: dict[str, object]) -> bool:
    """Return True when the node @type is an article type."""
    node_type: object = node.get("@type")
    types: list[object] = node_type if isinstance(node_type, list) else [node_type]
    return any(item in ARTICLE_TYPES for item in types)


def _from_json_ld(*, soup: BeautifulSoup) -> str | None:
    """Return the longest articleBody of an article object in JSON-LD, or None."""
    bodies: list[str] = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            parsed: object = json.loads(script.string or script.get_text() or "")
        except json.JSONDecodeError:
            continue
        for node in _iter_json_ld_nodes(value=parsed):
            body: object = node.get("articleBody")
            if _is_article_node(node=node) and isinstance(body, str) and body.strip():
                bodies.append(body.strip())
    return max(bodies, key=len) if bodies else None


def _page_title(*, soup: BeautifulSoup) -> str:
    """Return og:title, else h1, else the title element."""
    og_tag: Tag | None = soup.find("meta", property="og:title")
    if og_tag and og_tag.get("content"):
        return str(og_tag["content"]).strip()
    heading: Tag | None = soup.find("h1")
    if heading and heading.get_text(strip=True):
        return heading.get_text(strip=True)
    return soup.title.get_text(strip=True) if soup.title else ""


def _iter_framework_payloads(*, soup: BeautifulSoup) -> Iterator[object]:
    """Yield the parsed __NEXT_DATA__ and __NUXT__ payloads that are valid JSON."""
    raw_payloads: list[str] = []
    for script_id in ("__NEXT_DATA__", "__NUXT_DATA__"):
        script: Tag | None = soup.find("script", id=script_id)
        if script:
            raw_payloads.append(script.get_text())
    for script in soup.find_all("script"):
        match: re.Match[str] | None = NUXT_ASSIGNMENT.search(script.get_text())
        if match:
            raw_payloads.append(script.get_text()[match.end():].rstrip().rstrip(";"))
    for raw in raw_payloads:
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def _walk_objects(*, value: object) -> Iterator[dict[str, object]]:
    """Yield every dict found anywhere inside a JSON value."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_objects(value=child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_objects(value=child)


def _text_of_string(*, value: str) -> str:
    """Return plain text of a string that may hold HTML."""
    if "<" in value and ">" in value:
        return BeautifulSoup(value, "html.parser").get_text(separator="\n", strip=True)
    return value.strip()


def _from_framework_json(*, soup: BeautifulSoup) -> str | None:
    """Return the longest string field tied to the page title in __NEXT_DATA__ or __NUXT__.

    A string is tied to the title when it contains the title, or when it sits in an
    object that has another field equal to the title.
    """
    title: str = _page_title(soup=soup)
    if not title:
        return None
    lowered_title: str = title.lower()
    best: str = ""
    for payload in _iter_framework_payloads(soup=soup):
        for node in _walk_objects(value=payload):
            strings: list[str] = [item for item in node.values() if isinstance(item, str)]
            node_has_title: bool = any(item.strip().lower() == lowered_title for item in strings)
            for item in strings:
                text: str = _text_of_string(value=item)
                tied: bool = node_has_title or lowered_title in text.lower()
                if (
                    tied
                    and text.lower() != lowered_title
                    and len(text) >= MINIMUM_FRAMEWORK_STRING_LENGTH
                    and len(text) > len(best)
                ):
                    best = text
    return best or None
