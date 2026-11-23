"""Diagnose a fetch result. Pure: no input or output, no clock."""

import re

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict

from robin_scraping_api.tiers.models import FetchResult, Outcome

BLOCKING_STATUSES: frozenset[int] = frozenset({403, 429, 503})
CHALLENGE_TITLES: tuple[str, ...] = (
    "just a moment",
    "attention required",
    "verify you are human",
    "are you a robot",
)
CHALLENGE_ATTRIBUTE_MARKERS: tuple[str, ...] = (
    "cf-chl",
    "cf-browser-verification",
    "challenge-form",
    "g-recaptcha",
    "h-captcha",
    "cf-turnstile",
    "px-captcha",
    "captcha-container",
)
CHALLENGE_SCRIPT_HOSTS: tuple[str, ...] = (
    "challenges.cloudflare.com",
    "captcha-delivery.com",
)
WALL_ATTRIBUTE_MARKERS: tuple[str, ...] = (
    "paywall",
    "regwall",
    "login-wall",
    "subscribe-wall",
)
WALL_PHRASES: tuple[str, ...] = (
    "sign in to continue",
    "log in to continue",
    "subscribe to continue reading",
    "subscribe to read",
    "create a free account to continue",
    "register to continue",
)
SPA_ROOT_IDS: tuple[str, ...] = ("root", "app", "__next", "__nuxt")
NOSCRIPT_PATTERN: re.Pattern[str] = re.compile(
    r"(enable|requires?|turn on)\s+javascript", re.IGNORECASE
)
NON_CONTENT_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "noscript",
    "template",
    "nav",
    "header",
    "footer",
    "aside",
)


class ClassifyConfig(BaseModel):
    """Thresholds of the classifier. All of them are configurable."""

    model_config = ConfigDict(frozen=True)

    min_words: int = 50
    spa_root_max_words: int = 20
    challenge_max_words: int = 200
    wall_max_words: int = 400
    wall_phrase_max_words: int = 120
    password_page_max_words: int = 150
    title_overlap_threshold: float = 0.3


class Diagnosis(BaseModel):
    """The outcome of a classification and the reason in plain words."""

    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    reason: str


def classify(
    *,
    result: FetchResult,
    expected_title: str | None = None,
    config: ClassifyConfig | None = None,
) -> Outcome:
    """Return the outcome of a fetch result."""
    return diagnose(result=result, expected_title=expected_title, config=config).outcome


def diagnose(
    *,
    result: FetchResult,
    expected_title: str | None = None,
    config: ClassifyConfig | None = None,
) -> Diagnosis:
    """Return the outcome and the reason, from status, markers, text size and titles."""
    settings: ClassifyConfig = config or ClassifyConfig()

    if result.status in BLOCKING_STATUSES:
        return Diagnosis(
            outcome=Outcome.BLOCKED, reason=f"status {result.status} blocks the request"
        )
    if result.status < 200 or result.status >= 400:
        return Diagnosis(
            outcome=Outcome.ERROR, reason=f"status {result.status} is an error"
        )

    soup: BeautifulSoup = BeautifulSoup(result.html, "html.parser")
    words: int = _visible_word_count(soup=soup)

    if words < settings.challenge_max_words and _has_challenge_marker(soup=soup):
        return Diagnosis(
            outcome=Outcome.BLOCKED, reason="the page has anti-bot challenge markers"
        )

    wall_reason: str | None = _login_wall_reason(soup=soup, words=words, config=settings)
    if wall_reason:
        return Diagnosis(outcome=Outcome.LOGIN_WALL, reason=wall_reason)

    js_reason: str | None = _needs_js_reason(soup=soup, words=words, config=settings)
    if js_reason:
        return Diagnosis(outcome=Outcome.NEEDS_JS, reason=js_reason)

    if words < settings.min_words:
        return Diagnosis(
            outcome=Outcome.THIN,
            reason=f"the page has {words} words, below the minimum of {settings.min_words}",
        )

    if _title_mismatch(soup=soup, expected_title=expected_title, config=settings):
        return Diagnosis(
            outcome=Outcome.THIN, reason="the page title does not match the expected title"
        )

    return Diagnosis(outcome=Outcome.OK, reason=f"the page has {words} words of content")


