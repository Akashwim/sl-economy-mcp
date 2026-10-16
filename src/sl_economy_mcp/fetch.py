"""Downloading pages and files: one place for the cache, User-Agent and errors.

Every tool goes through here so that they all behave the same way:
- we identify ourselves honestly with a User-Agent,
- we keep each page for a few minutes so repeated questions don't hammer the
  website they came from,
- network problems become one clear, readable error.
"""

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from . import __version__
from .dates import SRI_LANKA_TIME
from .errors import SourceUnavailable

USER_AGENT = f"sl-economy-mcp/{__version__} (unofficial open-source MCP server)"
TIMEOUT_SECONDS = 20
CACHE_SECONDS = 5 * 60
MAX_BYTES = 20_000_000  # the largest real download is about 0.6 MB; anything far bigger is wrong


@dataclass(frozen=True)
class Page:
    url: str  # where the page ended up, after any redirects
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


def new_session() -> urllib.request.OpenerDirector:
    """A browser-like visit that remembers cookies between requests."""
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor())


def download(
    url: str,
    form: dict | None = None,
    session: urllib.request.OpenerDirector | None = None,
    timeout: int = TIMEOUT_SECONDS,
    site: str = "CBSL",
) -> Page:
    """Get a page from the internet right now, with no cache.

    Pass `form` to submit a search form (an HTTP POST) instead of simply
    opening the page, and `session` when the site needs its cookies back.
    `site` is the website's name, used in the error messages.
    """
    data = urllib.parse.urlencode(form).encode() if form else None
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    open_url = session.open if session else urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise SourceUnavailable(
                    f"{site} sent more than {MAX_BYTES // 1_000_000} MB for {url}, far more "
                    "than this page should be, so it was not read."
                )
            return Page(response.geturl(), body, datetime.now(timezone.utc))
    except urllib.error.HTTPError as error:
        raise SourceUnavailable(
            f"{site} returned an error (HTTP {error.code}) for {url}. "
            "The site may be down or the page may have moved."
        ) from error
    except OSError as error:  # no connection, timed out, connection dropped
        raise SourceUnavailable(
            f"Could not reach {site} at {url}. Check the internet connection, "
            "or the website may be down or slow. Try again in a few minutes."
        ) from error


_cache: dict[tuple, tuple[float, Page]] = {}


def cached(key: tuple, get_page, seconds: int = CACHE_SECONDS) -> Page:
    """The page saved under `key` if it is recent, otherwise whatever `get_page()` returns."""
    saved = _cache.get(key)
    if saved and time.monotonic() - saved[0] < seconds:
        return saved[1]
    page = get_page()
    _cache[key] = (time.monotonic(), page)
    return page


def fetch(url: str, form: dict | None = None) -> Page:
    """Download `url`, or return the copy from the last few minutes.

    Different form values are cached separately.
    """
    key = (url, tuple(sorted(form.items())) if form else None)
    return cached(key, lambda: download(url, form))
