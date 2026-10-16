"""Tests for the download helper: caching and error messages, without the internet."""

import io
import urllib.error

import pytest

from sl_economy_mcp import fetch as fetch_module
from sl_economy_mcp.errors import SourceUnavailable
from sl_economy_mcp.fetch import cached, fetch
from sl_economy_mcp.series import fisher_real_rate
from sl_economy_mcp.tables import number


@pytest.fixture
def fake_internet(monkeypatch):
    """Replace the real download with one that counts how often it is called."""
    monkeypatch.setattr(fetch_module, "_cache", {})
    requests = []

    class FakeResponse(io.BytesIO):
        def geturl(self):
            return "https://example.test/landed-here"

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse(b"hello")

    monkeypatch.setattr(fetch_module.urllib.request, "urlopen", fake_urlopen)
    return requests


def test_second_request_for_same_page_uses_the_cache(fake_internet):
    first = fetch("https://example.test/page")
    second = fetch("https://example.test/page")
    assert first.text == "hello"
    assert first.url == "https://example.test/landed-here"  # after any redirects
    assert second is first
    assert len(fake_internet) == 1


def test_different_form_values_are_downloaded_separately(fake_internet):
    fetch("https://example.test/form", form={"currency": "USD"})
    fetch("https://example.test/form", form={"currency": "GBP"})
    fetch("https://example.test/form", form={"currency": "USD"})
    assert len(fake_internet) == 2
    assert fake_internet[0].data == b"currency=USD"


def test_requests_identify_the_project(fake_internet):
    fetch("https://example.test/page")
    assert fake_internet[0].get_header("User-agent").startswith("sl-economy-mcp/")


def test_network_failure_becomes_a_readable_error(monkeypatch):
    monkeypatch.setattr(fetch_module, "_cache", {})

    def broken_urlopen(request, timeout):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(fetch_module.urllib.request, "urlopen", broken_urlopen)
    with pytest.raises(SourceUnavailable, match="Could not reach CBSL"):
        fetch("https://example.test/page")


def test_slow_pages_can_be_kept_longer(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(fetch_module.time, "monotonic", lambda: clock[0])
    downloads = []

    def get_page():
        downloads.append(1)
        return "page"

    cached(("slow",), get_page, seconds=3600)
    clock[0] += 30 * 60  # half an hour later: still fresh
    cached(("slow",), get_page, seconds=3600)
    assert len(downloads) == 1
    clock[0] += 31 * 60  # just over the hour: fetched again
    cached(("slow",), get_page, seconds=3600)
    assert len(downloads) == 2


def test_fisher_real_rate_matters_most_when_inflation_is_high():
    assert fisher_real_rate(11.04, 8.0) == 2.81  # simple subtraction gives 3.04
    assert fisher_real_rate(28.0, 60.0) == -20.0  # simple subtraction gives -32
    assert fisher_real_rate(5.0, 0.0) == 5.0


def test_an_oversized_download_is_refused(fake_internet, monkeypatch):
    monkeypatch.setattr(fetch_module, "MAX_BYTES", 3)  # the fake page says "hello", 5 bytes
    with pytest.raises(SourceUnavailable, match="far more than this page should be"):
        fetch("https://example.test/page")


def test_errors_name_the_site_that_failed(monkeypatch):
    def broken_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(fetch_module.urllib.request, "urlopen", broken_urlopen)
    with pytest.raises(SourceUnavailable, match=r"^The Treasury returned an error \(HTTP 502\)"):
        fetch_module.download("https://example.test/file", site="The Treasury")


@pytest.mark.parametrize("cell", ["nan", "inf", "1e5", "11..04", "8.", "n/a", "12%"])
def test_only_plain_numbers_are_read_as_numbers(cell):
    with pytest.raises(ValueError):
        number(cell)


def test_plain_numbers_blanks_and_dashes():
    assert [number(cell) for cell in ["11.04", "-0.30", "2,100.00", "7", "", "-"]] == [
        11.04, -0.3, 2100.0, 7.0, None, None,
    ]  # fmt: skip
