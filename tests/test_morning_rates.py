"""Tests for the Morning Sheet, without the internet.

Every source is replaced by a saved copy of its real page: the CBSL pages of
9 October 2026, the Ministry's daily report of 13 October and its Treasury
bill results page of 16 October (newest auction: 14 October). "Today" is
fixed at 9 October 2026, the day the CBSL pages were saved, unless a test
says otherwise.

The saved daily report (trading on 12 October) is from before the newest
auction, so by default the sheet shows the auction before it, 7 October,
which that report confirms. `confirmed_by_a_later_report` supplies one that
covers the newest auction.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sl_economy_mcp import bill_auctions, data_library, exchange_rates, inflation, morning_rates, snapshot, treasury_yields
from sl_economy_mcp.errors import PageChanged, SourceUnavailable
from sl_economy_mcp.fetch import Page
from sl_economy_mcp.tables import heading_cells
from sl_economy_mcp.treasury_yields import FILE_STORE, Summary

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)

CCPI = "Colombo Consumer Price Index (CCPI) (CCPI, 2021=100)"
NCPI = "National Consumer Price Index (NCPI) (NCPI, 2021=100)"
TITLES = [
    "Measures of Consumer Price Inflation",
    "Daily Indicative Exchange Rates",
    "Daily Buy and Sell Exchange Rates",
    "Daily Operations",
    "Commercial Bank Lending and Deposit Rates ( Per cent per annum )",
    "Auction Result: Treasury Bills",
]
BILL_RESULTS = FILE_STORE + "e2e42399-1bd0-4e24-86ef-2f6bfaaf275c"
BILL_PHASE_II = FILE_STORE + "96a04677-bbfc-4848-a833-a2b22864f0af"
DAILY_LABELS = ["< 91 Days", "< 182 Days", "< 364 Days"]
BONDS = "To be developed with the primary dealer. Until then, please refer to the primary dealer's information."


def saved(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def nothing_still_loading():
    """Each test starts with no section left loading by another test."""
    morning_rates._reading.clear()
    yield
    morning_rates._reading.clear()


def confirmed_by_a_later_report(monkeypatch, rates=(9.30, 9.44, 9.95)):
    """A daily report for trading on 14 October, the newest auction's day, showing `rates`."""
    rows = [("Treasury Bills", label, [rate] + [None] * 4) for label, rate in zip(DAILY_LABELS, rates)]
    report = Summary(date(2026, 10, 14), date(2026, 10, 15), rows, None)
    listed = (date(2026, 10, 15), report, Page(FILE_STORE + "report-15-oct", b"", FETCHED))
    monkeypatch.setattr(treasury_yields, "latest_summary", lambda: listed)


@pytest.fixture
def sources(monkeypatch):
    """Make every source return its saved page. Change an entry to change what a source says."""
    pages = {
        inflation.TABLE_URL: saved("inflation_table_2026-10-09.html"),
        exchange_rates.INDICATIVE.form_url: saved("indicative_form.html"),
        exchange_rates.TT.form_url: saved("tt_form.html"),
        exchange_rates.INDICATIVE.results_url: saved("indicative_USD_2026-10-01_to_09.html"),
        exchange_rates.TT.results_url: saved("tt_USD_2026-10-01_to_09.html"),
        "lending": saved("library_lending_2026-08-01_to_10-09.html"),
        "policy": saved("library_policy_2026-09-25_to_10-09.html"),
        snapshot.RATE_WINDOW_URL: saved("ratewindow_2026-10-09.html"),
        "daily report page": saved("treasury_daily_report_page_2026-10-13.html"),
        "bill results page": saved("bill_auction_results_page_2026-10-16.html"),
        BILL_RESULTS: bill_auctions.pdf_text((FIXTURES / "bill_auction_2026-10-14.pdf").read_bytes()),
        BILL_PHASE_II: saved("bill_auction_2026-10-14_phase_ii.txt"),
    }
    daily_file = (FIXTURES / "treasury_daily_summary_2026-10-13.xls").read_bytes()

    def fake_fetch(url, form=None):
        return Page(url, pages[url].encode(), FETCHED)

    def fake_search(report_id, start, end):
        return Page("unused", pages["policy" if report_id == 1059 else "lending"].encode(), FETCHED)

    def fake_ministry(url, **options):
        if url == bill_auctions.LISTING_URL:
            return Page(f"{url}/section/2026", pages["bill results page"].encode(), FETCHED)
        if url in (BILL_RESULTS, BILL_PHASE_II):
            return Page(url, url.encode(), FETCHED)  # its text is looked up by address below
        if url.startswith(FILE_STORE):
            return Page(url, daily_file, FETCHED)
        return Page(f"{url}/section/2026", pages["daily report page"].encode(), FETCHED)

    monkeypatch.setattr(morning_rates, "fetch", fake_fetch)
    monkeypatch.setattr(exchange_rates, "fetch", fake_fetch)
    monkeypatch.setattr(data_library, "search", fake_search)
    monkeypatch.setattr(treasury_yields, "download", fake_ministry)
    monkeypatch.setattr(bill_auctions, "pdf_text", lambda body: pages[body.decode()])
    monkeypatch.setattr(morning_rates, "today_in_sri_lanka", lambda: date(2026, 10, 9))
    return pages


