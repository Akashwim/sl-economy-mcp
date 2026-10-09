"""Tests for the Data Library reader and the interest rate tool, without the internet."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sl_economy_mcp import data_library, interest_rates
from sl_economy_mcp.errors import InvalidRequest, NoData, PageChanged
from sl_economy_mcp.fetch import Page

FIXTURES = Path(__file__).parent / "fixtures"
LENDING = (FIXTURES / "library_lending_2026-08-01_to_10-09.html").read_text()
LENDING_EMPTY = (FIXTURES / "library_lending_empty.html").read_text()
TREASURY = (FIXTURES / "library_treasury_2026-06-01_to_07-31.html").read_text()

LENDING_TITLE = interest_rates.REPORTS["lending"].title
TREASURY_TITLE = interest_rates.REPORTS["treasury_bills"].title


# --- Reading the Data Library's pages -------------------------------------


def test_finds_the_hidden_fields_the_library_wants_back():
    fields = data_library.hidden_fields(LENDING_EMPTY)
    assert fields["__VIEWSTATE"].startswith("/wEP")
    assert "__EVENTVALIDATION" in fields
    assert fields["ctl00$ContentPlaceHolder1$hfGridHtml"] == ""  # present but empty


def test_reads_lending_rows_oldest_first_with_blanks():
    rows = data_library.parse_grid(LENDING, LENDING_TITLE, 8)
    assert len(rows) == 10
    assert rows[0][0] < rows[-1][0]
    day, figures = rows[-1]
    assert day == date(2026, 10, 2)
    assert figures[1] == 11.04  # weekly prime lending rate
    assert figures[0] is None  # monthly average lending rate, not out yet


def test_reads_treasury_bill_yields():
    rows = data_library.parse_grid(TREASURY, TREASURY_TITLE, 16)
    day, figures = rows[-1]
    assert day == date(2026, 7, 9)
    assert figures[:3] == [10.21, 10.30, 10.21]


def test_no_records_is_an_empty_list():
    assert data_library.parse_grid(LENDING_EMPTY, LENDING_TITLE, 8) == []


def test_clear_error_when_a_different_page_comes_back():
    with pytest.raises(PageChanged, match="did not return"):
        data_library.parse_grid("<html><body>Please log in</body></html>", LENDING_TITLE, 8)
    with pytest.raises(PageChanged, match="did not return"):
        data_library.parse_grid(TREASURY, LENDING_TITLE, 8)  # the wrong report


def test_clear_error_when_cbsl_adds_or_removes_a_column():
    with pytest.raises(PageChanged, match="Unexpected row"):
        data_library.parse_grid(LENDING, LENDING_TITLE, 7)


def test_search_arrives_by_the_front_door_then_submits_the_dates(monkeypatch):
    calls = []

    def fake_download(url, form=None, session=None, timeout=None):
        calls.append((url, form, session))
        landed = "https://www.cbsl.lk/eResearch/Modules/RD/SearchPages/CMB_LendingAndDeposit.aspx"
        return Page(landed, LENDING_EMPTY.encode(), datetime.now(timezone.utc))

    monkeypatch.setattr(data_library, "download", fake_download)
    data_library._search(6277, date(2026, 8, 1), date(2026, 10, 9))

    (front_url, front_form, first_session), (search_url, form, second_session) = calls
    assert front_url.endswith("ReportId=6277") and front_form is None
    assert search_url.endswith("CMB_LendingAndDeposit.aspx")  # where the front door led
    assert form["ctl00$ContentPlaceHolder1$txtFrom"] == "2026-08-01"
    assert form["ctl00$ContentPlaceHolder1$txtTo"] == "2026-10-09"
    assert "__VIEWSTATE" in form
    assert first_session is second_session  # same visit, so the cookie is sent back


# --- The tool -------------------------------------------------------------


@pytest.fixture
def fake_library(monkeypatch):
    """Make the Data Library return saved pages. `today` is fixed for the 'behind' check."""
    pages = {6277: LENDING, 6169: TREASURY}
    searches = []

    def fake_search(report_id, start, end):
        searches.append((report_id, start, end))
        return Page("unused", pages[report_id].encode(), datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc))

    monkeypatch.setattr(data_library, "search", fake_search)
    monkeypatch.setattr(interest_rates, "today_in_sri_lanka", lambda: date(2026, 10, 9))
    return pages, searches


def test_lending_rates_with_summary(fake_library):
    result = interest_rates.get_interest_rates("lending", "2026-08-01", "2026-10-09")
    prime = result["rates"]["prime_lending_rate"]
    assert prime["summary"]["last"] == {"date": "2026-10-02", "value": 11.04}
    assert prime["values"]["2026-09-25"] == 10.94
    first = prime["summary"]["first"]["value"]
    assert prime["summary"]["change_percentage_points"] == round(11.04 - first, 2)
    assert result["latest_data_date"] == "2026-10-02"
    assert "note" not in result  # a week old is normal for weekly data
    assert result["source_url"].endswith("ReportId=6277")
    assert "disclaimer" in result


def test_monthly_columns_keep_their_own_dates(fake_library):
    result = interest_rates.get_interest_rates("lending", "2026-08-01", "2026-10-09")
    monthly = result["rates"]["average_lending_rate"]["values"]
    weekly = result["rates"]["prime_lending_rate"]["values"]
    assert 0 < len(monthly) < len(weekly)


def test_treasury_bills_flagged_when_the_library_is_behind(fake_library):
    result = interest_rates.get_interest_rates("treasury_bills", "2026-06-01", "2026-10-09")
    assert result["rates"]["364_day"]["summary"]["last"] == {"date": "2026-07-09", "value": 10.21}
    assert result["latest_data_date"] == "2026-07-09"
    assert "running behind" in result["note"]


def test_default_range_is_the_last_year(fake_library):
    _, searches = fake_library
    interest_rates.get_interest_rates()
    assert searches == [(6277, date(2025, 10, 9), date(2026, 10, 9))]


def test_long_series_are_listed_as_month_ends():
    weekly = [(date.fromordinal(date(2020, 1, 3).toordinal() + 7 * week), 10.0) for week in range(200)]
    shown = interest_rates.present(weekly, "meaning")
    assert shown["summary"]["observations"] == 200
    assert len(shown["values"]) < 50
    assert "last value of each month" in shown["values_note"]


def test_unknown_series_lists_the_choices(fake_library):
    with pytest.raises(InvalidRequest, match="lending, treasury_bills"):
        interest_rates.get_interest_rates("mortgages")


def test_no_data_is_explained(fake_library):
    pages, _ = fake_library
    pages[6277] = LENDING_EMPTY
    with pytest.raises(NoData, match="no lending rates"):
        interest_rates.get_interest_rates("lending", "2031-01-01", "2031-02-01")
