"""Tests for the output renderers."""

from bs4 import BeautifulSoup

from robin_scraping_api.rendering import clean_soup, render_plain_text, render_root


def test_clean_soup_removes_noise() -> None:
    """Nav, scripts, cookie banners and data images are removed."""
    html = '<body><nav>n</nav><script>s</script><div id="cookie-bar">c</div><img src="data:x"><p>keep</p></body>'
    text = clean_soup(soup=BeautifulSoup(html, "html.parser")).get_text(strip=True)
    assert text == "keep"


def test_render_root_formats() -> None:
    """Markdown, html and text renderings."""
    root = BeautifulSoup("<h1>T</h1><p>a</p>", "html.parser")
    assert render_root(root=root, fmt="markdown").startswith("# T")
    assert render_root(root=root, fmt="html") == "<h1>T</h1><p>a</p>"
    assert render_root(root=root, fmt="text") == "T\na"


def test_render_plain_text_html_escapes() -> None:
    """Plain text becomes escaped paragraphs in html format and stays as is otherwise."""
    assert render_plain_text(text="a < b\n\nc", fmt="html") == "<p>a &lt; b</p><p>c</p>"
    assert render_plain_text(text="a\n\nb", fmt="markdown") == "a\n\nb"
    assert render_plain_text(text="a", fmt="text") == "a"