def sheet() -> dict:
    """The sheet, with its sections looked up by title."""
    result = morning_rates.get_morning_rates()
    return {**result, "by_title": {section["title"]: section for section in result["sections"]}}


def figures(section: dict) -> list[tuple]:
    return [(figure["label"], figure["value"], figure["date"]) for figure in section["figures"]]


def shown(section: dict) -> list[tuple]:
    return [(figure["label"], figure["shown"], figure["for"]) for figure in section["figures"]]


# --- The whole sheet --------------------------------------------------------


def test_every_section_is_there_under_the_sources_own_title(sources):
    result = sheet()
    assert [section["title"] for section in result["sections"]] == TITLES
    assert [section["group"] for section in result["sections"]] == [
        "Inflation", "US dollar", "US dollar", "Policy rates", "Lending and deposit rates", "Treasury bills",
    ]  # fmt: skip
    assert not any("not_available" in section for section in result["sections"])
    assert result["sheet"] == "Morning Sheet"
    assert result["date"] == "2026-10-09"
    assert "confirm a figure against its source" in result["disclaimer"]


def test_inflation_is_ncpi_only_each_figure_with_its_own_month(sources):
    section = sheet()["by_title"]["Measures of Consumer Price Inflation"]
    # In the saved table September's NCPI cells are "-": CBSL had not published them yet.
    assert figures(section) == [
        (f"{NCPI}: Headline Inflation (Y-o-Y)", 8.1, "2026-08"),
        (f"{NCPI}: Core Inflation (Y-o-Y)", 6.3, "2026-08"),
    ]
    assert shown(section)[0][1:] == ("8.10%", "Aug 2026")
    assert section["dates_are"] == "the month the inflation figure measures"
    assert not any("CCPI" in figure["label"] for figure in section["figures"])


def test_us_dollar_rates_keep_cbsls_column_headings(sources):
    by_title = sheet()["by_title"]
    indicative = by_title["Daily Indicative Exchange Rates"]
    assert figures(indicative) == [("1 USD -> LKR", 330.9617, "2026-10-09")]
    assert shown(indicative) == [("1 USD -> LKR", "330.9617", "9 Oct 2026")]
    assert indicative["currency"] == "US Dollar"
    assert indicative["dates_are"] == "the day the rate is for (CBSL's 'Date' column)"
    bank = by_title["Daily Buy and Sell Exchange Rates"]
    assert figures(bank) == [
        ("Buy Rate (LKR)", 326.4384, "2026-10-09"),
        ("Sell Rate (LKR)", 335.4464, "2026-10-09"),
    ]
    assert "note" not in indicative and "note" not in bank  # today's rates are out


def test_daily_rates_that_are_not_todays_say_so(sources, monkeypatch):
    monkeypatch.setattr(morning_rates, "today_in_sri_lanka", lambda: date(2026, 10, 12))
    by_title = sheet()["by_title"]
    for title in ("Daily Indicative Exchange Rates", "Daily Buy and Sell Exchange Rates"):
        assert by_title[title]["note"] == "The latest published rate is for 9 Oct 2026, not today (12 Oct 2026)."
    # Monthly, weekly and auction figures are never today's, so they carry no such note.
    assert not any("note" in by_title[title] for title in (TITLES[0], TITLES[4]))
    assert "not today" not in by_title[TITLES[5]].get("note", "")


def test_lending_and_deposit_rates_under_cbsls_own_headings(sources):
    section = sheet()["by_title"][TITLES[4]]
    # CBSL's headings exactly as printed, its "Weigted" typo included. The
    # deposit rate's unexplained "6 months" column (7.13) is not shown.
    assert figures(section) == [
        ("Average Weighted Prime Lending Rate (AWPR): Weekly", 11.04, "2026-10-02"),
        ("Average Weigted Lending Rate (AWLR)", 12.59, "2026-08-31"),
        ("Average Weighted Deposit Rate: Monthly", 7.52, "2026-08-31"),
        ("Average Weighted Fixed Deposit Rate (AWFDR) Rate (% )", 9.34, "2026-08-31"),
    ]
    assert [row[1:] for row in shown(section)] == [
        ("11.04%", "week ending 2 Oct 2026"), ("12.59%", "Aug 2026"), ("7.52%", "Aug 2026"), ("9.34%", "Aug 2026"),
    ]  # fmt: skip
    assert "7.13" not in str(section)
    assert section["dates_are"].startswith("for AWPR, the week ending on that day (CBSL's 'End Week' column)")
    assert section["source_url"].endswith("ReportId=6277")


@pytest.mark.parametrize(
    "old, new",
    [
        ("Average Weigted Lending Rate (AWLR)", "Average Weighted Lending Rate (AWLR)"),
        ("Average Weighted Deposit Rate", "Average Weighted Savings Rate"),
        ("Average Weighted Fixed Deposit Rate (AWFDR) Rate (% )", "Average Weighted Fixed Deposit Rate (AWFDR)"),
    ],
)
def test_a_changed_rate_heading_blanks_the_section(sources, old, new):
    import re

    spaced = r"\s+".join(map(re.escape, old.split()))  # CBSL breaks long headings across lines
    assert len(re.findall(spaced, sources["lending"])) == 1, old
    sources["lending"] = re.sub(spaced, new, sources["lending"])
    section = sheet()["by_title"][TITLES[4]]
    assert "figures" not in section and "rate headings" in section["not_available"]


