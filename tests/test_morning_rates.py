"""Tests for the Morning Sheet, without the internet.

Every source is replaced by a saved copy of its real page: the CBSL pages of
9 October 2026, the Ministry's daily report of 13 October and its Treasury
bill results page of 16 October (newest auction: 14 October). "Today" is
fixed at 9 October 2026, the day the CBSL pages were saved, unless a test
says otherwise.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sl_economy_mcp import bill_auctions, data_library, exchange_rates, inflation, morning_rates, treasury_yields
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
    "Commercial Bank Lending and Deposit Rates ( Per cent per annum )",
    "Auction Result: Treasury Bills",
]
BILL_RESULTS = FILE_STORE + "e2e42399-1bd0-4e24-86ef-2f6bfaaf275c"
BILL_PHASE_II = FILE_STORE + "96a04677-bbfc-4848-a833-a2b22864f0af"
BONDS = "To be developed with the primary dealer. Until then, please refer to the primary dealer's information."


def saved(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


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
        "daily report page": saved("treasury_daily_report_page_2026-10-13.html"),
        "bill results page": saved("bill_auction_results_page_2026-10-16.html"),
        BILL_RESULTS: bill_auctions.pdf_text((FIXTURES / "bill_auction_2026-10-14.pdf").read_bytes()),
        BILL_PHASE_II: saved("bill_auction_2026-10-14_phase_ii.txt"),
    }
    daily_file = (FIXTURES / "treasury_daily_summary_2026-10-13.xls").read_bytes()

    def fake_fetch(url, form=None):
        return Page(url, pages[url].encode(), FETCHED)

    def fake_search(report_id, start, end):
        return Page("unused", pages["lending"].encode(), FETCHED)

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
        "Inflation", "US dollar", "US dollar", "Lending rate", "Treasury bills",
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
    assert not any("note" in by_title[title] for title in (TITLES[0], TITLES[3], TITLES[4]))


def test_prime_lending_rate_is_the_latest_weekly_figure(sources):
    section = sheet()["by_title"][TITLES[3]]
    assert figures(section) == [("Average Weighted Prime Lending Rate (AWPR): Weekly", 11.04, "2026-10-02")]
    assert shown(section)[0][1:] == ("11.04%", "week ending 2 Oct 2026")
    assert section["dates_are"] == "the week ending on that day (CBSL's 'End Week' column)"
    assert section["source_url"].endswith("ReportId=6277")


def test_treasury_bills_are_the_latest_auction_rates_checked_against_the_daily_report(sources):
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
    # The saved daily report (trading on 12 October) is from before this auction,
    # so it is compared with the result's "Last Auction" column.
    assert section["cross_check"].startswith("Checked: the rates agree")
    assert "listed on 13 Oct 2026" in section["cross_check"]
    assert section["daily_report_url"].startswith(FILE_STORE)


def test_a_bill_rate_the_daily_report_disagrees_with_is_not_shown(sources, monkeypatch):
    rows = [("Treasury Bills", "< 91 Days", [9.26] + [None] * 4),
            ("Treasury Bills", "< 182 Days", [9.45] + [None] * 4),
            ("Treasury Bills", "< 364 Days", [9.95] + [None] * 4)]  # fmt: skip
    disagreeing = Summary(date(2026, 10, 12), date(2026, 10, 13), rows, None)
    monkeypatch.setattr(treasury_yields, "latest_summary", lambda: (date(2026, 10, 13), disagreeing, Page("d", b"", FETCHED)))
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert [figure["value"] for figure in section["figures"]] == [9.30, None, 9.95]
    assert section["figures"][1]["shown"] == "—"
    assert "disagree" in section["figures"][1]["not_shown_because"]


def test_bill_rates_still_show_if_the_daily_report_cannot_be_read(sources, monkeypatch):
    def down():
        raise SourceUnavailable("Could not reach Sri Lanka's Ministry of Finance.")

    monkeypatch.setattr(treasury_yields, "latest_summary", down)
    section = sheet()["by_title"]["Auction Result: Treasury Bills"]
    assert [figure["value"] for figure in section["figures"]] == [9.30, 9.44, 9.95]
    assert section["cross_check"].startswith("Not cross-checked today")


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
    assert "| **Lending rate** | Average Weighted Prime Lending Rate (AWPR): Weekly | 11.04% | week ending 2 Oct 2026 |" in table
    assert "| **Treasury bills** (note 1) | 91 days | 9.30% | auction of 14 Oct 2026 |" in table
    assert f"| **Treasury bonds** | {BONDS} | — | — | — |" in table
    assert "| **FD ceiling rate** | Still in development. Until then, please refer to the team's existing source. |" in table
    assert "\n1. Figures are the 'Weighted Average Yield Rate (WAYR) (%), Current Auction' column. Checked:" in table
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
    assert "| **Lending rate** | Not available just now (note 1) | — | — |" in table
    assert "\n1. CBSL's Data Library did not answer after two tries." in table


# --- When something is wrong, only that section goes blank ------------------


def test_one_source_being_down_leaves_the_others_untouched(sources, monkeypatch):
    def down(report_id, start, end):
        raise SourceUnavailable("CBSL's Data Library did not answer after two tries.")

    monkeypatch.setattr(data_library, "search", down)
    result = sheet()
    lending = result["by_title"][TITLES[3]]
    assert lending["not_available"] == "CBSL's Data Library did not answer after two tries."
    assert "figures" not in lending
    assert lending["source_url"].endswith("ReportId=6277")  # still says where to look by hand
    others = [section for section in result["sections"] if section is not lending]
    assert len(others) == 4 and not any("not_available" in section for section in others)


@pytest.mark.parametrize(
    "page, old, new, title",
    [
        (inflation.TABLE_URL, ">Core Inflation<", ">Underlying Inflation<", TITLES[0]),
        (exchange_rates.INDICATIVE.results_url, "USD  -&gt; LKR", "EUR  -&gt; LKR", TITLES[1]),
        (exchange_rates.TT.results_url, "Sell Rate (LKR)", "Sell Rate (USD)", TITLES[2]),
        ("lending", ">Weekly<", ">Daily<", TITLES[3]),
        ("bill results page", "Treasury Bills", "Treasury Notes", TITLES[4]),
        (BILL_RESULTS, "Current \nAuction \nLast", "Last \nAuction \nCurrent", TITLES[4]),
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
    section = sheet()["by_title"][TITLES[3]]
    assert "lists no weekly AWPR between 2026-09-04 and 2026-10-09" in section["not_available"]


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


def test_a_source_that_hangs_only_blanks_its_own_section(sources, monkeypatch):
    import time

    def hangs(report_id, start, end):
        time.sleep(1.0)
        raise AssertionError("the sheet should not have waited for this")

    monkeypatch.setattr(morning_rates, "SHEET_DEADLINE_SECONDS", 0.3)
    monkeypatch.setattr(data_library, "search", hangs)
    started = time.monotonic()
    result = sheet()
    assert time.monotonic() - started < 0.9  # did not wait for the slow source
    lending = result["by_title"][TITLES[3]]
    assert lending["not_available"].startswith("CBSL Data Library did not answer within 0.3 seconds")
    assert sum("not_available" in section for section in result["sections"]) == 1


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
    bill = next(row for row in rows if row[1:2] == ["91 days"])
    assert bill[2:4] == ["9.30%", "auction of 14 Oct 2026"]  # as displayed, so Excel keeps 9.30, not 9.3
    assert bill[6].startswith("Checked:")
    assert ["Treasury bonds", BONDS, "", "", "", "", ""] in rows
    assert rows[-1] == [morning_rates.DISCLAIMER]


def test_save_csv_writes_a_dated_file(sources, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    morning_rates.save_csv()
    text = (tmp_path / "morning-sheet-2026-10-09.csv").read_text(encoding="utf-8-sig")
    assert "9.30%" in text
