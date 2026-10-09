"""Downloading pages from CBSL: one place for the cache, User-Agent and errors.

Every tool goes through `fetch()` so that they all behave the same way:
- we identify ourselves honestly with a User-Agent,
- we keep each page for a few minutes so repeated questions don't hammer CBSL,
- network problems become one clear, readable error.
"""

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import __version__
from .errors import SourceUnavailable

USER_AGENT = f"sl-economy-mcp/{__version__} (unofficial open-source MCP server)"
TIMEOUT_SECONDS = 20
CACHE_SECONDS = 5 * 60

# Sri Lanka is UTC+5:30 all year round (no daylight saving).
SRI_LANKA_TIME = timezone(timedelta(hours=5, minutes=30), "Asia/Colombo")


@dataclass(frozen=True)
class Page:
    url: str
    body: bytes
    fetched_at: datetime  # timezone-aware, UTC

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def stamp(self, source_url: str | None = None) -> dict:
        """Source details that every tool attaches to its answer.

        `source_url` lets a tool point at the page a person would open in a
        browser when that differs from the address the data was read from.
        """
        return {
            "source_url": source_url or self.url,
            "fetched_at_utc": self.fetched_at.isoformat(timespec="seconds"),
            "fetched_at_sri_lanka": self.fetched_at.astimezone(SRI_LANKA_TIME).isoformat(
                timespec="seconds"
            ),
        }


_cache: dict[tuple, tuple[float, Page]] = {}


def fetch(url: str, form: dict | None = None) -> Page:
    """Download `url`, or return the copy from the last few minutes.

    Pass `form` to submit a search form (an HTTP POST) instead of simply
    opening the page. Different form values are cached separately.
    """
    data = urllib.parse.urlencode(form).encode() if form else None
    key = (url, data)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        raise SourceUnavailable(
            f"CBSL returned an error (HTTP {error.code}) for {url}. "
            "The site may be down or the page may have moved."
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise SourceUnavailable(
            f"Could not reach CBSL at {url}. Check the internet connection, "
            "or CBSL's website may be down. Try again in a few minutes."
        ) from error

    page = Page(url=url, body=body, fetched_at=datetime.now(timezone.utc))
    _cache[key] = (time.monotonic(), page)
    return page