def test_deposit_columns_in_another_order_are_refused(sources):
    swapped = sources["lending"].replace(">Weekly<", ">Monthly<", 1)
    sources["lending"] = swapped
    section = sheet()["by_title"][TITLES[4]]
    assert "figures" not in section and "column headings" in section["not_available"]


def test_a_missing_monthly_rate_blanks_only_its_own_row(sources):
    assert sources["lending"].count("9.34</td>") == 1
    sources["lending"] = sources["lending"].replace("9.34</td>", "</td>")
    section = sheet()["by_title"][TITLES[4]]
    assert [figure["shown"] for figure in section["figures"]] == ["11.04%", "12.59%", "7.52%", "—"]
    assert "lists no 'Average Weighted Fixed Deposit Rate (AWFDR) Rate (% )'" in section["figures"][3]["not_shown_because"]


def test_a_monthly_rate_not_dated_at_a_month_end_is_not_shown(sources):
    assert sources["lending"].count("2026-08-31</td>") == 1
    sources["lending"] = sources["lending"].replace("2026-08-31</td>", "2026-08-30</td>")
    section = sheet()["by_title"][TITLES[4]]
    assert [figure["shown"] for figure in section["figures"][1:]] == ["—", "—", "—"]
    assert section["figures"][1]["not_shown_because"] == "CBSL dates this monthly figure 2026-08-30, not the last day of a month."


def test_treasury_bills_are_the_newest_auction_rates_once_the_daily_report_confirms_them(sources, monkeypatch):
    confirmed_by_a_later_report(monkeypatch)
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert figures(section) == [
        ("91 days", 9.30, "2026-10-14"),
        ("182 days", 9.44, "2026-10-14"),
        ("364 days", 9.95, "2026-10-14"),
    ]
    assert shown(section)[0][1:] == ("9.30%", "auction of 14 Oct 2026")
    assert [figure["isin"] for figure in section["figures"]] == ["LKA09127A158", "LKA18227D167", "LKA36427J150"]
    assert section["report_title"] == "TREASURY BILL AUCTION HELD ON 14 OCTOBER 2026"
    assert section["file_url"] == BILL_RESULTS
    assert section["figures_are"] == "Weighted Average Yield Rate (WAYR) (%), Current Auction"
    assert section["cross_check"].startswith("Checked: the rates agree")
    assert "listed on 15 Oct 2026" in section["cross_check"]
    assert "'Current Auction' column" in section["cross_check"]
    assert "note" not in section


def test_until_a_daily_report_covers_the_newest_auction_the_one_before_is_shown(sources):
    # The saved report trades on 12 October: it confirms the auction of 7 October
    # (the result's "Last Auction" column), not the newer one of 14 October.
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert figures(section) == [
        ("91 days", 9.26, "2026-10-07"),
        ("182 days", 9.44, "2026-10-07"),
        ("364 days", 9.95, "2026-10-07"),
    ]
    assert shown(section)[0][1:] == ("9.26%", "auction of 7 Oct 2026")
    assert [figure["isin"] for figure in section["figures"]] == [None, None, None]  # those printed are this week's
    assert section["figures_are"] == "Weighted Average Yield Rate (WAYR) (%), Last Auction"
    assert section["cross_check"].startswith("Checked: the rates agree")
    assert "listed on 13 Oct 2026" in section["cross_check"]
    assert section["note"].startswith("The auction of 14 Oct 2026 has results, but no daily report confirms them yet")
    assert "the auction before it, 7 Oct 2026" in section["note"]
    assert section["daily_report_url"].startswith(FILE_STORE)


def test_a_bill_rate_the_daily_report_disagrees_with_is_not_shown(sources, monkeypatch):
    confirmed_by_a_later_report(monkeypatch, rates=(9.30, 9.45, 9.95))
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert [figure["value"] for figure in section["figures"]] == [9.30, None, 9.95]
    assert section["figures"][1]["shown"] == "—"
    assert "disagree" in section["figures"][1]["not_shown_because"]


def test_last_weeks_rate_the_daily_report_disagrees_with_is_not_shown_either(sources, monkeypatch):
    rows = [("Treasury Bills", label, [rate] + [None] * 4) for label, rate in zip(DAILY_LABELS, [9.26, 9.45, 9.95])]
    disagreeing = Summary(date(2026, 10, 12), date(2026, 10, 13), rows, None)
    monkeypatch.setattr(treasury_yields, "latest_summary", lambda: (date(2026, 10, 13), disagreeing, Page("d", b"", FETCHED)))
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert [figure["value"] for figure in section["figures"]] == [9.26, None, 9.95]
    assert "'Last Auction' rate for 182 days is 9.44%" in section["figures"][1]["not_shown_because"]


def test_a_bill_with_no_rate_in_the_confirmed_column_is_not_shown(sources):
    sources[BILL_RESULTS] = sources[BILL_RESULTS].replace("9.30 9.26", "9.30 -")
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert section["figures"][0]["shown"] == "—"
    assert section["figures"][0]["not_shown_because"] == (
        "The results table shows '-' for 91 days in its 'Last Auction' column, not a rate."
    )


