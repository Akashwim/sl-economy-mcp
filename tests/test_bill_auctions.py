"""Tests for reading the Treasury bill auction results, without the internet.

They use a saved copy of the Ministry of Finance's results page (16 October
2026), the real results PDF for the auction of 14 October 2026, and the text
of the "Phase II" notice that followed it. Two things were removed from the
saved copies before they were added here: the PDF's document details (its
author's name) and the notice's "[Limited Sharing]" stamp line.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sl_economy_mcp import bill_auctions
from sl_economy_mcp.bill_auctions import LISTING_URL, Result
from sl_economy_mcp.errors import NoData, PageChanged
from sl_economy_mcp.fetch import Page
from sl_economy_mcp.treasury_yields import FILE_STORE, Summary

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "bill_auction_results_page_2026-10-16.html").read_text(encoding="utf-8")
PDF = (FIXTURES / "bill_auction_2026-10-14.pdf").read_bytes()
TABLE_TEXT = bill_auctions.pdf_text(PDF)
PHASE_II_TEXT = (FIXTURES / "bill_auction_2026-10-14_phase_ii.txt").read_text(encoding="utf-8")
FETCHED = datetime(2026, 10, 16, 4, 0, tzinfo=timezone.utc)

HELD_ON = date(2026, 10, 14)
RESULTS_FILE = FILE_STORE + "e2e42399-1bd0-4e24-86ef-2f6bfaaf275c"  # listed 14 Oct: the table
PHASE_II_FILE = FILE_STORE + "96a04677-bbfc-4848-a833-a2b22864f0af"  # listed 15 Oct: the notice
RESULT = Result(
    HELD_ON,
    "TREASURY BILL AUCTION HELD ON 14 OCTOBER 2026",
    {91: ("LKA09127A158", "9.30", "9.26"), 182: ("LKA18227D167", "9.44", "9.44"), 364: ("LKA36427J150", "9.95", "9.95")},
)


def line(listed: str, held: str, address: str, language: str = "English") -> str:
    """One line of the results page, as the Ministry types it."""
    return (
        f'<p>&gt; {listed} <a href="{address}">Press Release-TREASURY BILL AUCTION '
        f"HELD ON {held} | {language}</a></p>"
    )


# --- Step 1: the list of results ------------------------------------------------


def test_lists_every_english_result_newest_first():
    files = bill_auctions.parse_listing(PAGE)
    assert files[:2] == [(HELD_ON, PHASE_II_FILE), (HELD_ON, RESULTS_FILE)]
    assert files[2][0] == date(2026, 10, 7)
    assert len({held_on for held_on, _ in files}) == 42  # weekly auctions listed on the 2026 page
    assert all(address.startswith(FILE_STORE) for _, address in files)


def test_an_old_http_address_is_read_as_https():
    # The page gives the Phase II notice of 14 October as "http://www.treasury...".
    assert 'href="http://www.treasury.gov.lk/api/file/96a04677' in PAGE
    assert (HELD_ON, PHASE_II_FILE) in bill_auctions.parse_listing(PAGE)


def test_sinhala_and_tamil_releases_are_left_out():
    page = (
        "<h1>Treasury Bills</h1>"
        + line("14.10.2026", "14 October 2026", FILE_STORE + "sinhala", "Sinhala")
        + line("14.10.2026", "14 October 2026", "/api/file/tamil", "Tamil")
        + line("14.10.2026", "14 October 2026", FILE_STORE + "english")
    )
    assert bill_auctions.parse_listing(page) == [(HELD_ON, FILE_STORE + "english")]


def test_an_english_link_elsewhere_is_kept_as_unfollowable_not_skipped():
    page = (
        "<h1>Treasury Bills</h1>"
        + line("14.10.2026", "14 October 2026", "https://example.test/api/file/x")
        + line("14.10.2026", "14 October 2026", "/api/file/y")
    )
    assert bill_auctions.parse_listing(page) == [(HELD_ON, None), (HELD_ON, FILE_STORE + "y")]


def test_ordinal_dates_and_mistyped_dates():
    page = (
        "<h1>Treasury Bills</h1>"
        + line("08.10.2026", "7th October 2026", FILE_STORE + "a")
        + line("01.10.2026", "31 September 2026", FILE_STORE + "impossible")
    )
    assert bill_auctions.parse_listing(page) == [(date(2026, 10, 7), FILE_STORE + "a")]


def test_a_blocked_or_changed_page_is_reported():
    with pytest.raises(PageChanged, match="did not return its 'Treasury Bills'"):
        bill_auctions.parse_listing("<html><body>Access Denied</body></html>")
    unreadable = "<h1>Treasury Bills</h1><div>TREASURY BILL AUCTION HELD ON 14.10.26</div>"
    with pytest.raises(PageChanged, match="could not be read"):
        bill_auctions.parse_listing(unreadable)
    assert bill_auctions.parse_listing("<h1>Treasury Bills</h1>") == []  # a new, empty year


# --- Step 2: reading one result ---------------------------------------------------


def test_reads_the_real_results_pdf():
    assert bill_auctions.read_result(TABLE_TEXT, HELD_ON) == RESULT


def test_a_phase_ii_notice_has_no_table():
    assert bill_auctions.read_result(PHASE_II_TEXT, HELD_ON) is None


def test_a_result_whose_title_gives_another_date_is_refused():
    with pytest.raises(PageChanged, match="gives a different date"):
        bill_auctions.read_result(TABLE_TEXT, date(2026, 10, 7))


def test_changed_headings_stop_everything():
    # The two rates are read by position, so their headings must be in this order.
    swapped = TABLE_TEXT.replace("Current \nAuction \nLast", "Last \nAuction \nCurrent")
    assert swapped != TABLE_TEXT
    with pytest.raises(PageChanged, match="no longer has the headings"):
        bill_auctions.read_result(swapped, HELD_ON)


def test_a_file_that_is_not_a_pdf_is_reported():
    with pytest.raises(PageChanged, match="no longer a PDF"):
        bill_auctions.pdf_text(b"<html>502 Bad Gateway</html>")


# --- The newest result -----------------------------------------------------------


@pytest.fixture
def ministry(monkeypatch):
    """Make the Ministry's site return the saved page, and each PDF's text."""
    asked = []
    texts = {RESULTS_FILE: TABLE_TEXT, PHASE_II_FILE: PHASE_II_TEXT}

    def fake_download(url, **options):
        asked.append(url)
        if url.startswith(FILE_STORE):
            return Page(url, url.encode(), FETCHED)  # the "PDF" is its own address
        return Page(f"{url}/section/2026", PAGE.encode(), FETCHED)

    monkeypatch.setattr(bill_auctions, "ministry_get", lambda url, keep_seconds: fake_download(url))
    monkeypatch.setattr(bill_auctions, "pdf_text", lambda body: texts[body.decode()])
    return asked, texts


def test_the_newest_auction_is_read_from_whichever_release_has_the_table(ministry):
    asked, _ = ministry
    result, address, page, previous = bill_auctions.latest_result()
    assert result == RESULT
    assert address == RESULTS_FILE
    assert previous == date(2026, 10, 7)
    assert page.url == f"{LISTING_URL}/section/2026"
    assert asked == [LISTING_URL, PHASE_II_FILE, RESULTS_FILE]  # both releases are opened


def test_two_different_tables_for_one_auction_are_refused(ministry):
    _, texts = ministry
    texts[PHASE_II_FILE] = TABLE_TEXT.replace("9.30 9.26", "9.31 9.26")  # e.g. an amended result
    with pytest.raises(PageChanged, match="more than one results table"):
        bill_auctions.latest_result()


def test_an_unfollowable_newest_table_is_reported_not_replaced_by_last_week(monkeypatch):
    # If the newest auction's table cannot be opened, the auction before it must
    # not quietly stand in as "the latest".
    page = (
        "<h1>Treasury Bills</h1>"
        + line("14.10.2026", "14 October 2026", "https://example.test/api/file/new")
        + line("07.10.2026", "07 October 2026", RESULTS_FILE)
    )
    monkeypatch.setattr(bill_auctions, "ministry_get", lambda url, keep_seconds: Page(url, page.encode(), FETCHED))
    with pytest.raises(PageChanged, match="auction of 2026-10-14"):
        bill_auctions.latest_result()


def test_no_readable_table_for_the_newest_auction_is_reported(ministry):
    _, texts = ministry
    texts[RESULTS_FILE] = PHASE_II_TEXT
    with pytest.raises(PageChanged, match="None of the English releases for the Treasury bill auction of 2026-10-14"):
        bill_auctions.latest_result()


def test_an_empty_list_looks_at_last_years(monkeypatch):
    asked = []

    def empty(url, keep_seconds):
        asked.append(url)
        return Page(url, b"<h1>Treasury Bills</h1>", FETCHED)

    monkeypatch.setattr(bill_auctions, "ministry_get", empty)
    monkeypatch.setattr(bill_auctions, "today_in_sri_lanka", lambda: date(2027, 1, 2))
    with pytest.raises(NoData, match="lists no results"):
        bill_auctions.latest_result()
    assert asked == [LISTING_URL, f"{LISTING_URL}/section/2026"]


# --- Step 3: the check against the daily report -------------------------------------


def daily(trades_on: date, rates: list[float]) -> Summary:
    """A daily report whose "Last Primary Auctions" column shows `rates` for the three bills."""
    rows = [
        ("Treasury Bills", label, [rate, None, None, None, None])
        for label, rate in zip(["< 91 Days", "< 182 Days", "< 364 Days"], rates)
    ]
    return Summary(trades_on, trades_on, rows, None)


def test_a_report_after_the_auction_must_show_its_rates():
    problems, said = bill_auctions.cross_check(RESULT, date(2026, 10, 7), daily(HELD_ON, [9.30, 9.44, 9.95]), "the report")
    assert problems == {}
    assert "agree" in said and "'Current Auction'" in said


def test_a_report_from_before_the_auction_must_show_the_last_auctions_rates():
    # On auction day the result is out before the next daily report, which
    # still shows the week before's rates: the result's "Last Auction" column.
    problems, said = bill_auctions.cross_check(RESULT, date(2026, 10, 7), daily(date(2026, 10, 13), [9.26, 9.44, 9.95]), "the report")
    assert problems == {}
    assert "'Last Auction'" in said


def test_a_disagreement_names_both_figures():
    problems, said = bill_auctions.cross_check(RESULT, date(2026, 10, 7), daily(HELD_ON, [9.30, 9.45, 9.95]), "the report")
    assert list(problems) == [182]
    assert "is 9.44%, but the report shows 9.45%" in problems[182]
    assert "disagreements" in said


def test_a_report_older_than_the_last_two_auctions_cannot_confirm_anything():
    problems, said = bill_auctions.cross_check(RESULT, date(2026, 10, 7), daily(date(2026, 10, 1), [1.0, 1.0, 1.0]), "the report")
    assert problems == {}
    assert said.startswith("Not cross-checked")


def test_english_split_across_two_links_is_still_english():
    page = (
        '<h1>Treasury Bills</h1><p>&gt; 14.10.2026 '
        f'<a href="{FILE_STORE}x">Press Release-TREASURY BILL AUCTION HELD ON 14 October 2026 | Eng</a>'
        f'<a href="{FILE_STORE}x">lish</a></p>'
    )
    assert bill_auctions.parse_listing(page) == [(HELD_ON, FILE_STORE + "x")]


def test_two_rows_for_one_bill_are_refused():
    doubled = TABLE_TEXT.replace("364 \nLKA36427J150", "182 \nLKA36427J150")
    assert doubled != TABLE_TEXT
    with pytest.raises(PageChanged, match="more than one row for 182 days"):
        bill_auctions.read_result(doubled, HELD_ON)


def test_headings_without_readable_rows_are_refused():
    flattened = TABLE_TEXT.replace("91 \nLKA", "91 LKA").replace("182 \nLKA", "182 LKA").replace("364 \nLKA", "364 LKA")
    with pytest.raises(PageChanged, match="headings but no rows"):
        bill_auctions.read_result(flattened, HELD_ON)


def test_a_dash_in_the_daily_report_is_reported_as_no_figure():
    problems, _ = bill_auctions.cross_check(RESULT, date(2026, 10, 7), daily(HELD_ON, [9.30, None, 9.95]), "the report")
    assert "the report shows no figure" in problems[182]


def test_a_bill_with_no_rate_to_compare_is_named_not_counted_as_agreeing():
    no_last = Result(HELD_ON, RESULT.title, {**RESULT.rows, 182: ("LKA18227D167", "9.44", "-")})
    problems, said = bill_auctions.cross_check(no_last, date(2026, 10, 7), daily(date(2026, 10, 13), [9.26, 9.44, 9.95]), "the report")
    assert problems == {}
    assert said.endswith("Not compared, because the result shows no rate to compare: 182 days.")
