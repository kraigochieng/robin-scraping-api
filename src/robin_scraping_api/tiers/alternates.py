"""Tier 2: cheaper copies of the page (AMP, feed, WordPress API, print view)."""

import json
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict

from robin_scraping_api.errors import TierFetchError
from robin_scraping_api.tiers.models import FetchResult, Tier, TierRequest

KIND_AMP: str = "amp"
KIND_WP_JSON: str = "wp_json"
KIND_FEED: str = "feed"
KIND_PRINT: str = "print"
FEED_TYPES: tuple[str, ...] = ("application/rss+xml", "application/atom+xml")


class AlternateCandidate(BaseModel):
    """One alternate URL the page points to."""

    model_config = ConfigDict(frozen=True)

    kind: str
    url: str


def _same_host(*, first: str, second: str) -> bool:
    """Return True when two URLs have the same host name."""
    return urlparse(first).netloc == urlparse(second).netloc


def discover_alternates(*, html: str, url: str) -> list[AlternateCandidate]:
    """List alternate URLs the HTML hints at. Only same-host URLs are kept. Pure."""
    soup: BeautifulSoup = BeautifulSoup(html, "html.parser")
    found: list[AlternateCandidate] = []

    amp: Tag | None = soup.find("link", rel="amphtml")
    if amp and amp.get("href"):
        found.append(AlternateCandidate(kind=KIND_AMP, url=urljoin(url, str(amp["href"]))))

    api_link: Tag | None = soup.find("link", rel="https://api.w.org/")
    if api_link or "/wp-json/" in html or "/wp-content/" in html:
        parsed = urlparse(url)
        slug: str = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if slug:
            found.append(
                AlternateCandidate(
                    kind=KIND_WP_JSON,
                    url=f"{parsed.scheme}://{parsed.netloc}/wp-json/wp/v2/posts?slug={slug}",
                )
            )

    for link in soup.find_all("link", rel="alternate"):
        if str(link.get("type") or "").lower() in FEED_TYPES and link.get("href"):
            found.append(AlternateCandidate(kind=KIND_FEED, url=urljoin(url, str(link["href"]))))

    print_link: Tag | None = soup.find("link", rel="print") or soup.find(
        "link", rel="alternate", media="print"
    )
    if print_link and print_link.get("href"):
        found.append(AlternateCandidate(kind=KIND_PRINT, url=urljoin(url, str(print_link["href"]))))

    return [candidate for candidate in found if _same_host(first=candidate.url, second=url)]


def html_from_wp_json(*, body: str) -> str | None:
    """Build a small HTML page from a WordPress posts response, or None. Pure."""
    try:
        posts: object = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(posts, list) or not posts or not isinstance(posts[0], dict):
        return None
    post: dict[str, object] = posts[0]
    title: object = (post.get("title") or {}).get("rendered", "") if isinstance(post.get("title"), dict) else ""
    content: object = (post.get("content") or {}).get("rendered", "") if isinstance(post.get("content"), dict) else ""
    if not content:
        return None
    return f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1>{content}</article></body></html>"


def html_from_feed(*, body: str, page_url: str) -> str | None:
    """Build a small HTML page from the feed entry that points to the page URL. Pure."""
    soup: BeautifulSoup = BeautifulSoup(body, "xml")
    target_path: str = urlparse(page_url).path.rstrip("/")
    for entry in soup.find_all(["item", "entry"]):
        link_tag: Tag | None = entry.find("link")
        link: str = str(link_tag.get("href") or link_tag.get_text(strip=True)) if link_tag else ""
        if urlparse(link).path.rstrip("/") != target_path:
            continue
        title_tag: Tag | None = entry.find("title")
        content_tag: Tag | None = entry.find("content:encoded") or entry.find("content") or entry.find("description") or entry.find("summary")
        if content_tag is None:
            continue
        title: str = title_tag.get_text(strip=True) if title_tag else ""
        return f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1>{content_tag.get_text()}</article></body></html>"
    return None


def _candidate_to_html(*, candidate: AlternateCandidate, fetched: FetchResult, page_url: str) -> str | None:
    """Convert a fetched alternate to an HTML page, or None when it holds nothing."""
    if fetched.status != 200:
        return None
    if candidate.kind == KIND_WP_JSON:
        return html_from_wp_json(body=fetched.html)
    if candidate.kind == KIND_FEED:
        return html_from_feed(body=fetched.html, page_url=page_url)
    return fetched.html


def fetch_alternates(
    *,
    request: TierRequest,
    fetch_one: Callable[[TierRequest], FetchResult],
    accept: Callable[[FetchResult], bool],
    clock: Callable[[], float] = time.monotonic,
) -> FetchResult:
    """Try each alternate URL in order. Has a network side effect. Raises TierFetchError."""
    started: float = clock()
    candidates: list[AlternateCandidate] = discover_alternates(
        html=request.hint_html or "", url=request.url
    )
    if not candidates:
        raise TierFetchError(tier_label=Tier.ALTERNATES.label, reason="the page has no alternate hints")
    last: FetchResult | None = None
    for candidate in candidates:
        try:
            fetched: FetchResult = fetch_one(request.model_copy(update={"url": candidate.url}))
        except TierFetchError:
            continue
        html: str | None = _candidate_to_html(candidate=candidate, fetched=fetched, page_url=request.url)
        if html is None:
            continue
        last = FetchResult(
            status=200,
            headers=fetched.headers,
            html=html,
            final_url=request.url,
            tier=Tier.ALTERNATES,
            elapsed_ms=int((clock() - started) * 1000),
            extra={"alternate_kind": candidate.kind, "alternate_url": candidate.url},
        )
        if accept(last):
            return last
    if last is None:
        raise TierFetchError(
            tier_label=Tier.ALTERNATES.label, reason="no alternate URL returned usable content"
        )
    return last
