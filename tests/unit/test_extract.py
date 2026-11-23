"""Tests for extract: each strategy, the fallthrough order and malformed input."""

import json

import pytest
from factories import page, words

from robin_scraping_api.tiers.extract import (
    STRATEGY_CLEAN_SOUP,
    STRATEGY_FRAMEWORK_JSON,
    STRATEGY_JSON_LD,
    STRATEGY_TRAFILATURA,
    extract,
)

BODY: str = "Harbour news. " + words(count=80)
TITLE_HEAD: str = '<meta property="og:title" content="The Harbour Reopens">'


def json_ld(*, node: object) -> str:
    """Return a JSON-LD script tag."""
    return f'<script type="application/ld+json">{json.dumps(node)}</script>'


def next_data(*, payload: object) -> str:
    """Return a __NEXT_DATA__ script tag."""
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'


def test_json_ld_news_article_body() -> None:
    """articleBody of a NewsArticle wins."""
    html = page(head=json_ld(node={"@type": "NewsArticle", "articleBody": BODY}), body="<p>x</p>")
    result = extract(html=html)
    assert (result.strategy, result.text) == (STRATEGY_JSON_LD, BODY)


def test_json_ld_inside_graph_and_list() -> None:
    """An article inside @graph is found."""
    node = {"@graph": [{"@type": "WebSite"}, {"@type": ["Thing", "NewsArticle"], "articleBody": BODY}]}
    assert extract(html=page(head=json_ld(node=node), body="")).strategy == STRATEGY_JSON_LD


def test_json_ld_other_type_is_ignored() -> None:
    """A Product with articleBody is not an article."""
    html = page(head=json_ld(node={"@type": "Product", "articleBody": BODY}), body="")
    assert extract(html=html).strategy != STRATEGY_JSON_LD


def test_json_ld_body_below_minimum_falls_through() -> None:
    """A tiny articleBody does not win over later strategies."""
    html = page(head=json_ld(node={"@type": "NewsArticle", "articleBody": "tiny"}), body="<p>x</p>")
    assert extract(html=html).strategy != STRATEGY_JSON_LD


def test_malformed_json_ld_is_skipped() -> None:
    """Broken JSON-LD does not raise."""
    html = page(head='<script type="application/ld+json">{not json</script>', body="<p>Some words here.</p>")
    assert extract(html=html).strategy == STRATEGY_CLEAN_SOUP


def test_next_data_object_with_title_field() -> None:
    """The longest string next to a field equal to the title is returned."""
    payload = {"props": {"pageProps": {"article": {"title": "The Harbour Reopens", "body": BODY * 3, "slug": "x"}}}}
    html = page(head=TITLE_HEAD + next_data(payload=payload), body="<div id='__next'></div>")
    result = extract(html=html)
    assert result.strategy == STRATEGY_FRAMEWORK_JSON
    assert result.text == BODY * 3


def test_next_data_string_containing_title() -> None:
    """A long string that contains the title counts, and HTML in it is stripped."""
    text = "<p>The Harbour Reopens today. " + words(count=80) + "</p>"
    payload = {"props": {"html": text}}
    html = page(head=TITLE_HEAD + next_data(payload=payload), body="")
    result = extract(html=html)
    assert result.strategy == STRATEGY_FRAMEWORK_JSON
    assert "<p>" not in result.text


def test_nuxt_assignment_json() -> None:
    """window.__NUXT__ with a JSON object is read."""
    payload = {"data": {"title": "The Harbour Reopens", "content": BODY * 3}}
    html = page(head=TITLE_HEAD, body=f"<script>window.__NUXT__={json.dumps(payload)};</script>")
    assert extract(html=html).strategy == STRATEGY_FRAMEWORK_JSON


def test_malformed_next_data_is_skipped() -> None:
    """Broken __NEXT_DATA__ does not raise."""
    html = page(head=TITLE_HEAD + '<script id="__NEXT_DATA__" type="application/json">{oops</script>', body="<p>few words</p>")
    assert extract(html=html).strategy == STRATEGY_CLEAN_SOUP


def test_framework_json_without_title_is_skipped() -> None:
    """With no title on the page, the framework strategy gives nothing."""
    html = "<html><body>" + next_data(payload={"a": {"title": "x", "body": BODY * 3}}) + "</body></html>"
    assert extract(html=html).strategy != STRATEGY_FRAMEWORK_JSON


def test_trafilatura_for_plain_article() -> None:
    """A plain article page goes to trafilatura."""
    paragraphs = "".join(f"<p>Paragraph {index}. {words(count=40)}</p>" for index in range(4))
    html = page(body=f"<nav>Menu</nav><main><article><h1>Title</h1>{paragraphs}</article></main><footer>Foot</footer>")
    result = extract(html=html)
    assert result.strategy == STRATEGY_TRAFILATURA
    assert "Menu" not in result.text


def test_clean_soup_is_the_last_resort() -> None:
    """A short page falls through every strategy to clean_soup, without nav."""
    html = page(body="<nav>Menu</nav><main><p>Short text.</p></main>")
    result = extract(html=html)
    assert result.strategy == STRATEGY_CLEAN_SOUP
    assert result.text == "Short text."


def test_order_json_ld_beats_framework_json() -> None:
    """When both exist, JSON-LD is used first."""
    payload = {"article": {"title": "The Harbour Reopens", "body": "NEXT " + BODY * 3}}
    head = TITLE_HEAD + json_ld(node={"@type": "NewsArticle", "articleBody": BODY}) + next_data(payload=payload)
    assert extract(html=page(head=head, body="")).strategy == STRATEGY_JSON_LD


@pytest.mark.parametrize("html", ["", "<html>", "not html at all"])
def test_degenerate_input_does_not_raise(html: str) -> None:
    """Empty or broken input returns an extraction."""
    assert extract(html=html).strategy == STRATEGY_CLEAN_SOUP