def test_no_bill_rate_is_shown_if_the_daily_report_cannot_be_read(sources, monkeypatch):
    def down():
        raise SourceUnavailable("Could not reach Sri Lanka's Ministry of Finance.")

    monkeypatch.setattr(treasury_yields, "latest_summary", down)
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert "figures" not in section
    assert section["not_available"] == (
        "The Treasury bill auction rates are not shown, because the Ministry's daily report, "
        "which must confirm them, could not be read. Could not reach Sri Lanka's Ministry of Finance."
    )


def test_a_site_that_is_down_still_counts_as_down_not_as_a_changed_page(sources, monkeypatch):
    def down():
        raise SourceUnavailable("Could not reach Sri Lanka's Ministry of Finance.")

    monkeypatch.setattr(treasury_yields, "latest_summary", down)
    with pytest.raises(SourceUnavailable):  # the live check counts this as "unreachable", not "broken"
        morning_rates.SECTIONS[5].read()


def test_no_bill_rate_is_shown_if_the_daily_report_is_older_than_both_auctions(sources, monkeypatch):
    rows = [("Treasury Bills", label, [1.0] + [None] * 4) for label in DAILY_LABELS]
    old = Summary(date(2026, 10, 1), date(2026, 10, 2), rows, None)
    monkeypatch.setattr(treasury_yields, "latest_summary", lambda: (date(2026, 10, 2), old, Page("d", b"", FETCHED)))
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert "figures" not in section
    assert section["not_available"].startswith("The Treasury bill auction rates are not shown, because the Ministry's")
    assert section["not_available"].endswith("before the last two auctions, so it cannot confirm any of their rates.")


def test_the_auction_result_and_the_daily_report_are_read_side_by_side(sources, monkeypatch):
    import threading

    report_started = threading.Event()
    read_report, read_result = treasury_yields.latest_summary, bill_auctions.latest_result

    def report():
        report_started.set()
        return read_report()

    def result():
        # Read one after the other, the report would only start after this returns.
        assert report_started.wait(timeout=2), "the daily report was not started alongside the result"
        return read_result()

    monkeypatch.setattr(treasury_yields, "latest_summary", report)
    monkeypatch.setattr(bill_auctions, "latest_result", result)
    assert sheet()["by_title"]["Auction Result: Treasury Bills"]["figures"]


def test_bonds_and_the_fd_ceiling_are_listed_as_not_shown(sources):
    bonds, ceiling = sheet()["not_shown"]
    assert bonds == {"item": "Treasury bonds", "reason": BONDS, "in_short": BONDS}
    assert ceiling["item"].startswith("FD ceiling rate")
    assert ceiling["reason"].startswith("Still in development.")
    assert [rule["issued"] for rule in ceiling["rules"]] == ["2025-06-23", "2026-01-12"]


# --- The finished table ---------------------------------------------------------


def test_the_table_is_one_sheet_with_notes(sources):
    table = sheet()["table"]
    assert table.startswith("## Morning Sheet: Friday 9 October 2026\n")
    assert "| Section | Item | Figure | For | Source |" in table
    assert f"| **Inflation** | {NCPI}: Headline Inflation (Y-o-Y) | 8.10% | Aug 2026 |" in table
    assert "| **US dollar** | 1 USD -> LKR | 330.9617 | 9 Oct 2026 |" in table
    assert "|  | Buy Rate (LKR) | 326.4384 | 9 Oct 2026 |" in table
    assert "| **Lending and deposit rates** | Average Weighted Prime Lending Rate (AWPR): Weekly | 11.04% | week ending 2 Oct 2026 |" in table
    assert "|  | Average Weigted Lending Rate (AWLR) | 12.59% | Aug 2026 |" in table
    assert "|  | Average Weighted Deposit Rate: Monthly | 7.52% | Aug 2026 |" in table
    assert "|  | Average Weighted Fixed Deposit Rate (AWFDR) Rate (% ) | 9.34% | Aug 2026 |" in table
    assert "| **Policy rates** (note 1) | Overnight Policy Rate | 8.75% | in force at 13:30, 9 Oct 2026 | [CBSL: Overnight Policy Rate (front page)](https://www.cbsl.gov.lk/en) |" in table
    assert "|  | Standing Facilities: SDF, Rate (%) | 8.25% | 9 Oct 2026 | [CBSL Data Library: Daily Operations](" in table
    assert "|  | Standing Facilities: SLF, Rate (%) | 9.25% | 9 Oct 2026 |" in table
    assert "\n1. Checked: the SDF and SLF rates are 0.50% either side of the Overnight Policy Rate, as CBSL sets them." in table
    assert "| **Treasury bills** (note 2) | 91 days | 9.26% | auction of 7 Oct 2026 ⚠ (note 3) |" in table
    assert f"| **Treasury bonds** | {BONDS} | — | — | — |" in table
    assert "| **FD ceiling rate** | Still in development. Until then, please refer to the team's existing source. |" in table
    assert "\n2. Figures are the 'Weighted Average Yield Rate (WAYR) (%), Last Auction' column. Checked:" in table
    assert "\n3. The auction of 14 Oct 2026 has results, but no daily report confirms them yet" in table
    assert "[CBSL: Daily Indicative Exchange Rates](https://www.cbsl.gov.lk/" in table
    assert "[Ministry of Finance (PDMO): Auction Result: Treasury Bills](" in table
    assert table.rstrip().endswith(f"*{morning_rates.DISCLAIMER}*")


