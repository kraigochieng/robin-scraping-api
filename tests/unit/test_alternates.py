"""Tests for alternate discovery and parsing. No network."""

import json

import pytest
from factories import make_result, page, words

from robin_scraping_api.errors import TierFetchError
from robin_scraping_api.tiers.alternates import (
    KIND_AMP,
    KIND_FEED,
    KIND_PRINT,
    KIND_WP_JSON,
    discover_alternates,
    fetch_alternates,
    html_from_feed,
    html_from_wp_json,
)
from robin_scraping_api.tiers.models import Tier, TierRequest

URL: str = "http://127.0.0.1/news/my-post"


def kinds(*, head: str, html_extra: str = "") -> list[tuple[str, str]]:
    """Return (kind, url) of every alternate in a page."""
    found = discover_alternates(html=page(head=head, body=html_extra), url=URL)
    return [(item.kind, item.url) for item in found]


def test_amp_link() -> None:
    """rel=amphtml gives an AMP candidate with an absolute URL."""
    assert kinds(head='<link rel="amphtml" href="/amp/my-post">') == [(KIND_AMP, "http://127.0.0.1/amp/my-post")]


def test_feed_link() -> None:
    """An RSS alternate link gives a feed candidate."""
    assert kinds(head='<link rel="alternate" type="application/rss+xml" href="/feed">') == [(KIND_FEED, "http://127.0.0.1/feed")]


def test_wordpress_hint_gives_wp_json_with_slug() -> None:
    """The api.w.org link gives a wp-json URL with the last path segment as slug."""
    assert kinds(head='<link rel="https://api.w.org/" href="/wp-json/">') == [
        (KIND_WP_JSON, "http://127.0.0.1/wp-json/wp/v2/posts?slug=my-post")
    ]


def test_print_link() -> None:
    """rel=print gives a print candidate."""
    assert kinds(head='<link rel="print" href="/print/my-post">') == [(KIND_PRINT, "http://127.0.0.1/print/my-post")]


def test_no_hints_gives_nothing() -> None:
    """A page without hints has no alternates."""
    assert kinds(head="") == []


def test_other_host_is_dropped() -> None:
    """An alternate on another host is not followed."""
    assert kinds(head='<link rel="amphtml" href="http://elsewhere.invalid/amp">') == []


def test_wp_json_html() -> None:
    """The first post becomes a small article page."""
    body = json.dumps([{"title": {"rendered": "T"}, "content": {"rendered": "<p>Hello</p>"}}])
    html = html_from_wp_json(body=body)
    assert html is not None and "<h1>T</h1>" in html and "<p>Hello</p>" in html


@pytest.mark.parametrize("body", ["not json", "[]", "{}", json.dumps([{"title": {"rendered": "T"}}])])
def test_wp_json_unusable(body: str) -> None:
    """Broken, empty or content-less responses give None."""
    assert html_from_wp_json(body=body) is None


def test_feed_entry_is_matched_by_path() -> None:
    """The entry whose link path equals the page path is used."""
    feed = (
        '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
        "<item><title>A</title><link>http://127.0.0.1/other</link><description>nope</description></item>"
        "<item><title>B</title><link>http://127.0.0.1/news/my-post/</link><description>the body</description></item>"
        "</channel></rss>"
    )
    html = html_from_feed(body=feed, page_url=URL)
    assert html is not None and "the body" in html and "nope" not in html


def test_feed_without_matching_entry() -> None:
    """No matching entry gives None."""
    assert html_from_feed(body="<rss><channel><item><link>http://x/y</link></item></channel></rss>", page_url=URL) is None


def good(*, count: int = 100) -> str:
    """Return a page with enough words."""
    return page(body=f"<main><p>{words(count=count)}</p></main>")


def test_fetch_alternates_returns_first_accepted() -> None:
    """The first candidate that passes accept ends the search."""
    asked: list[str] = []

    def fetch_one(request: TierRequest):
        asked.append(request.url)
        return make_result(html=good(), tier=Tier.ALTERNATES)

    request = TierRequest(
        url=URL,
        hint_html=page(head='<link rel="amphtml" href="/amp/a"><link rel="print" href="/print/a">', body=""),
    )
    result = fetch_alternates(request=request, fetch_one=fetch_one, accept=lambda fetched: True)
    assert asked == ["http://127.0.0.1/amp/a"]
    assert result.tier == Tier.ALTERNATES
    assert result.extra["alternate_kind"] == KIND_AMP
    assert result.final_url == URL


def test_fetch_alternates_tries_next_when_not_accepted() -> None:
    """A rejected candidate is followed by the next one, and the last is returned."""
    asked: list[str] = []

    def fetch_one(request: TierRequest):
        asked.append(request.url)
        return make_result(html=good(count=3), tier=Tier.ALTERNATES)

    request = TierRequest(
        url=URL,
        hint_html=page(head='<link rel="amphtml" href="/amp/a"><link rel="print" href="/print/a">', body=""),
    )
    result = fetch_alternates(request=request, fetch_one=fetch_one, accept=lambda fetched: False)
    assert len(asked) == 2
    assert result.extra["alternate_kind"] == KIND_PRINT


def test_fetch_alternates_without_hints_raises() -> None:
    """No hints is a tier error, not a silent success."""
    with pytest.raises(TierFetchError):
        fetch_alternates(request=TierRequest(url=URL, hint_html="<html></html>"), fetch_one=lambda r: make_result(), accept=lambda f: True)


def test_fetch_alternates_all_failing_raises() -> None:
    """When every candidate fails to fetch, the tier raises."""

    def failing(request: TierRequest):
        raise TierFetchError(tier_label="alternates", reason="down")

    request = TierRequest(url=URL, hint_html=page(head='<link rel="amphtml" href="/amp/a">', body=""))
    with pytest.raises(TierFetchError):
        fetch_alternates(request=request, fetch_one=failing, accept=lambda f: True)


def test_fetch_alternates_skips_non_200() -> None:
    """A 404 from an alternate is skipped."""
    request = TierRequest(url=URL, hint_html=page(head='<link rel="amphtml" href="/amp/a">', body=""))
    with pytest.raises(TierFetchError):
        fetch_alternates(request=request, fetch_one=lambda r: make_result(status=404, html="x"), accept=lambda f: True)
