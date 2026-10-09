"""Tests for the download helper: caching and error messages, without the internet."""

import io
import urllib.error

import pytest

from sl_economy_mcp import fetch as fetch_module
from sl_economy_mcp.errors import SourceUnavailable
from sl_economy_mcp.fetch import cached, fetch
from sl_economy_mcp.series import fisher_real_rate


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