def test_the_table_flags_rates_that_are_not_todays(sources, monkeypatch):
    monkeypatch.setattr(morning_rates, "today_in_sri_lanka", lambda: date(2026, 10, 12))
    table = sheet()["table"]
    assert "| 330.9617 | 9 Oct 2026 ⚠ (note 1) |" in table
    assert "\n1. The latest published rate is for 9 Oct 2026, not today (12 Oct 2026)." in table


def test_the_table_says_when_a_section_is_not_available(sources, monkeypatch):
    def down(report_id, start, end):
        raise SourceUnavailable("CBSL's Data Library did not answer after two tries.")

    monkeypatch.setattr(data_library, "search", down)
    table = sheet()["table"]
    assert "| **Lending and deposit rates** | Not available just now (note 1) | — | — |" in table
    assert "\n1. CBSL's Data Library did not answer after two tries." in table


# --- When something is wrong, only that section goes blank ------------------


def test_one_source_being_down_leaves_the_others_untouched(sources, monkeypatch):
    working = data_library.search

    def lending_down(report_id, start, end):
        if report_id == 6277:
            raise SourceUnavailable("CBSL's Data Library did not answer after two tries.")
        return working(report_id, start, end)

    monkeypatch.setattr(data_library, "search", lending_down)
    result = sheet()
    lending = result["by_title"][TITLES[4]]
    assert lending["not_available"] == "CBSL's Data Library did not answer after two tries."
    assert "figures" not in lending
    assert lending["source_url"].endswith("ReportId=6277")  # still says where to look by hand
    others = [section for section in result["sections"] if section is not lending]
    assert len(others) == 5 and not any("not_available" in section for section in others)


@pytest.mark.parametrize(
    "page, old, new, title",
    [
        (inflation.TABLE_URL, ">Core Inflation<", ">Underlying Inflation<", TITLES[0]),
        (exchange_rates.INDICATIVE.results_url, "USD  -&gt; LKR", "EUR  -&gt; LKR", TITLES[1]),
        (exchange_rates.TT.results_url, "Sell Rate (LKR)", "Sell Rate (USD)", TITLES[2]),
        ("lending", ">Weekly<", ">Daily<", TITLES[4]),
        ("bill results page", "Treasury Bills", "Treasury Notes", TITLES[5]),
        (BILL_RESULTS, "Current \nAuction \nLast", "Last \nAuction \nCurrent", TITLES[5]),
    ],
)
def test_a_changed_heading_blanks_that_section_only(sources, page, old, new, title):
    assert old in sources[page]
    sources[page] = sources[page].replace(old, new)
    result = sheet()
    assert "figures" not in result["by_title"][title]
    assert "not_available" in result["by_title"][title]
    assert sum("not_available" in section for section in result["sections"]) == 1


def test_no_dollar_rate_in_the_last_two_weeks_is_said_plainly(sources):
    sources[exchange_rates.INDICATIVE.results_url] = saved("indicative_USD_weekend_empty.html")
    section = sheet()["by_title"]["Daily Indicative Exchange Rates"]
    assert section["not_available"] == "CBSL lists no US dollar rate between 2026-09-25 and 2026-10-09."


def test_no_weekly_rate_in_five_weeks_is_said_plainly(sources):
    sources["lending"] = saved("library_lending_empty.html")
    section = sheet()["by_title"][TITLES[4]]
    assert section["not_available"] == "CBSL's Data Library lists no lending or deposit rates between 2026-07-01 and 2026-10-09."


def test_a_bug_is_not_dressed_up_as_a_missing_section(sources, monkeypatch):
    def bug(report_id, start, end):
        raise RuntimeError("a mistake in this project's own code")

    monkeypatch.setattr(data_library, "search", bug)
    with pytest.raises(RuntimeError):
        morning_rates.get_morning_rates()


# --- Reading the sources' own headings ---------------------------------------


def test_inflation_labels_follow_the_base_year_on_the_page(sources):
    rebased = sources[inflation.TABLE_URL].replace("2021=100", "2025=100")
    labels = morning_rates.inflation_labels(rebased)
    assert labels[0] == "Colombo Consumer Price Index (CCPI) (CCPI, 2025=100): Headline Inflation (Y-o-Y)"
    assert labels[3] == "National Consumer Price Index (NCPI) (NCPI, 2025=100): Core Inflation (Y-o-Y)"


def test_inflation_columns_in_a_new_order_are_refused(sources):
    table = sources[inflation.TABLE_URL]
    swapped = table.replace("Colombo Consumer Price Index", "National Consumer Price Index", 1)
    with pytest.raises(PageChanged, match="index headings"):
        morning_rates.inflation_labels(swapped)
    with pytest.raises(PageChanged, match="heading row starting 'Date'"):
        morning_rates.inflation_labels("<table><tr><td>Month</td></tr></table>")


