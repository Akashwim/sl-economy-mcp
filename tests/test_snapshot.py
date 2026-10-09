"""Tests for the rate window parser.

These run against a saved copy of the real page, so they work offline and
give the same answer every time.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sl_economy_mcp import exchange_rates, inflation, snapshot
from sl_economy_mcp.errors import PageChanged, SourceUnavailable
from sl_economy_mcp.fetch import Page
from sl_economy_mcp.snapshot import parse_rate_window

SAVED_PAGE = (Path(__file__).parent / "fixtures" / "ratewindow_2026-10-09.html").read_text()


def test_reads_all_four_numbers_from_saved_page():
    assert parse_rate_window(SAVED_PAGE) == {
        "ccpi_inflation_percent": 8.00,
        "overnight_policy_rate_percent": 8.75,
        "usd_lkr_tt_buy": 326.4384,
        "usd_lkr_tt_sell": 335.4464,
    }


def test_handles_negative_inflation():
    # Sri Lanka has had deflation before, so a minus sign must survive.
    page = SAVED_PAGE.replace("8.00&nbsp;", "-0.30&nbsp;")
    assert parse_rate_window(page)["ccpi_inflation_percent"] == -0.30


def test_inflation_and_policy_rate_are_not_mixed_up():
    page = SAVED_PAGE.replace("8.00&nbsp;", "1.50&nbsp;").replace("8.75 %", "7.25 %")
    values = parse_rate_window(page)
    assert values["ccpi_inflation_percent"] == 1.50
    assert values["overnight_policy_rate_percent"] == 7.25


def test_clear_error_when_a_number_is_missing():
    with pytest.raises(PageChanged, match="usd_lkr_tt_sell"):
        parse_rate_window(SAVED_PAGE.replace("TT Sell", "Selling"))


def test_clear_error_when_page_is_something_else_entirely():
    with pytest.raises(PageChanged):
        parse_rate_window("<html><body>Site under maintenance</body></html>")


def test_clear_error_when_buy_is_above_sell():
    with pytest.raises(PageChanged, match="buying rate above"):
        parse_rate_window(SAVED_PAGE.replace("326.4384", "999.0"))


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fake_cbsl(monkeypatch):
    """Saved copies of the headline page and the two dated tables it is checked against."""
    table = inflation.parse_inflation_table((FIXTURES / "inflation_table_2026-10-09.html").read_text())
    dated = exchange_rates.parse_rate_table(
        (FIXTURES / "tt_USD_2026-10-01_to_09.html").read_text(), exchange_rates.TT.heading
    )
    page = Page(snapshot.RATE_WINDOW_URL, SAVED_PAGE.encode(), datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(snapshot, "fetch", lambda url, form=None: page)
    monkeypatch.setattr(inflation, "load_table", lambda: table)
    monkeypatch.setattr(exchange_rates, "lookup", lambda form, code, start, end: (dated, page))
    return table


def test_snapshot_adds_real_rate_source_and_time(fake_cbsl):
    result = snapshot.get_snapshot()
    assert result["real_policy_rate_percent"] == 0.75  # 8.75 policy rate - 8.00 inflation
    assert result["real_policy_rate_fisher_percent"] == 0.69  # 1.0875 / 1.08 - 1
    assert result["source_url"] == snapshot.RATE_WINDOW_URL
    assert result["fetched_at_utc"] == "2026-10-09T08:00:00+00:00"
    assert "disclaimer" in result


def test_snapshot_dates_each_figure_from_cbsl_dated_tables(fake_cbsl):
    dates = snapshot.get_snapshot()["data_dates"]
    assert dates["ccpi_inflation_percent"] == "2026-09"
    assert dates["usd_lkr_tt_buy / usd_lkr_tt_sell"] == "2026-10-09"


def test_snapshot_does_not_guess_a_date_when_the_tables_disagree(fake_cbsl):
    fake_cbsl["2026-09"]["ccpi_headline"] = 7.5  # the table no longer matches the headline page
    dates = snapshot.get_snapshot()["data_dates"]
    assert dates["ccpi_inflation_percent"].startswith("not confirmed")


def test_snapshot_still_works_when_a_dated_table_is_down(fake_cbsl, monkeypatch):
    def down():
        raise SourceUnavailable("Could not reach CBSL.")

    monkeypatch.setattr(inflation, "load_table", down)
    result = snapshot.get_snapshot()
    assert result["overnight_policy_rate_percent"] == 8.75
    assert result["data_dates"]["ccpi_inflation_percent"].startswith("not confirmed")
