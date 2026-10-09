"""Tests for the Data Library reader and the interest rate tool, without the internet."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sl_economy_mcp import data_library, inflation, interest_rates
from sl_economy_mcp.errors import InvalidRequest, NoData, PageChanged
from sl_economy_mcp.fetch import Page

FIXTURES = Path(__file__).parent / "fixtures"
LENDING = (FIXTURES / "library_lending_2026-08-01_to_10-09.html").read_text()
LENDING_EMPTY = (FIXTURES / "library_lending_empty.html").read_text()
TREASURY = (FIXTURES / "library_treasury_2026-06-01_to_07-31.html").read_text()
POLICY = (FIXTURES / "library_policy_2026-05-18_to_29.html").read_text()
INFLATION = (FIXTURES / "inflation_table_2026-10-09.html").read_text()

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


def test_typo_in_an_unused_column_does_not_spoil_the_rest():
    # Seen for real on 5 May 2026: CBSL's table had "2508..92" in a column we don't read.
    typo = LENDING.replace("11.04", "11..04")
    assert typo != LENDING
    with pytest.raises(PageChanged, match="Unexpected row"):
        data_library.parse_grid(typo, LENDING_TITLE, 8)  # strict when the column is wanted
    rows = data_library.parse_grid(typo, LENDING_TITLE, 8, wanted={0})
    assert rows[-1][1][1] is None  # skipped, not misread


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
    pages = {6277: LENDING, 6169: TREASURY, 1059: POLICY}
    table = inflation.parse_inflation_table(INFLATION)
    monkeypatch.setattr(inflation, "load_table", lambda: table)
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
    with pytest.raises(InvalidRequest, match="policy, lending, treasury_bills, treasury_bonds"):
        interest_rates.get_interest_rates("mortgages")


def test_no_data_is_explained(fake_library):
    pages, _ = fake_library
    pages[6277] = LENDING_EMPTY
    with pytest.raises(NoData, match="no lending rates"):
        interest_rates.get_interest_rates("lending", "2031-01-01", "2031-02-01")


def test_policy_rates_list_each_change(fake_library):
    result = interest_rates.get_interest_rates("policy", "2026-05-18", "2026-05-29")
    deposit = result["rates"]["standing_deposit_facility_rate"]
    assert deposit["changes"] == [{"date": "2026-05-26", "from": 7.25, "to": 8.25, "change": 1.0}]
    lending = result["rates"]["standing_lending_facility_rate"]
    assert lending["changes"] == [{"date": "2026-05-26", "from": 8.25, "to": 9.25, "change": 1.0}]
    assert "real_rate_latest" not in deposit


def test_a_blank_day_is_not_mistaken_for_a_rate_change(fake_library):
    # CBSL left the lending facility rate blank on 19 May 2026.
    result = interest_rates.get_interest_rates("policy", "2026-05-18", "2026-05-29")
    lending = result["rates"]["standing_lending_facility_rate"]
    assert "2026-05-19" not in lending["values"]
    assert len(lending["changes"]) == 1


def test_policy_range_is_capped_because_the_source_is_slow(fake_library):
    with pytest.raises(InvalidRequest, match="12 months or less"):
        interest_rates.get_interest_rates("policy", "2024-01-01", "2026-10-09")


def test_bond_yields_only_where_cbsl_held_an_auction(fake_library):
    result = interest_rates.get_interest_rates("treasury_bonds", "2026-06-01", "2026-07-31")
    assert result["rates"]["4_year"]["values"]["2026-07-02"] == 11.44
    assert result["rates"]["8_year"]["values"]["2026-07-02"] == 11.88
    assert "30_year" not in result["rates"]  # not auctioned in this period


def test_real_rate_uses_inflation_for_the_same_month(fake_library):
    result = interest_rates.get_interest_rates("treasury_bills", "2026-06-01", "2026-10-09")
    assert result["rates"]["364_day"]["real_rate_latest"] == {
        "value": 2.91,  # 10.21 yield - 7.30 inflation
        "rate": 10.21,
        "rate_date": "2026-07-09",
        "inflation": 7.3,
        "inflation_month": "2026-07",
    }


def test_real_rate_falls_back_to_the_latest_published_month(fake_library):
    # October 2026 inflation is not out yet, so September's is used.
    result = interest_rates.get_interest_rates("lending", "2026-08-01", "2026-10-09")
    real = result["rates"]["prime_lending_rate"]["real_rate_latest"]
    assert real["inflation_month"] == "2026-09"
    assert real["value"] == 3.04  # 11.04 - 8.00


def test_real_rate_is_left_out_when_inflation_is_too_old():
    table = inflation.parse_inflation_table(INFLATION)
    assert interest_rates.real_rate((date(2027, 6, 30), 10.0), table) is None


def test_main_answer_survives_if_inflation_cannot_be_read(fake_library, monkeypatch):
    def down():
        raise PageChanged("inflation table changed")

    monkeypatch.setattr(inflation, "load_table", down)
    result = interest_rates.get_interest_rates("lending", "2026-08-01", "2026-10-09")
    assert result["rates"]["prime_lending_rate"]["summary"]["last"]["value"] == 11.04
    assert "Real rates left out" in result["real_rate_note"]
