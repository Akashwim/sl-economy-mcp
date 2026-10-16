"""Tests for reading the Ministry of Finance's Daily Summary Report, without the internet.

They use a saved copy of the Ministry of Finance's Daily Report page and of
the Daily Summary Report it linked to on 13 October 2026.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sl_economy_mcp import treasury_yields
from sl_economy_mcp.errors import NoData, PageChanged, SourceUnavailable
from sl_economy_mcp.fetch import Page
from sl_economy_mcp.treasury_yields import FILE_STORE, PAGE_URL, Cell

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "treasury_daily_report_page_2026-10-13.html").read_text(encoding="utf-8")
FILE = (FIXTURES / "treasury_daily_summary_2026-10-13.xls").read_bytes()
GRID = treasury_yields.open_sheet(FILE)
FETCHED = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)

REPORT_13_OCT = FILE_STORE + "eb3c83a4-70c9-490d-ae71-bc4c74e47631"
EMPTY_YEAR = "<html><body><h1>Daily Report</h1></body></html>"


def line(day: str, address: str, words: str = "Daily Summary Report") -> str:
    """One line of the Daily Report page, as the Ministry types it."""
    return f'<p>&gt; {day} <a href="{address}">{words}</a></p>'


# --- Step 1: the Daily Report page -----------------------------------------


def test_every_business_day_has_one_report_link():
    lines = treasury_yields.parse_listing(PAGE)
    assert len(lines) == 191
    assert lines[0] == (date(2026, 10, 13), REPORT_13_OCT)  # the top line is the newest
    assert lines[-1][0] == date(2026, 1, 1)
    assert len({listed_on for listed_on, _ in lines}) == 191  # no day appears twice


def test_hand_typed_lines_are_still_read():
    files = dict(treasury_yields.parse_listing(PAGE))
    # "24 .03.2026": a stray space inside the date.
    assert files[date(2026, 3, 24)].startswith(FILE_STORE + "826ae01e")
    # 18 February: the link's words are split in two, "D" and "aily Summary Report".
    assert files[date(2026, 2, 18)].startswith(FILE_STORE + "e5c7d4ba")
    # 3 February: the final "t" of "Report" is outside the link.
    assert files[date(2026, 2, 3)].startswith(FILE_STORE + "c30d2171")
    # 16 April: the link says "Amended Daily Summary Report".
    assert files[date(2026, 4, 16)].startswith(FILE_STORE + "04857ab3")


def test_the_other_link_on_each_line_is_not_taken():
    # Each line also links to "Outright Treasury Bond Transactions Volumes".
    addresses = [address for _, address in treasury_yields.parse_listing(PAGE)]
    assert FILE_STORE + "3a68c877-2d95-471d-9b11-23b0749725c8" not in addresses


def test_every_spelling_of_a_ministry_file_link_is_followed():
    # The 15 October 2026 line was typed with "http://"; other pages use "/api/file/...".
    page = (
        "<h1>Daily Report</h1>"
        + line("15.10.2026", "http://www.treasury.gov.lk/api/file/a")
        + line("14.10.2026", "/api/file/b")
        + line("13.10.2026", FILE_STORE + "c")
    )
    assert treasury_yields.parse_listing(page) == [
        (date(2026, 10, 15), FILE_STORE + "a"),
        (date(2026, 10, 14), FILE_STORE + "b"),
        (date(2026, 10, 13), FILE_STORE + "c"),
    ]


def test_a_link_elsewhere_is_kept_as_unfollowable_not_skipped():
    page = "<h1>Daily Report</h1>" + line("13.10.2026", "https://example.test/api/file/abc")
    assert treasury_yields.parse_listing(page) == [(date(2026, 10, 13), None)]
    unlinked = "<h1>Daily Report</h1><p>&gt; 13.10.2026 Daily Summary Report</p>"
    assert treasury_yields.parse_listing(unlinked) == [(date(2026, 10, 13), None)]


def test_a_mistyped_date_is_left_out():
    page = (
        "<h1>Daily Report</h1>"
        + line("31.02.2026", FILE_STORE + "impossible")
        + line("27.02.2026", FILE_STORE + "real")
    )
    assert treasury_yields.parse_listing(page) == [(date(2026, 2, 27), FILE_STORE + "real")]


def test_a_year_with_no_reports_is_an_empty_list():
    assert treasury_yields.parse_listing(EMPTY_YEAR) == []


def test_a_blocked_or_changed_page_is_reported():
    with pytest.raises(PageChanged, match="did not return"):
        treasury_yields.parse_listing("<html><body>Access Denied</body></html>")
    undated = '<h1>Daily Report</h1><a href="x">Daily Summary Report</a>'
    with pytest.raises(PageChanged, match="could not be read"):
        treasury_yields.parse_listing(undated)


# --- Step 3: the Summary Statistics sheet -----------------------------------


def test_reads_the_table_as_the_sheet_shows_it():
    summary = treasury_yields.read_summary(GRID)
    assert summary.trades_date == date(2026, 10, 12)
    assert summary.quotes_date == date(2026, 10, 13)
    assert len(summary.rows) == 13
    assert summary.rows[0] == ("Treasury Bills", "< 91 Days", [9.26, 9.26, 9.10, 9.28, 9.09])
    assert summary.rows[2] == ("Treasury Bills", "< 364 Days", [9.95, None, 9.90, 9.99, 9.83])
    assert summary.rows[3] == ("Treasury Bonds", "< 2 Year", [13.83, None, None, 10.38, 10.17])
    assert summary.rows[-1] == ("Treasury Bonds", "< 30Year", [12.15, None, None, None, None])
    assert summary.source_line.startswith("Source : Primary Dealer Daily Reporting System")


def test_extra_spaces_in_the_sheet_do_not_matter():
    # The sheet really says "<  91 Days" and "Last Primary Auctions ".
    assert GRID[6, 1].value == "< 91 Days"
    assert GRID[4, 2].value == "Last Primary Auctions"


def test_rounds_the_way_excel_displays():
    # Stored value -> what the sheet shows. Python's round() gives 9.82, 9.49 and 7.62 for these.
    assert treasury_yields.as_displayed(0.09824999999999999) == 9.83  # 13 Oct 2026, < 364 Days Offer
    assert treasury_yields.as_displayed(0.09494999999999999) == 9.50  # 12 Oct 2026, < 182 Days Bid
    assert treasury_yields.as_displayed(0.07625) == 7.63  # 1 Dec 2025, < 91 Days Bid
    # Values away from a rounding edge come out the same either way.
    assert treasury_yields.as_displayed(0.09258925655928127) == 9.26
    assert treasury_yields.as_displayed(0.0926) == 9.26
    assert treasury_yields.as_displayed(0.1) == 10.0


def test_a_moved_heading_stops_everything():
    moved = {**GRID, (4, 2): Cell("text", "Latest Auctions")}
    with pytest.raises(PageChanged, match="Cell C5 .* expects 'Last Primary Auctions'"):
        treasury_yields.read_summary(moved)
    missing = {place: cell for place, cell in GRID.items() if place != (5, 5)}
    with pytest.raises(PageChanged, match="Cell F6 .* holds nothing where this tool expects 'Bid'"):
        treasury_yields.read_summary(missing)


def test_a_changed_row_label_stops_everything():
    relabelled = {**GRID, (12, 1): Cell("text", "< 7 Year")}
    with pytest.raises(PageChanged, match="Cell B13 .* expects '< 5 Year'"):
        treasury_yields.read_summary(relabelled)


@pytest.mark.parametrize(
    "cell",
    [
        Cell("number", 9.26, "0.00%"),  # typed as 9.26 instead of 0.0926: would display as 926.00%
        Cell("number", 0.0926, "0.000%"),  # displayed to three decimals, so two would misstate it
        Cell("text", "n/a", "0.00%"),
        Cell("other", 42, "0.00%"),  # an Excel error such as #N/A
    ],
)
def test_a_figure_that_is_not_a_two_decimal_percentage_is_refused(cell):
    with pytest.raises(PageChanged, match="Cell C7 .* No figures were read"):
        treasury_yields.read_summary({**GRID, (6, 2): cell})


def test_a_dash_or_an_empty_cell_is_no_figure():
    dash = treasury_yields.read_summary({**GRID, (6, 2): Cell("text", "-", "0.00%")})
    assert dash.rows[0][2][0] is None
    emptied = {place: cell for place, cell in GRID.items() if place != (6, 2)}
    assert treasury_yields.read_summary(emptied).rows[0][2][0] is None


def test_the_dates_must_be_dates_and_must_agree():
    undated = {**GRID, (1, 5): Cell("text", "12 October")}
    with pytest.raises(PageChanged, match="Cell F2 .* should hold a date"):
        treasury_yields.read_summary(undated)
    disagreeing = {**GRID, (4, 6): Cell("date", date(2026, 10, 12))}
    with pytest.raises(PageChanged, match="two different dates"):
        treasury_yields.read_summary(disagreeing)


def test_the_sheets_source_line_is_optional():
    without = {place: cell for place, cell in GRID.items() if place[0] < 19}
    assert treasury_yields.read_summary(without).source_line is None


def test_a_file_that_is_not_excel_is_reported():
    with pytest.raises(PageChanged, match="no longer an old-format Excel file"):
        treasury_yields.open_sheet(b"<html>502 Bad Gateway</html>")
    with pytest.raises(PageChanged, match="no longer an old-format Excel file"):
        treasury_yields.open_sheet(b"")


# --- The newest report ---------------------------------------------------------


@pytest.fixture
def ministry(monkeypatch):
    """Make the Ministry's site return the saved page and file. Lists what was asked for."""
    asked = []

    def fake_download(url, form=None, session=None, timeout=None, site=None):
        asked.append(url)
        if url.startswith(FILE_STORE):
            return Page(url, FILE, FETCHED)
        # The plain address leads to this year's list.
        return Page(f"{url}/section/2026", PAGE.encode(), FETCHED)

    monkeypatch.setattr(treasury_yields, "download", fake_download)
    return asked


