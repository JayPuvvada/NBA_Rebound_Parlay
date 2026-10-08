"""Manual NBA proxy connectivity check.

This module is intentionally inert when imported by a test runner. Configure the
proxy through ``NBA_API_PROXY``; credentials must never be committed to source.
"""

import os
from urllib.parse import urlsplit

import requests


TEST_URL = "https://stats.nba.com/stats/commonplayerinfo?PlayerID=1628369"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.nba.com/",
    "Accept": "application/json, text/plain, */*",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Origin": "https://www.nba.com",
}


def main() -> int:
    proxy_url = os.environ.get("NBA_API_PROXY")
    if not proxy_url:
        print("NBA_API_PROXY is not configured; nothing to test.")
        return 2

    parsed = urlsplit(proxy_url)
    safe_host = parsed.hostname or "configured proxy"
    if parsed.port:
        safe_host = f"{safe_host}:{parsed.port}"

    print(f"Testing NBA API connectivity through {safe_host}...")
    try:
        response = requests.get(
            TEST_URL,
            headers=HEADERS,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=10,
        )
        print(f"HTTP {response.status_code}")
        return 0 if response.ok else 1
    except requests.RequestException as exc:
        print(f"Proxy test failed: {exc.__class__.__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
