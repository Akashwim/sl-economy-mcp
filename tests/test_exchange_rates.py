"""Tests for the exchange rate tools.

Nothing here touches the internet. Reading CBSL's pages is tested against
saved copies of real responses, and the two tools are tested with a stand-in
for `fetch` that hands back those saved copies.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sl_economy_mcp import exchange_rates as fx
from sl_economy_mcp.errors import InvalidRequest, NoData, PageChanged
from sl_economy_mcp.fetch import Page

FIXTURES = Path(__file__).parent / "fixtures"


def saved(name: str) -> str:
    return (FIXTURES / name).read_text()


INDICATIVE_USD = saved("indicative_USD_2026-10-01_to_09.html")
TT_USD = saved("tt_USD_2026-10-01_to_09.html")
EMPTY = saved("indicative_USD_weekend_empty.html")


# --- Reading CBSL's pages -------------------------------------------------


def test_reads_currency_list_from_indicative_form():
    names = fx.parse_currencies(saved("indicative_form.html"))
    assert len(names) == 55
    assert names["USD"] == "US Dollar"
    assert names["MYR"] == "Malaysia Ringgit"  # CBSL has a double space here


def test_reads_currency_list_from_tt_form():
    assert sorted(fx.parse_currencies(saved("tt_form.html"))) == [
        "AUD", "CAD", "CHF", "CNY", "EUR", "GBP", "JPY", "SGD", "USD",
    ]  # fmt: skip


def test_reads_indicative_rates_oldest_first():
    rows = fx.parse_rate_table(INDICATIVE_USD, fx.INDICATIVE.heading)
    assert len(rows) == 7  # 3 and 4 October 2026 were a weekend
    assert rows[0][:2] == (date(2026, 10, 1), 330.7005)
    assert rows[-1][:2] == (date(2026, 10, 9), 330.9617)


def test_reads_buying_and_selling_rates():
    rows = fx.parse_rate_table(TT_USD, fx.TT.heading)
    assert rows[-1] == (date(2026, 10, 9), 326.4384, 335.4464)


def test_no_results_is_an_empty_list_not_an_error():
    assert fx.parse_rate_table(EMPTY, fx.INDICATIVE.heading) == []


def test_clear_error_when_results_page_changes():
    with pytest.raises(PageChanged):
        fx.parse_rate_table("<html><body>Site under maintenance</body></html>", "-> LKR")


def test_clear_error_when_currency_list_is_missing():
    with pytest.raises(PageChanged):
        fx.parse_currencies("<html><body>Site under maintenance</body></html>")


# --- Working with a series of rates ---------------------------------------

SERIES = [
    (date(2026, 1, 30), 300.0),
    (date(2026, 2, 2), 310.0),
    (date(2026, 2, 27), 290.0),
    (date(2026, 3, 2), 315.0),
]


def test_summary_of_a_series():
    summary = fx.summarise(SERIES, "USD")
    assert summary["first"] == {"date": "2026-01-30", "rate": 300.0}
    assert summary["last"] == {"date": "2026-03-02", "rate": 315.0}
    assert summary["change_percent"] == 5.0
    assert summary["direction"] == "USD became more expensive in rupees"
    assert summary["high"] == {"date": "2026-03-02", "rate": 315.0}
    assert summary["low"] == {"date": "2026-02-27", "rate": 290.0}
    assert summary["average"] == 303.75
    assert summary["business_days"] == 4


def test_falling_rate_is_reported_as_cheaper():
    summary = fx.summarise([(date(2026, 1, 1), 400.0), (date(2026, 1, 2), 300.0)], "GBP")
    assert summary["change_percent"] == -25.0
    assert summary["direction"] == "GBP became cheaper in rupees"


def test_month_ends_keeps_last_rate_of_each_month():
    assert fx.month_ends(SERIES) == [
        (date(2026, 1, 30), 300.0),
        (date(2026, 2, 27), 290.0),
        (date(2026, 3, 2), 315.0),
    ]


def test_bad_date_gets_a_helpful_message():
    with pytest.raises(InvalidRequest, match="year-month-day"):
        fx.parse_day("9 October 2026")


# --- The two tools, with a stand-in for the internet ----------------------


@pytest.fixture
def fake_cbsl(monkeypatch):
    """Make `fetch` return saved pages and record which forms were submitted."""
    submitted = []
    pages = {
        fx.INDICATIVE.form_url: saved("indicative_form.html"),
        fx.TT.form_url: saved("tt_form.html"),
        fx.INDICATIVE.results_url: INDICATIVE_USD,
        fx.TT.results_url: TT_USD,
    }

    def fake_fetch(url, form=None):
        if form:
            submitted.append(form)
        return Page(url, pages[url].encode(), datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc))

    monkeypatch.setattr(fx, "fetch", fake_fetch)
    return pages, submitted


def test_rate_on_a_business_day(fake_cbsl):
    result = fx.get_exchange_rate("usd", "2026-10-09")
    assert result["currency"] == "USD"
    assert result["data_date"] == "2026-10-09"
    assert result["indicative_rate"] == 330.9617
    assert result["bank_tt_rates"]["buy"] == 326.4384
    assert result["bank_tt_rates"]["sell"] == 335.4464
    assert "note" not in result
    assert result["source_url"] == fx.INDICATIVE.public_url
    assert result["fetched_at_sri_lanka"] == "2026-10-09T13:30:00+05:30"
    assert "disclaimer" in result


def test_weekend_falls_back_to_the_friday_before(fake_cbsl):
    result = fx.get_exchange_rate("USD", "2026-10-04")  # a Sunday
    assert result["requested_date"] == "2026-10-04"
    assert result["data_date"] == "2026-10-02"
    assert result["indicative_rate"] == 330.6231
    assert result["bank_tt_rates"]["buy"] == 326.1715
    assert "most recent earlier business day" in result["note"]


def test_form_is_submitted_with_the_right_currency_and_dates(fake_cbsl):
    _, submitted = fake_cbsl
    fx.get_exchange_rate("USD", "2026-10-09")
    assert submitted[0]["chk_cur[]"] == "USD~US Dollar"
    assert submitted[0]["txtStart"] == "2026-09-25"
    assert submitted[0]["txtEnd"] == "2026-10-09"


def test_bank_rates_not_out_yet_are_explained(fake_cbsl):
    pages, _ = fake_cbsl
    pages[fx.TT.results_url] = TT_USD.replace("2026-10-09", "2026-09-30")  # today's row missing
    result = fx.get_exchange_rate("USD", "2026-10-09")
    assert result["indicative_rate"] == 330.9617
    assert "Not published for 2026-10-09" in result["bank_tt_rates"]


def test_currency_without_bank_rates_says_so(fake_cbsl):
    result = fx.get_exchange_rate("INR", "2026-10-09")
    assert "Not published for this currency" in result["bank_tt_rates"]


def test_unknown_currency_lists_what_is_available(fake_cbsl):
    with pytest.raises(InvalidRequest, match="Available codes: AED, AUD"):
        fx.get_exchange_rate("XYZ")


def test_no_data_is_explained(fake_cbsl):
    pages, _ = fake_cbsl
    pages[fx.INDICATIVE.results_url] = EMPTY
    with pytest.raises(NoData, match="2010-05-07"):
        fx.get_exchange_rate("USD", "2009-01-01")


def test_history_lists_daily_rates_with_summary(fake_cbsl):
    result = fx.get_exchange_rate_history("USD", "2026-10-01", "2026-10-09")
    assert result["interval"] == "daily"
    assert list(result["rates"]) == [
        "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06",
        "2026-10-07", "2026-10-08", "2026-10-09",
    ]  # fmt: skip
    assert result["rates"]["2026-10-05"] == 330.6009
    assert result["summary"]["change_percent"] == 0.08  # 330.7005 -> 330.9617
    assert result["summary"]["business_days"] == 7


def test_history_can_be_monthly(fake_cbsl):
    result = fx.get_exchange_rate_history("USD", "2026-10-01", "2026-10-09", "monthly")
    assert result["rates"] == {"2026-10-09": 330.9617}
    assert result["summary"]["business_days"] == 7  # summary still uses every day


def test_history_warns_when_range_reaches_into_patchy_years(fake_cbsl):
    result = fx.get_exchange_rate_history("USD", "2013-01-01", "2026-10-09")
    assert "missing business days before 2014" in result["note"]
    assert "note" not in fx.get_exchange_rate_history("USD", "2026-10-01", "2026-10-09")


def test_history_rejects_dates_the_wrong_way_round(fake_cbsl):
    with pytest.raises(InvalidRequest, match="on or before"):
        fx.get_exchange_rate_history("USD", "2026-10-09", "2026-10-01")