def test_a_column_with_no_figures_at_all_shows_nothing(sources):
    sources[inflation.TABLE_URL] = (
        "<table>"
        f"<tr><td>Date</td><td>{CCPI}</td><td>{NCPI}</td></tr>"
        "<tr><td></td><td>Headline Inflation (Y-o-Y)</td><td>Core Inflation (Y-o-Y)</td>"
        "<td>Headline Inflation (Y-o-Y)</td><td>Core Inflation (Y-o-Y)</td></tr>"
        "<tr><td>2026</td></tr>"
        "<tr><td>September</td><td>8.00</td><td>5.40</td><td>-</td><td>-</td></tr>"
        "</table>"
    )
    section = sheet()["by_title"]["Measures of Consumer Price Inflation"]
    assert shown(section)[0] == (f"{NCPI}: Headline Inflation (Y-o-Y)", "—", "none published")
    assert figures(section)[0][1:] == (None, None)


def test_reads_the_lending_tables_heading_rows(sources):
    title, groups, kinds = data_library.heading_rows(sources["lending"])[:3]
    assert title == ["Commercial Bank Lending and Deposit Rates ( Per cent per annum )"]
    assert groups[0] == "End Week" and groups[2] == "Average Weighted Prime Lending Rate (AWPR)"
    assert kinds == ["Weekly", "Monthly", "6 months", "Monthly", "6 months"]
    assert data_library.heading_rows("<html><body>Please log in</body></html>") == []


def test_reads_heading_cells():
    assert heading_cells(saved("tt_USD_2026-10-01_to_09.html")) == [
        "Date",
        "Buy Rate (LKR)",
        "Sell Rate (LKR)",
    ]


def slow_bill_results(monkeypatch, seconds: float) -> list:
    """Make the auction result take `seconds` to read. Lists each time it is read."""
    import time

    reads, read_result = [], bill_auctions.latest_result

    def slow():
        reads.append(1)
        time.sleep(seconds)
        return read_result()

    monkeypatch.setattr(bill_auctions, "latest_result", slow)
    return reads


def test_a_slow_section_says_loading_and_shows_the_rest_on_time(sources, monkeypatch):
    import time

    slow_bill_results(monkeypatch, 1.0)
    monkeypatch.setattr(morning_rates, "SHEET_DEADLINE_SECONDS", 0.3)
    started = time.monotonic()
    result = sheet()
    assert time.monotonic() - started < 0.9  # did not wait for the slow source
    bills = result["by_title"][TITLES[5]]
    assert "figures" not in bills and "not_available" not in bills
    assert bills["loading"].startswith("Loading: the Ministry of Finance (PDMO) website is slow to respond.")
    assert "this takes up to 30 seconds" in bills["loading"]
    assert result["check_again"] is True
    assert "| **Treasury bills** | Loading, up to 30 seconds (note 2) | — | — |" in result["table"]
    others = [section for section in result["sections"] if section is not bills]
    assert all("figures" in section for section in others)


def test_the_second_look_waits_for_the_same_downloads_and_shows_checked_rates(sources, monkeypatch):
    reads = slow_bill_results(monkeypatch, 0.5)
    monkeypatch.setattr(morning_rates, "SHEET_DEADLINE_SECONDS", 0.1)
    assert sheet()["check_again"] is True
    second = sheet()  # the look the assistant is asked to take
    assert second["check_again"] is False
    bills = second["by_title"][TITLES[5]]
    assert [figure["shown"] for figure in bills["figures"]] == ["9.26%", "9.44%", "9.95%"]
    assert bills["cross_check"].startswith("Checked:")
    assert reads == [1]  # read once: the second look did not start the downloads again


def test_still_loading_on_the_second_look_asks_the_person_to_try_later(sources, monkeypatch):
    slow_bill_results(monkeypatch, 1.0)
    monkeypatch.setattr(morning_rates, "SHEET_DEADLINE_SECONDS", 0.1)
    monkeypatch.setattr(morning_rates, "FOLLOW_UP_SECONDS", 0.1)
    sheet()
    second = sheet()
    assert second["check_again"] is False  # one second look only, never a loop
    bills = second["by_title"][TITLES[5]]
    assert bills["not_available"].startswith("Still loading: the Ministry of Finance (PDMO) website has still not answered.")


def test_a_finished_read_is_not_reused_by_the_next_sheet(sources, monkeypatch):
    reads = slow_bill_results(monkeypatch, 0)
    sheet()
    sheet()
    assert reads == [1, 1]  # each sheet reads afresh (from the few-minute cache)


def test_the_saved_file_takes_the_second_look_itself(sources, tmp_path, monkeypatch):
    slow_bill_results(monkeypatch, 0.5)
    monkeypatch.setattr(morning_rates, "SHEET_DEADLINE_SECONDS", 0.1)
    monkeypatch.chdir(tmp_path)
    morning_rates.save_csv()
    text = (tmp_path / "morning-sheet-2026-10-09.csv").read_text(encoding="utf-8-sig")
    assert "9.26%" in text and "Loading" not in text


def test_how_long_each_section_took_goes_to_the_log(sources, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="sl_economy_mcp"):
        sheet()
    assert any(line.startswith("Auction Result: Treasury Bills: section read in ") for line in caplog.messages)


def test_a_vertical_bar_in_a_label_cannot_break_the_table(sources):
    rows = [{"group": "Lending rate", "title": "A | B", "publisher": morning_rates.CBSL, "source_url": "https://example.test",
             "figures": [{"label": "x | y", "shown": "1.00%", "for": "today"}]}]
    table = morning_rates.render(rows, date(2026, 10, 9), "09:00")
    assert "| **Lending rate** | x \\| y | 1.00% | today | [CBSL: A \\| B](https://example.test) |" in table


