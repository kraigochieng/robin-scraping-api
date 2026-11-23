"""Table-driven tests for classify. No input or output."""

import pytest
from factories import PROSE, make_result, page, words

from robin_scraping_api.tiers.classify import ClassifyConfig, classify, diagnose
from robin_scraping_api.tiers.models import Outcome

LONG: str = words(count=120)
CHALLENGE_BODY: str = '<div id="cf-chl-widget"><p>Checking your browser</p></div>'

OUTCOME_CASES: list[tuple[str, str, int, Outcome]] = [
    ("complete article", page(body=f"<main><h1>Title</h1><p>{LONG}</p></main>"), 200, Outcome.OK),
    ("status 403", page(body=f"<p>{LONG}</p>"), 403, Outcome.BLOCKED),
    ("status 429", "<html></html>", 429, Outcome.BLOCKED),
    ("status 503", "<html></html>", 503, Outcome.BLOCKED),
    ("status 404", page(body=f"<p>{LONG}</p>"), 404, Outcome.ERROR),
    ("status 500", "", 500, Outcome.ERROR),
    ("challenge element on 200", page(body=CHALLENGE_BODY), 200, Outcome.BLOCKED),
    ("challenge title on 200", page(body="<p>Please wait.</p>", title="Just a moment..."), 200, Outcome.BLOCKED),
    ("challenge script host", page(body='<script src="https://challenges.cloudflare.com/x.js"></script><p>wait</p>'), 200, Outcome.BLOCKED),
    ("empty react root", page(body='<div id="root"></div><script src="/app.js"></script>'), 200, Outcome.NEEDS_JS),
    ("empty next root", page(body='<div id="__next"></div>'), 200, Outcome.NEEDS_JS),
    ("noscript enable javascript", page(body="<noscript>Please enable JavaScript to continue</noscript><p>Hi</p>"), 200, Outcome.NEEDS_JS),
    ("paywall marker", page(body=f'<p>{words(count=60)}</p><div class="paywall">Subscribe</div>'), 200, Outcome.LOGIN_WALL),
    ("sign in phrase", page(body="<p>Sign in to continue reading this story.</p>"), 200, Outcome.LOGIN_WALL),
    ("password form", page(body='<form><input type="password"></form><p>Welcome back</p>'), 200, Outcome.LOGIN_WALL),
    ("thin page", page(body="<main><p>Only a few words here.</p></main>"), 200, Outcome.THIN),
    ("empty body", page(body=""), 200, Outcome.THIN),
]


@pytest.mark.parametrize(("name", "html", "status", "expected"), OUTCOME_CASES, ids=[case[0] for case in OUTCOME_CASES])
def test_outcome(name: str, html: str, status: int, expected: Outcome) -> None:
    """Each signal gives its outcome."""
    assert classify(result=make_result(html=html, status=status)) == expected


def test_framework_heavy_ssr_page_that_is_complete_is_ok() -> None:
    """A page with a __next root, many scripts and full text is ok."""
    scripts: str = "".join(f'<script src="/chunk{index}.js"></script>' for index in range(30))
    html: str = page(body=f'<div id="__next"><main><p>{LONG}</p></main></div>{scripts}<script id="__NEXT_DATA__" type="application/json">{{}}</script>')
    assert classify(result=make_result(html=html)) == Outcome.OK


def test_short_legitimate_page_is_ok_with_lower_threshold() -> None:
    """The word minimum is configurable, so a short page can be ok."""
    html: str = page(body="<main><h1>Title</h1><p>A short but real notice for readers today.</p></main>")
    assert classify(result=make_result(html=html)) == Outcome.THIN
    assert classify(result=make_result(html=html), config=ClassifyConfig(min_words=5)) == Outcome.OK


def test_title_mismatch_is_thin() -> None:
    """An og:title that disagrees with h1 and title gives thin."""
    html: str = page(
        head='<meta property="og:title" content="Harbour reopens after repairs">',
        title="Welcome to our portal",
        body=f"<main><h1>Welcome to our portal</h1><p>{LONG}</p></main>",
    )
    result = diagnose(result=make_result(html=html))
    assert result.outcome == Outcome.THIN
    assert "title" in result.reason


def test_expected_title_mismatch_is_thin() -> None:
    """The expected_title argument is compared with h1 and title."""
    html: str = page(title="Cooking tips", body=f"<main><h1>Cooking tips</h1><p>{LONG}</p></main>")
    assert classify(result=make_result(html=html), expected_title="Harbour reopens") == Outcome.THIN
    assert classify(result=make_result(html=html), expected_title="Cooking tips") == Outcome.OK


def test_matching_og_title_with_site_suffix_is_ok() -> None:
    """A title with a site name suffix still matches the og:title."""
    html: str = page(
        head='<meta property="og:title" content="The Harbour Reopens">',
        title="The Harbour Reopens | Coast News",
        body=f"<main><h1>The Harbour Reopens</h1><p>{LONG}</p></main>",
    )
    assert classify(result=make_result(html=html)) == Outcome.OK


@pytest.mark.parametrize(
    "sentence",
    [
        "Researchers study how a captcha affects people who use screen readers.",
        "The word challenge appears in many sports reports, and a cf-chl style name is not prose.",
        "Just a moment, the editor wrote, and then the story began.",
        "Readers can subscribe to continue reading other stories on our site.",
    ],
)
def test_marker_words_in_normal_prose_do_not_block(sentence: str) -> None:
    """Marker words in the visible text of a long article never trigger blocked."""
    html: str = page(body=f"<main><h1>Title</h1><p>{sentence} {PROSE * 8}</p></main>")
    assert classify(result=make_result(html=html)) == Outcome.OK


def test_recaptcha_in_comment_form_of_long_article_is_ok() -> None:
    """A long article with a captcha widget in its comment form is ok."""
    html: str = page(body=f'<main><p>{LONG * 3}</p></main><div class="g-recaptcha"></div>')
    assert classify(result=make_result(html=html)) == Outcome.OK


def test_challenge_threshold_flips_result() -> None:
    """The same markup is blocked under a high challenge threshold and ok under a low one."""
    html: str = page(body=f'<main><p>{words(count=90)}</p></main><div id="cf-chl-widget"></div>')
    assert classify(result=make_result(html=html)) == Outcome.BLOCKED
    assert classify(result=make_result(html=html), config=ClassifyConfig(challenge_max_words=50)) == Outcome.OK


def test_reason_is_plain_text() -> None:
    """The diagnosis carries a reason a person can read."""
    reason: str = diagnose(result=make_result(html="", status=429)).reason
    assert reason == "status 429 blocks the request"