def test_the_newest_report_is_the_top_line_of_the_page(ministry):
    listed_on, summary, file = treasury_yields.latest_summary()
    assert ministry == [PAGE_URL, REPORT_13_OCT]
    assert listed_on == date(2026, 10, 13)
    assert summary.trades_date == date(2026, 10, 12)
    assert summary.rows[0] == ("Treasury Bills", "< 91 Days", [9.26, 9.26, 9.10, 9.28, 9.09])
    assert file.url == REPORT_13_OCT


def test_a_newest_line_without_a_usable_link_is_never_skipped(monkeypatch):
    # Falling back to the line below would quietly use yesterday's report.
    page = (
        "<h1>Daily Report</h1>"
        + line("15.10.2026", "https://example.test/api/file/new")
        + line("14.10.2026", FILE_STORE + "older")
    )
    monkeypatch.setattr(treasury_yields, "download", lambda url, **options: Page(url, page.encode(), FETCHED))
    with pytest.raises(PageChanged, match=r"newest line .* \(2026-10-15\) has no Daily Summary Report link"):
        treasury_yields.latest_summary()


def test_an_older_line_without_a_usable_link_does_not_matter(monkeypatch):
    page = (
        "<h1>Daily Report</h1>"
        + line("15.10.2026", FILE_STORE + "newest")
        + line("14.10.2026", "https://example.test/api/file/old")
    )
    monkeypatch.setattr(treasury_yields, "download", lambda url, **options: Page(url, page.encode(), FETCHED))
    assert treasury_yields.find_latest()[:2] == (date(2026, 10, 15), FILE_STORE + "newest")


