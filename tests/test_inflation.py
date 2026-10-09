"""Tests for the inflation tool, against a saved copy of CBSL's table."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sl_economy_mcp import inflation
from sl_economy_mcp.errors import InvalidRequest, NoData, PageChanged
from sl_economy_mcp.fetch import Page

SAVED_TABLE = (Path(__file__).parent / "fixtures" / "inflation_table_2026-10-09.html").read_text()


def test_reads_every_month_oldest_first():
    table = inflation.parse_inflation_table(SAVED_TABLE)
    assert list(table)[0] == "2020-01"
    assert list(table)[-1] == "2026-09"
    assert table["2022-09"] == {  # the peak of the 2022 crisis
        "ccpi_headline": 69.8,
        "ccpi_core": 50.2,
        "ncpi_headline": 73.7,
        "ncpi_core": 64.1,
    }


def test_negative_inflation_and_unpublished_figures():
    table = inflation.parse_inflation_table(SAVED_TABLE)
    assert table["2025-02"]["ccpi_headline"] == -4.2  # deflation
    assert table["2026-09"]["ccpi_headline"] == 8.0
    assert table["2026-09"]["ncpi_headline"] is None  # CBSL shows "-": not out yet


def test_clear_error_when_the_page_changes():
    with pytest.raises(PageChanged):
        inflation.parse_inflation_table("<html><body>Site under maintenance</body></html>")


def test_months_between_crosses_year_ends():
    assert inflation.months_between("2025-11", "2026-02") == [
        "2025-11", "2025-12", "2026-01", "2026-02",
    ]  # fmt: skip


@pytest.fixture
def fake_cbsl(monkeypatch):
    def fake_fetch(url, form=None):
        return Page(url, SAVED_TABLE.encode(), datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc))

    monkeypatch.setattr(inflation, "fetch", fake_fetch)


def test_history_for_a_range_of_months(fake_cbsl):
    result = inflation.get_inflation_history("2026-01", "2026-09")
    assert list(result["months"]) == [f"2026-0{month}" for month in range(1, 10)]
    assert result["ccpi_headline_summary"] == {
        "latest": {"month": "2026-09", "value": 8.0},
        "highest": {"month": "2026-08", "value": 8.0},  # first of two equal months
        "lowest": {"month": "2026-02", "value": 1.6},
    }
    assert "note" not in result
    assert result["source_url"] == inflation.PUBLIC_URL
    assert "disclaimer" in result


def test_everything_available_when_no_months_are_given(fake_cbsl):
    result = inflation.get_inflation_history()
    assert result["requested_start"] == "2020-01"
    assert result["requested_end"] == "2026-09"
    assert result["ccpi_headline_summary"]["highest"] == {"month": "2022-09", "value": 69.8}


def test_gap_in_cbsl_table_is_pointed_out_not_hidden(fake_cbsl):
    # CBSL's page skips 2023 (it sits between two index base years).
    result = inflation.get_inflation_history("2022-06", "2024-06")
    assert "2023-06" not in result["months"]
    assert "no figures for 12 months between 2023-01 and 2023-12" in result["note"]


def test_full_dates_are_accepted_as_months(fake_cbsl):
    result = inflation.get_inflation_history("2026-08-15", "2026-09-30")
    assert list(result["months"]) == ["2026-08", "2026-09"]


def test_bad_month_gets_a_helpful_message(fake_cbsl):
    with pytest.raises(InvalidRequest, match="year-month"):
        inflation.get_inflation_history("Sept 2026")
    with pytest.raises(InvalidRequest, match="year-month"):
        inflation.get_inflation_history("2026-13")


def test_months_the_wrong_way_round(fake_cbsl):
    with pytest.raises(InvalidRequest, match="on or before"):
        inflation.get_inflation_history("2026-09", "2026-01")


def test_range_outside_the_table_is_explained(fake_cbsl):
    with pytest.raises(NoData, match="runs from 2020-01 to 2026-09, but skips 2023-01 to 2023-12"):
        inflation.get_inflation_history("2015-01", "2015-12")
