"""Shared test setup: no test may use the real internet."""

import pytest

from sl_economy_mcp import fetch


@pytest.fixture(autouse=True)
def no_internet(monkeypatch):
    """Fail any test that tries a real download instead of using a saved page."""

    def blocked(*args, **kwargs):
        raise AssertionError("A test tried to use the internet. Give it a saved page instead.")

    monkeypatch.setattr(fetch.urllib.request, "urlopen", blocked)
    monkeypatch.setattr(fetch, "new_session", blocked)
    monkeypatch.setattr(fetch, "_cache", {})