def test_an_empty_list_is_explained(monkeypatch):
    def empty_year(url, **options):
        return Page(url, EMPTY_YEAR.encode(), FETCHED)

    monkeypatch.setattr(treasury_yields, "download", empty_year)
    with pytest.raises(NoData, match="lists no Daily Summary Report yet"):
        treasury_yields.latest_summary()


def test_two_different_files_for_one_day_are_refused(monkeypatch):
    page = (
        "<h1>Daily Report</h1>"
        + line("13.10.2026", FILE_STORE + "first")
        + line("13.10.2026", FILE_STORE + "second")
    )
    monkeypatch.setattr(treasury_yields, "download", lambda url, **options: Page(url, page.encode(), FETCHED))
    with pytest.raises(PageChanged, match="2 different Daily Summary Report files for 2026-10-13"):
        treasury_yields.latest_summary()


def test_the_site_is_tried_once_more_when_it_does_not_answer(ministry, monkeypatch):
    working, attempts, waits = treasury_yields.download, [], []

    def flaky(url, **options):
        attempts.append(url)
        if len(attempts) == 1:
            raise SourceUnavailable("HTTP 502")
        return working(url, **options)

    monkeypatch.setattr(treasury_yields, "download", flaky)
    monkeypatch.setattr(treasury_yields.time, "sleep", waits.append)
    assert treasury_yields.latest_summary()[0] == date(2026, 10, 13)
    assert attempts == [PAGE_URL, PAGE_URL, REPORT_13_OCT]
    assert waits == [treasury_yields.RETRY_AFTER_SECONDS]


def test_after_two_failures_the_error_names_the_ministry(monkeypatch):
    def down(request, timeout):
        raise OSError("timed out")

    monkeypatch.setattr(treasury_yields.time, "sleep", lambda seconds: None)
    monkeypatch.setattr("sl_economy_mcp.fetch.urllib.request.urlopen", down)
    with pytest.raises(SourceUnavailable, match="Could not reach Sri Lanka's Ministry of Finance"):
        treasury_yields.latest_summary()


def test_a_second_look_does_not_download_again(ministry):
    treasury_yields.latest_summary()
    treasury_yields.latest_summary()
    assert len(ministry) == 2  # the page and the file, once each


@pytest.mark.parametrize(
    "address, file",
    [
        ("https://www.treasury.gov.lk/api/file/abc", FILE_STORE + "abc"),
        ("http://www.treasury.gov.lk/api/file/abc", FILE_STORE + "abc"),
        ("/api/file/abc", FILE_STORE + "abc"),
        ("https://treasury.gov.lk/api/file/abc", FILE_STORE + "abc"),
        ("HTTPS://WWW.TREASURY.GOV.LK/api/file/abc", FILE_STORE + "abc"),
        ("https://www.treasury.gov.lk/api/file/", None),
        ("https://www.treasury.gov.lk/web/report-daily-report", None),
        ("https://www.treasury.gov.lk.example.test/api/file/abc", None),  # a look-alike site
        ("javascript:alert(1)", None),
    ],
)
def test_which_links_count_as_the_ministrys_files(address, file):
    assert treasury_yields.ministry_file(address) == file


def test_excel_warnings_go_to_the_error_log_not_the_protocol_channel(capsys):
    # Standard output carries the conversation with Claude, so nothing else may write there.
    with pytest.raises(PageChanged):
        treasury_yields.open_sheet(FILE[:-3000])  # a damaged file makes xlrd warn
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "WARNING" in captured.err
