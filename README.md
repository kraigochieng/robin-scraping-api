# robin-scraping-api

`GET /fetch` returns the content of a page. It uses an escalation ladder: the cheapest tier that gives good content wins.

| Tier | Name | What it does |
|---|---|---|
| 1 | http | Scrapling Fetcher with Chrome impersonation, no proxy |
| 2 | alternates | AMP, feed, WordPress API or print copy, only when the HTML points to one |
| 3 | http_proxy | Same as tier 1 through a proxy |
| 4 | browser | Stealth browser, saved profile, no images, fonts or media |
| 5 | browser_stealth_proxy | Headful stealth browser through a proxy |

Each result is diagnosed as `ok`, `needs_js`, `blocked`, `login_wall`, `thin` or `error`. The diagnosis picks the next tier. A tier runs at most once per request.

## Parameters

- `url`, `profile_name`, `clean`, `format`: as before.
- `min_tier`, `max_tier` (1-5): limit the ladder.
- `proxy`: proxy URL for tiers 3 and 5. Overrides `SCRAPING_PROXY`. A proxy in a query string can appear in access logs.
- `debug=true`: adds `attempts` to the response.

## Response fields added

- `tier_used`: the tier that gave the content.
- `outcome`: the diagnosis of the final result.
- `process`: plain-English sentences that tell how the ladder moved.
- `attempts`: one entry per tier run (only with `debug=true`).

## Tests

```
uv run pytest
RUN_BROWSER_TESTS=1 uv run pytest -m browser   # needs: uv run playwright install chromium
```

Tests never use the real internet. An autouse fixture blocks every non-loopback connection.
