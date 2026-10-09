"""Tests for the download helper: caching and error messages, without the internet."""

import io
import urllib.error

import pytest

from sl_economy_mcp import fetch as fetch_module
from sl_economy_mcp.errors import SourceUnavailable
from sl_economy_mcp.fetch import fetch


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
