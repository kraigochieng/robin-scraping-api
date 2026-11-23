"""Tests for API candidate detection. Pure."""

import json

import pytest
from factories import page

from robin_scraping_api.tiers.candidates import (
    CapturedResponse,
    find_api_candidates,
    first_sentence,
    og_title,
)

SENTENCE: str = "The old harbour on the east coast reopened on Monday after three years of repairs."
HTML: str = page(
    head='<meta property="og:title" content="The Harbour Reopens">',
    body=f"<nav><p>Menu menu menu menu menu menu menu menu.</p></nav><main><p>Hi.</p><p>{SENTENCE} More text follows here.</p></main>",
)


def response(*, body: str, status: int = 200, url: str = "http://127.0.0.1/api/a") -> CapturedResponse:
    """Build a captured response."""
    return CapturedResponse(url=url, status=status, content_type="application/json", body=body)


def test_helpers() -> None:
    """og:title and first sentence are read, skipping nav and short paragraphs."""
    assert og_title(html=HTML) == "The Harbour Reopens"
    assert first_sentence(html=HTML) == SENTENCE
    assert og_title(html="<html></html>") == ""
    assert first_sentence(html="<html></html>") == ""


def test_match_on_title_only() -> None:
    """A JSON body with the title but not the sentence matches on og_title."""
    found = find_api_candidates(captured=[response(body=json.dumps({"headline": "The Harbour Reopens"}))], html=HTML)
    assert [(item.url, item.matched_on) for item in found] == [("http://127.0.0.1/api/a", ["og_title"])]


def test_match_on_sentence_and_title() -> None:
    """A body with both reports both reasons."""
    body = json.dumps({"title": "The Harbour Reopens", "body": SENTENCE + " Extra."})
    found = find_api_candidates(captured=[response(body=body)], html=HTML)
    assert found[0].matched_on == ["og_title", "first_sentence"]
    assert found[0].size_bytes == len(body)


def test_match_ignores_case_and_white_space() -> None:
    """Matching normalises case and spacing."""
    body = json.dumps({"x": "the  HARBOUR\nreopens"})
    assert find_api_candidates(captured=[response(body=body)], html=HTML)


def test_non_ascii_escapes_are_decoded() -> None:
    """json.dumps escapes non-ASCII characters, and the match still works."""
    html = page(head='<meta property="og:title" content="Café opens">', body="")
    body = json.dumps({"t": "Café opens"})
    assert "Café" not in body
    assert find_api_candidates(captured=[response(body=body)], html=html)


@pytest.mark.parametrize(
    "captured",
    [
        [response(body=json.dumps({"headline": "Something else"}))],
        [response(body="not json at all The Harbour Reopens")],
        [response(body=json.dumps({"headline": "The Harbour Reopens"}), status=404)],
        [response(body=json.dumps({"The Harbour Reopens": 1}))],
        [],
    ],
    ids=["no match", "not json", "error status", "key only", "nothing captured"],
)
def test_no_candidate(captured: list[CapturedResponse]) -> None:
    """Non-matching, non-JSON, failed and empty cases give nothing."""
    assert find_api_candidates(captured=captured, html=HTML) == []


def test_page_without_needles_gives_nothing() -> None:
    """With no og:title and no paragraph there is nothing to look for."""
    assert find_api_candidates(captured=[response(body='{"a": "b"}')], html="<html></html>") == []


def test_oversized_body_is_skipped() -> None:
    """A body over the size limit is not parsed."""
    big = json.dumps({"t": "The Harbour Reopens", "pad": "x" * 2_100_000})
    assert find_api_candidates(captured=[response(body=big)], html=HTML) == []