def _visible_word_count(*, soup: BeautifulSoup) -> int:
    """Count the words of the page text, without scripts, navigation and footers."""
    body: Tag | BeautifulSoup = soup.find("body") or soup
    copy: BeautifulSoup = BeautifulSoup(str(body), "html.parser")
    for tag in copy(list(NON_CONTENT_TAGS)):
        tag.decompose()
    return len(copy.get_text(separator=" ", strip=True).split())


def _attribute_tokens(*, tag: Tag) -> str:
    """Join the id and class values of an element in lowercase."""
    class_value: str | list[str] = tag.get("class") or ""
    class_text: str = class_value if isinstance(class_value, str) else " ".join(class_value)
    return f"{tag.get('id') or ''} {class_text}".lower()


def _has_attribute_marker(*, soup: BeautifulSoup, markers: tuple[str, ...]) -> bool:
    """Return True when any element id or class contains one of the markers."""
    return any(
        marker in _attribute_tokens(tag=tag)
        for tag in soup.find_all(True)
        for marker in markers
    )


def _has_challenge_marker(*, soup: BeautifulSoup) -> bool:
    """Return True for a challenge title, challenge element or challenge script."""
    title: str = (soup.title.get_text() if soup.title else "").strip().lower()
    if any(title.startswith(marker) for marker in CHALLENGE_TITLES):
        return True
    if _has_attribute_marker(soup=soup, markers=CHALLENGE_ATTRIBUTE_MARKERS):
        return True
    sources: list[str] = [str(script.get("src") or "") for script in soup.find_all("script")]
    return any(host in source for source in sources for host in CHALLENGE_SCRIPT_HOSTS)


def _login_wall_reason(
    *, soup: BeautifulSoup, words: int, config: ClassifyConfig
) -> str | None:
    """Return the reason when the page is a login wall or a paywall stub, else None."""
    if words < config.wall_max_words and _has_attribute_marker(
        soup=soup, markers=WALL_ATTRIBUTE_MARKERS
    ):
        return "the page has a paywall or login wall marker and little text"
    if words < config.password_page_max_words and soup.find("input", {"type": "password"}):
        return "the page is a short page with a password field"
    text: str = soup.get_text(separator=" ", strip=True).lower()
    if words < config.wall_phrase_max_words and any(phrase in text for phrase in WALL_PHRASES):
        return "the page asks the reader to sign in or subscribe and has little text"
    return None


def _needs_js_reason(
    *, soup: BeautifulSoup, words: int, config: ClassifyConfig
) -> str | None:
    """Return the reason when the page needs JavaScript to show content, else None."""
    if words >= config.min_words:
        return None
    for noscript in soup.find_all("noscript"):
        if NOSCRIPT_PATTERN.search(noscript.get_text()):
            return "the page asks the reader to enable JavaScript"
    for root_id in SPA_ROOT_IDS:
        root: Tag | None = soup.find(id=root_id)
        if root is not None and len(root.get_text(separator=" ", strip=True).split()) < config.spa_root_max_words:
            return f"the #{root_id} element is empty, so JavaScript must render the page"
    return None


def _normalised_words(*, text: str) -> set[str]:
    """Return the set of lowercase alphanumeric words of a text."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _titles_match(*, first: str, second: str, threshold: float) -> bool:
    """Return True when one title contains the other or the word overlap is high."""
    first_words: set[str] = _normalised_words(text=first)
    second_words: set[str] = _normalised_words(text=second)
    if not first_words or not second_words:
        return True
    if first_words <= second_words or second_words <= first_words:
        return True
    overlap: float = len(first_words & second_words) / len(first_words | second_words)
    return overlap >= threshold


def _title_mismatch(
    *, soup: BeautifulSoup, expected_title: str | None, config: ClassifyConfig
) -> bool:
    """Return True when the page titles disagree with the expected or og:title."""
    og_tag: Tag | None = soup.find("meta", property="og:title")
    og_title: str = str(og_tag.get("content") or "").strip() if og_tag else ""
    expected: str = (expected_title or og_title).strip()
    if not expected:
        return False
    heading: Tag | None = soup.find("h1")
    candidates: list[str] = [
        value
        for value in (
            heading.get_text(strip=True) if heading else "",
            soup.title.get_text(strip=True) if soup.title else "",
        )
        if value
    ]
    if not candidates:
        return False
    return not any(
        _titles_match(
            first=expected, second=candidate, threshold=config.title_overlap_threshold
        )
        for candidate in candidates
    )