def test_the_sheet_as_a_csv_file(sources):
    import csv

    rows = list(csv.reader(morning_rates.csv_text(morning_rates.get_morning_rates()).splitlines()))
    assert rows[0][0].startswith("Morning Sheet: 2026-10-09")
    assert rows[1] == morning_rates.CSV_COLUMNS
    assert rows[2][:4] == ["Inflation", f"{NCPI}: Headline Inflation (Y-o-Y)", "8.10%", "Aug 2026"]
    bill = next(row for row in rows if row[1:2] == ["182 days"])
    assert bill[2:4] == ["9.44%", "auction of 7 Oct 2026"]  # as displayed, so Excel keeps 9.40, not 9.4
    assert bill[6].startswith("Checked:") and "no daily report confirms them yet" in bill[6]
    assert ["Treasury bonds", BONDS, "", "", "", "", ""] in rows
    assert rows[-1] == [morning_rates.DISCLAIMER]


def test_save_csv_writes_a_dated_file(sources, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    morning_rates.save_csv()
    text = (tmp_path / "morning-sheet-2026-10-09.csv").read_text(encoding="utf-8-sig")
    assert "9.26%" in text


# --- Figures older than usual, and who to tell ----------------------------------


def test_figures_of_a_normal_age_carry_no_warning(sources):
    result = sheet()
    assert not any("late" in figure for section in result["sections"] for figure in section.get("figures", []))
    assert "Older than usual" not in result["table"]


@pytest.mark.parametrize(
    "today, title, age",
    [
        (date(2026, 11, 15), TITLES[0], 76),  # August's inflation, from 31 Aug
        (date(2026, 10, 24), TITLES[4], 22),  # AWPR for the week ending 2 Oct (the monthly rates are not late)
        (date(2026, 10, 24), TITLES[5], 17),  # the auction of 7 Oct
    ],
)
def test_a_figure_older_than_usual_is_shown_but_flagged(sources, monkeypatch, today, title, age):
    monkeypatch.setattr(morning_rates, "today_in_sri_lanka", lambda: today)
    section = sheet()["by_title"][title]
    for figure in section["figures"][:1] if title == TITLES[4] else section["figures"]:
        assert figure["value"] is not None  # still the source's latest, so still shown
        assert figure["late"].startswith("Older than usual:")
        assert f"this one is {age} days old" in figure["late"]


def test_one_day_younger_is_not_flagged(sources, monkeypatch):
    monkeypatch.setattr(morning_rates, "today_in_sri_lanka", lambda: date(2026, 10, 23))
    by_title = sheet()["by_title"]
    assert "late" not in by_title[TITLES[4]]["figures"][0]  # 21 days: the usual limit
    assert "late" not in by_title[TITLES[5]]["figures"][0]  # 16 days: the usual limit


def test_the_warning_is_numbered_once_in_the_table(sources, monkeypatch):
    monkeypatch.setattr(morning_rates, "today_in_sri_lanka", lambda: date(2026, 11, 15))
    table = sheet()["table"]
    assert f"| {NCPI}: Headline Inflation (Y-o-Y) | 8.10% | Aug 2026 ⚠ (note 1) |" in table
    assert f"| {NCPI}: Core Inflation (Y-o-Y) | 6.30% | Aug 2026 ⚠ (note 1) |" in table
    assert table.count("Older than usual: a month's inflation figure") == 1


def test_a_changed_page_asks_the_reader_to_tell_whoever_looks_after_the_tool(sources):
    sources[inflation.TABLE_URL] = sources[inflation.TABLE_URL].replace(">Core Inflation<", ">Underlying Inflation<")
    section = sheet()["by_title"][TITLES[0]]
    assert section["not_available"].endswith("Please tell the person who looks after this tool for your team.")


def test_a_site_that_is_down_does_not_ask_anyone_to_fix_the_tool(sources, monkeypatch):
    def down(report_id, start, end):
        raise SourceUnavailable("CBSL's Data Library did not answer after two tries.")

    monkeypatch.setattr(data_library, "search", down)
    assert sheet()["by_title"][TITLES[4]]["not_available"] == "CBSL's Data Library did not answer after two tries."


def test_in_early_january_both_ministry_lists_fall_back_to_last_year(sources, monkeypatch):
    # On 2 January 2027 the Ministry's new lists may still be empty. The bill
    # rates must still be found (and double-checked) on last year's lists.
    serve_2026 = treasury_yields.download

    def new_year(url, **options):
        if url == bill_auctions.LISTING_URL:
            return Page(f"{url}/section/2027", b"<h1>Treasury Bills</h1>", FETCHED)
        if url == treasury_yields.PAGE_URL:
            return Page(f"{url}/section/2027", b"<h1>Daily Report</h1>", FETCHED)
        if url == f"{bill_auctions.LISTING_URL}/section/2026":
            return serve_2026(bill_auctions.LISTING_URL)
        if url == f"{treasury_yields.PAGE_URL}/section/2026":
            return serve_2026(treasury_yields.PAGE_URL)
        return serve_2026(url, **options)

    january = lambda: date(2027, 1, 2)  # noqa: E731
    monkeypatch.setattr(treasury_yields, "download", new_year)
    for module in (morning_rates, bill_auctions, treasury_yields):
        monkeypatch.setattr(module, "today_in_sri_lanka", january)
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert [figure["shown"] for figure in section["figures"]] == ["9.26%", "9.44%", "9.95%"]
    assert section["cross_check"].startswith("Checked:")
    assert all(figure["late"].startswith("Older than usual") for figure in section["figures"])  # saved pages are from October


def test_monthly_bank_rates_older_than_usual_are_flagged(sources, monkeypatch):
    monkeypatch.setattr(morning_rates, "today_in_sri_lanka", lambda: date(2026, 11, 15))  # 76 days after 31 Aug
    section = sheet()["by_title"][TITLES[4]]
    for figure in section["figures"][1:]:
        assert figure["value"] is not None
        assert "a monthly bank rate, counted from the month's end, is normally no more than 75 days old" in figure["late"]


# --- Policy rates ------------------------------------------------------------------


def test_policy_rates_from_both_cbsl_sources_checked_against_each_other(sources):
    section = sheet()["by_title"]["Daily Operations"]
    assert figures(section) == [
        ("Overnight Policy Rate", 8.75, "2026-10-09"),
        ("Standing Facilities: SDF, Rate (%)", 8.25, "2026-10-09"),
        ("Standing Facilities: SLF, Rate (%)", 9.25, "2026-10-09"),
    ]
    # The front page shows no date, only the rate in force when it was read.
    assert shown(section)[0][1:] == ("8.75%", "in force at 13:30, 9 Oct 2026")
    assert section["figures"][0]["source"] == {"label": "CBSL: Overnight Policy Rate (front page)", "url": "https://www.cbsl.gov.lk/en"}
    assert "source" not in section["figures"][1]  # the section's own table
    assert section["source_url"].endswith("ReportId=1059")
    assert section["cross_check"].startswith("Checked: the SDF and SLF rates are 0.50% either side")


def test_policy_rates_that_disagree_are_not_shown(sources):
    # As on the day CBSL changes its policy rate, before its tables catch up.
    assert sources[snapshot.RATE_WINDOW_URL].count("8.75 %") == 1
    sources[snapshot.RATE_WINDOW_URL] = sources[snapshot.RATE_WINDOW_URL].replace("8.75 %", "9.00 %")
    section = sheet()["by_title"]["Daily Operations"]
    assert "figures" not in section
    assert section["not_available"].startswith("The policy rates are not shown, because CBSL's two sources disagree:")
    assert "Overnight Policy Rate as 9.00%" in section["not_available"]
    assert "SDF rate as 8.25% and the SLF rate as 9.25%" in section["not_available"]
    assert morning_rates.LOOKS_AFTER not in section["not_available"]  # nothing to fix: it passes


def test_a_changed_standing_facility_heading_blanks_the_policy_rates(sources):
    assert sources["policy"].count('<td colspan="2">SDF</td>') == 1
    sources["policy"] = sources["policy"].replace('<td colspan="2">SDF</td>', '<td colspan="2">SDFR</td>')
    section = sheet()["by_title"]["Daily Operations"]
    assert "figures" not in section
    assert "standing facility headings" in section["not_available"]
    assert section["not_available"].endswith(morning_rates.LOOKS_AFTER)


def test_a_front_page_without_its_policy_rate_heading_blanks_the_policy_rates(sources):
    sources[snapshot.RATE_WINDOW_URL] = sources[snapshot.RATE_WINDOW_URL].replace("Overnight Policy Rate", "Policy Rate")
    section = sheet()["by_title"]["Daily Operations"]
    assert "figures" not in section and "Overnight Policy Rate" in section["not_available"]


def test_standing_facility_rates_older_than_usual_are_flagged(sources, monkeypatch):
    monkeypatch.setattr(morning_rates, "today_in_sri_lanka", lambda: date(2026, 10, 20))  # 11 days after 9 Oct
    section = sheet()["by_title"]["Daily Operations"]
    assert "late" not in section["figures"][0]  # the OPR is read live; it has no age
    assert all("is 11 days old" in figure["late"] for figure in section["figures"][1:])


def test_the_saved_file_names_the_opr_s_own_source(sources):
    import csv

    rows = list(csv.reader(morning_rates.csv_text(morning_rates.get_morning_rates()).splitlines()))
    opr = next(row for row in rows if row[1:2] == ["Overnight Policy Rate"])
    assert opr[:6] == ["Policy rates", "Overnight Policy Rate", "8.75%", "in force at 13:30, 9 Oct 2026",
                       "CBSL: Overnight Policy Rate (front page)", "https://www.cbsl.gov.lk/en"]  # fmt: skip


def test_a_lending_facility_rate_out_of_line_is_enough_to_withhold_all_three(sources):
    import re

    assert len(re.findall(r">\s*9\.25\s*<", sources["policy"])) == 11  # the SLF rate, once a day, and nothing else
    sources["policy"] = re.sub(r">(\s*)9\.25(\s*)<", r">\g<1>9.50\g<2><", sources["policy"])
    section = sheet()["by_title"]["Daily Operations"]
    assert "figures" not in section
    assert "SDF rate as 8.25% and the SLF rate as 9.50%" in section["not_available"]
