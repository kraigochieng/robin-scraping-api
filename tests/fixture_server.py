"""A local HTTP server for tests. It serves static fixtures and counts hits per path.

It also acts as a plain HTTP proxy: a request whose path is an absolute URL is served
as that URL path and counted as proxied. No test ever contacts a real host.
"""

import threading
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES_DIR: Path = Path(__file__).parent / "fixtures"
HTML: str = "text/html; charset=utf-8"


@dataclass
class Reply:
    """A response the fixture server sends."""

    body: str = ""
    status: int = 200
    content_type: str = HTML
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class IncomingRequest:
    """What a route function may look at."""

    path: str
    query: dict[str, list[str]]
    via_proxy: bool


Route = Callable[[IncomingRequest], Reply]


def read_fixture(*, name: str) -> str:
    """Return the text of a fixture file."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def static(*, name: str, status: int = 200, content_type: str = HTML) -> Route:
    """Return a route that serves one fixture file."""
    return lambda request: Reply(
        body=read_fixture(name=name), status=status, content_type=content_type
    )


def redirect(*, location: str) -> Route:
    """Return a route that answers 302 to the location."""
    return lambda request: Reply(status=302, headers={"Location": location})


def default_routes() -> dict[str, Route]:
    """Return the routes of the standard fixture set."""
    return {
        "/article/plain": static(name="plain_article.html"),
        "/article/jsonld": static(name="jsonld_article.html"),
        "/article/next": static(name="next_article.html"),
        "/spa": static(name="spa_shell.html"),
        "/api/article.json": static(name="article.json", content_type="application/json"),
        "/challenge/200": static(name="challenge.html"),
        "/challenge/403": static(name="challenge.html", status=403),
        "/status/429": static(name="rate_limited.html", status=429),
        "/status/503": static(name="unavailable.html", status=503),
        "/status/404": static(name="thin.html", status=404),
        "/paywall": static(name="paywall.html"),
        "/thin": static(name="thin.html"),
        "/login": static(name="login.html"),
        "/redirect/start": redirect(location="/redirect/middle"),
        "/redirect/middle": redirect(location="/article/plain"),
        "/amp-source/story": static(name="amp_source.html"),
        "/amp/story": static(name="amp_page.html"),
        "/rss-source/story-two": static(name="rss_source.html"),
        "/feed.xml": static(name="feed.xml", content_type="application/rss+xml"),
        "/wp-source/my-post": static(name="wp_source.html"),
        "/wp-json/wp/v2/posts": static(name="wp_posts.json", content_type="application/json"),
        "/assets/pixel.png": lambda request: Reply(body="png", content_type="image/png"),
        "/assets/font.woff2": lambda request: Reply(body="font", content_type="font/woff2"),
        "/needs-proxy": lambda request: (
            Reply(body=read_fixture(name="plain_article.html"))
            if request.via_proxy
            else Reply(body=read_fixture(name="challenge.html"), status=403)
        ),
    }


class FixtureServer:
    """A running server with hit counters. Use as a context manager."""

    def __init__(self, *, routes: dict[str, Route]) -> None:
        """Create the server on a random loopback port."""
        self.routes: dict[str, Route] = routes
        self.hits: Counter[str] = Counter()
        self.proxied_hits: Counter[str] = Counter()
        self._lock: threading.Lock = threading.Lock()
        server: "FixtureServer" = self

        class Handler(BaseHTTPRequestHandler):
            """Answer GET requests from the route table."""

            def do_GET(self) -> None:  # noqa: N802 - name is fixed by the base class
                """Serve one request and count it."""
                via_proxy: bool = self.path.startswith("http://")
                parsed = urlparse(self.path)
                with server._lock:
                    server.hits[parsed.path] += 1
                    if via_proxy:
                        server.proxied_hits[parsed.path] += 1
                route: Route | None = server.routes.get(parsed.path)
                if route is None:
                    reply = Reply(body="not found", status=404)
                else:
                    reply = route(
                        IncomingRequest(
                            path=parsed.path, query=parse_qs(parsed.query), via_proxy=via_proxy
                        )
                    )
                payload: bytes = reply.body.encode("utf-8")
                self.send_response(reply.status)
                self.send_header("Content-Type", reply.content_type)
                self.send_header("Content-Length", str(len(payload)))
                for name, value in reply.headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                """Keep test output quiet."""

        self._httpd: ThreadingHTTPServer = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url: str = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread: threading.Thread = threading.Thread(
            target=lambda: self._httpd.serve_forever(poll_interval=0.01), daemon=True
        )

    def start(self) -> None:
        """Start serving in a background thread."""
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and free the port."""
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def total_hits(self) -> int:
        """Return the number of requests the server answered."""
        return sum(self.hits.values())


def serve(*, routes: dict[str, Route] | None = None) -> Iterator[FixtureServer]:
    """Yield a started server and stop it afterwards."""
    server: FixtureServer = FixtureServer(routes=routes or default_routes())
    server.start()
    try:
        yield server
    finally:
        server.stop()
