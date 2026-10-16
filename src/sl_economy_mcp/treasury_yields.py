"""The Ministry of Finance's Daily Summary Report, used to double-check auction rates.

Each business day the Public Debt Management Office at Sri Lanka's Ministry
of Finance puts an Excel file on its "Daily Report" page. One sheet in it,
"Summary Statistics", carries this table (figures from 13 October 2026):

    Weighted Average Yield       Last Primary   Last Traded Secondary   Two Way Quotes for
    Rates ( % Per Annum)         Auctions       Market Rates            13-Oct-26
                                                Buying     Selling      Bid       Offer
    Treasury Bills  <  91 Days   9.26%          9.26%      9.10%        9.28%     9.09%
                    < 182 Days   9.44%          9.25%      8.75%        9.50%     9.33%
    Treasury Bonds  < 2 Year     13.83%         -          -            10.38%    10.17%

The morning sheet takes its Treasury bill rates from the auction results
themselves (see bill_auctions.py), because they carry the date of the auction.
This report is the second, independent official source: its "Last Primary
Auctions" column must show the same rates, or the sheet shows nothing.

Getting it takes three steps: find the day's link on the page, download the
file, read the table. Before any figure is read, the sheet is compared cell
by cell with the layout written out below, so a table that has moved is
reported and never misread.
"""

import re
import sys
import time
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import xlrd

from .errors import NoData, PageChanged, SourceUnavailable
from .fetch import Page, cached, download

SITE = "Sri Lanka's Ministry of Finance"
SITE_ROOT = "https://www.treasury.gov.lk/"
SITE_HOSTS = ("www.treasury.gov.lk", "treasury.gov.lk")
PAGE_URL = "https://www.treasury.gov.lk/web/report-daily-report"  # leads to this year's list
FILE_STORE = "https://www.treasury.gov.lk/api/file/"  # the only place a file is downloaded from
PAGE_TITLE = "Daily Report"
LINK_TEXT = "Daily Summary Report"
SHEET = "Summary Statistics"

TIMEOUT_SECONDS = 60  # the file is about 600 KB and has taken 3 to 12 seconds
RETRY_AFTER_SECONDS = 5  # the site has answered "HTTP 502" and then worked on the next try
PAGE_CACHE_SECONDS = 5 * 60
FILE_CACHE_SECONDS = 60 * 60  # a new or amended report gets a new address, so a file never changes

# --- The layout this code expects -----------------------------------------

TITLE = "GOVERNMENT SECURITIES MARKET"
TRADES_FOR = "DAILY SUMMARY OF SECONDARY MARKET TRANSACTIONS FOR"
QUOTES_FOR = "TWO WAY QUOTES FOR"
RATES_HEADING = "Weighted Average Yield Rates ( % Per Annum)"
AUCTION = "Last Primary Auctions"
TRADED = "Last Traded Secondary Market Rates (Reported by PDs.)"
QUOTES = "Two Way Quotes for"
BILLS, BONDS = "Treasury Bills", "Treasury Bonds"

# What the sheet must say and where, as (row, column) counted from zero.
# Extra spaces are ignored, so the sheet's "<  91 Days" matches "< 91 Days".
HEADINGS = {
    (0, 0): TITLE,
    (1, 0): TRADES_FOR,
    (2, 0): QUOTES_FOR,
    (4, 0): RATES_HEADING,
    (4, 2): AUCTION,
    (4, 3): TRADED,
    (4, 5): QUOTES,
    (5, 3): "Buying",
    (5, 4): "Selling",
    (5, 5): "Bid",
    (5, 6): "Offer",
    (6, 0): BILLS,
    (9, 0): BONDS,
}
MATURITIES = [  # column 1, from row 6 down: three rows of bills, then ten of bonds
    "< 91 Days", "< 182 Days", "< 364 Days",
    "< 2 Year", "< 3 Year", "< 4 Year", "< 5 Year", "< 6Year", "< 8Year",
    "<10Year", "< 15Year", "< 20Year", "< 30Year",
]  # fmt: skip
FIRST_ROW, FIRST_BOND_ROW = 6, 9
FIGURE_COLUMNS = range(2, 7)  # auction, buying, selling, bid, offer
TRADES_DATE, QUOTES_DATE, QUOTES_DATE_AGAIN = (1, 5), (2, 5), (4, 6)
SHOWN_AS = "0.00%"  # how Excel is told to display every figure: percent, two decimals
ROWS_READ, COLUMNS_READ = 40, 7  # the corner of the sheet that holds all of the above


@dataclass(frozen=True)
class Cell:
    """One cell of the sheet, reduced to what this code needs to know."""

    kind: str  # "text", "number", "date" or "empty"
    value: object = None  # the words, the number or the day
    shown_as: str = ""  # Excel's display format for the cell, e.g. "0.00%"


EMPTY = Cell("empty")
Grid = dict[tuple[int, int], Cell]  # (row, column) -> cell; empty cells are left out


@dataclass(frozen=True)
class Summary:
    trades_date: date  # beside "DAILY SUMMARY OF SECONDARY MARKET TRANSACTIONS FOR"
    quotes_date: date  # beside "TWO WAY QUOTES FOR"
    rows: list[tuple[str, str, list[float | None]]]  # group, maturity, the five figures across
    source_line: str | None  # the "Source : ..." line printed under the tables


# --- Step 1: find the day's link on the Daily Report page -----------------

DATED_LINE = re.compile(r">\s*(\d\d)\s*\.\s*(\d\d)\s*\.\s*(\d{4})")  # "> 13.10.2026"


class _PageText(HTMLParser):
    """The visible text of a page, remembering which part of it each link covers."""

    def __init__(self):
        super().__init__()
        self.text = ""
        self.links: list[tuple[int, int, str]] = []  # start and end in the text, and the address
        self._open: tuple[int, str] | None = None  # the link we are inside, if any
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skipping += 1
        elif tag == "a":
            self._open = (len(self.text), dict(attrs).get("href") or "")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skipping:
            self._skipping -= 1
        elif tag == "a" and self._open:
            self.links.append((self._open[0], len(self.text), self._open[1]))
            self._open = None

    def handle_data(self, data):
        if not self._skipping:
            self.text += data


def ministry_file(address: str) -> str | None:
    """A link as a full address in the Ministry's file store, or None if it points anywhere else.

    The Ministry's pages are typed by hand, so the same kind of link appears as
    "https://www.treasury.gov.lk/api/file/...", as "http://..." (seen on the
    15 October 2026 line) and as "/api/file/..." with no website name.
    """
    parts = urlsplit(urljoin(SITE_ROOT, address.strip()))
    if parts.scheme not in ("http", "https") or parts.hostname not in SITE_HOSTS:
        return None
    if not parts.path.startswith("/api/file/") or len(parts.path) <= len("/api/file/"):
        return None
    return FILE_STORE + parts.path[len("/api/file/") :]


def _names_the_report(words: str) -> bool:
    """Whether a link's words are "Daily Summary Report", allowing for how it is typed."""
    return "dailysummaryrepor" in "".join(words.split()).lower()


def parse_listing(html: str) -> list[tuple[date, str | None]]:
    """Every Daily Summary Report link on the page with the date of its line, top line first.

    A line that names the report but has no link this tool can follow comes
    back with None instead of an address, so that it is never silently skipped.

    The page is typed by hand, one line per business day:

        > 13.10.2026  Outright Treasury Bond Transactions Volumes as at ...  Daily Summary Report

    so the typing varies. A date may have a stray space in it, the link's
    words are sometimes split across two links to the same file, and the
    final "t" sometimes falls outside the link.
    """
    reader = _PageText()
    reader.feed(html)
    text = reader.text
    if PAGE_TITLE not in text:
        raise PageChanged(
            f"{SITE} did not return its '{PAGE_TITLE}' page. The site may be "
            "blocking this tool, or the page has changed and this tool needs updating."
        )

    marks = list(DATED_LINE.finditer(text))
    found = []
    for mark, following in zip(marks, marks[1:] + [None]):
        try:
            listed_on = date(int(mark[3]), int(mark[2]), int(mark[1]))
        except ValueError:
            continue  # a mistyped date such as 31.02.2026: that line is left out
        line_end = following.start() if following else len(text)
        words: dict[str | None, str] = {}  # file -> everything on this line that links to it
        for start, end, address in reader.links:
            if mark.end() <= start < line_end:
                file = ministry_file(address)
                words[file] = words.get(file, "") + text[start:end]
        files = [(listed_on, file) for file, said in words.items() if _names_the_report(said)]
        if not files and _names_the_report(text[mark.end() : line_end]):
            files = [(listed_on, None)]  # named on the line, but not as a link we can follow
        found += files

    if not found and _names_the_report(text):
        raise PageChanged(
            f"The '{PAGE_TITLE}' page mentions the {LINK_TEXT} but its dated lines "
            "could not be read. The page has probably changed and this tool needs updating."
        )
    return found


def find_latest() -> tuple[date, str, Page]:
    """The top line of the Daily Report page, the newest report.

    Returns the date typed on that line, the file's address and the page.
    """
    page = ministry_get(PAGE_URL, PAGE_CACHE_SECONDS)
    lines = parse_listing(page.text)
    if not lines:
        raise NoData(f"The '{PAGE_TITLE}' page at {page.url} lists no {LINK_TEXT} yet.")
    newest = lines[0][0]
    files = {address for listed_on, address in lines if listed_on == newest}
    if None in files:
        raise PageChanged(
            f"The newest line of the '{PAGE_TITLE}' page ({newest}) has no {LINK_TEXT} "
            f"link to the Ministry's files that this tool can follow. Open {page.url} "
            "to check by hand."
        )
    if len(files) != 1:
        raise PageChanged(
            f"The '{PAGE_TITLE}' page lists {len(files)} different {LINK_TEXT} files "
            f"for {newest}, and this tool will not guess which is right. Open "
            f"{page.url} and choose by hand."
        )
    return newest, files.pop(), page


# --- Step 2: download ------------------------------------------------------


def ministry_get(url: str, keep_seconds: int) -> Page:
    """Download from the Ministry's site, trying once more if it does not answer."""

    def twice() -> Page:
        try:
            return download(url, timeout=TIMEOUT_SECONDS, site=SITE)
        except SourceUnavailable:
            time.sleep(RETRY_AFTER_SECONDS)
        return download(url, timeout=TIMEOUT_SECONDS, site=SITE)

    return cached(("treasury", url), twice, seconds=keep_seconds)


# --- Step 3: read the table -------------------------------------------------


def open_sheet(body: bytes) -> Grid:
    """The top corner of the Summary Statistics sheet, cell by cell.

    This is the only function that deals with Excel. Everything after it
    works on the plain grid it returns, which keeps the checks easy to test.
    """
    try:
        # xlrd prints its warnings to standard output unless told otherwise, and
        # standard output is the channel the MCP server talks to Claude on.
        book = xlrd.open_workbook(
            file_contents=body, formatting_info=True, on_demand=True, logfile=sys.stderr
        )
        sheet = book.sheet_by_name(SHEET)
        grid = {}
        for row in range(min(sheet.nrows, ROWS_READ)):
            for column in range(min(sheet.ncols, COLUMNS_READ)):
                cell = sheet.cell(row, column)
                shown_as = book.format_map[book.xf_list[cell.xf_index].format_key].format_str
                if cell.ctype == xlrd.XL_CELL_TEXT and cell.value.strip():
                    grid[row, column] = Cell("text", " ".join(cell.value.split()), shown_as)
                elif cell.ctype == xlrd.XL_CELL_NUMBER:
                    grid[row, column] = Cell("number", cell.value, shown_as)
                elif cell.ctype == xlrd.XL_CELL_DATE:
                    day = xlrd.xldate_as_datetime(cell.value, book.datemode).date()
                    grid[row, column] = Cell("date", day, shown_as)
                elif cell.ctype in (xlrd.XL_CELL_BOOLEAN, xlrd.XL_CELL_ERROR):
                    grid[row, column] = Cell("other", cell.value, shown_as)  # e.g. Excel's #N/A
        return grid
    except Exception as error:  # xlrd raises many kinds of error for a file it cannot read
        raise PageChanged(
            f"The {LINK_TEXT} is no longer an old-format Excel file with a '{SHEET}' "
            "sheet. The report has probably changed and this tool needs updating."
        ) from error


def _name(place: tuple[int, int]) -> str:
    """A cell's name as Excel writes it: row 4, column 2 is "C5"."""
    row, column = place
    return f"{'ABCDEFG'[column]}{row + 1}"


def _holds(cell: Cell) -> str:
    """What a cell contains, for an error message."""
    return "nothing" if cell.kind == "empty" else f"'{cell.value}'"


def as_displayed(fraction: float) -> float:
    """A stored fraction as the sheet shows it: a percentage to two decimal places.

    The file stores more digits than it shows: 0.09824999999999999 appears on
    the sheet as 9.83%. Excel gets there by keeping 15 significant digits,
    which makes it 0.09825, and rounding halves upwards. Python's own round()
    works on the exact stored number and says 9.82, one hundredth away from
    what a person reading the sheet sees. So we round Excel's way.
    """
    fifteen_digits = Decimal(format(fraction, ".15g"))
    return float((fifteen_digits * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _figure(grid: Grid, place: tuple[int, int]) -> float | None:
    """One yield as the sheet shows it, or None where the sheet has "-" or nothing."""
    cell = grid.get(place, EMPTY)
    if cell.kind == "empty" or (cell.kind == "text" and cell.value == "-"):
        return None
    if cell.kind != "number" or cell.shown_as != SHOWN_AS or not 0 < cell.value < 1:
        raise PageChanged(
            f"Cell {_name(place)} of the {LINK_TEXT}'s '{SHEET}' sheet holds "
            f"{_holds(cell)} (displayed as '{cell.shown_as}'), not a yield displayed "
            f"as '{SHOWN_AS}'. No figures were read. The sheet has probably changed "
            "and this tool needs updating."
        )
    return as_displayed(cell.value)


def read_summary(grid: Grid) -> Summary:
    """Check the sheet against the layout above, then read the yields table."""
    expected = dict(HEADINGS)
    expected.update({(FIRST_ROW + n, 1): label for n, label in enumerate(MATURITIES)})
    for place, words in expected.items():
        cell = grid.get(place, EMPTY)
        if cell.kind != "text" or cell.value != words:
            raise PageChanged(
                f"Cell {_name(place)} of the {LINK_TEXT}'s '{SHEET}' sheet holds "
                f"{_holds(cell)} where this tool expects '{words}'. The layout has "
                "changed, so no figures were read and this tool needs updating."
            )

    def day_at(place: tuple[int, int]) -> date:
        cell = grid.get(place, EMPTY)
        if cell.kind != "date":
            raise PageChanged(
                f"Cell {_name(place)} of the {LINK_TEXT}'s '{SHEET}' sheet should "
                f"hold a date but holds {_holds(cell)}. No figures were read."
            )
        return cell.value

    trades_date, quotes_date = day_at(TRADES_DATE), day_at(QUOTES_DATE)
    if day_at(QUOTES_DATE_AGAIN) != quotes_date:
        raise PageChanged(
            f"The {LINK_TEXT}'s '{SHEET}' sheet gives two different dates for its "
            f"two-way quotes ({quotes_date} in {_name(QUOTES_DATE)} and "
            f"{day_at(QUOTES_DATE_AGAIN)} in {_name(QUOTES_DATE_AGAIN)}). No figures were read."
        )

    rows = []
    for n, maturity in enumerate(MATURITIES):
        row = FIRST_ROW + n
        figures = [_figure(grid, (row, column)) for column in FIGURE_COLUMNS]
        rows.append((BILLS if row < FIRST_BOND_ROW else BONDS, maturity, figures))

    # Under the tables the sheet names its own source. Quoted if found, not required.
    first_column = [cell for (_, column), cell in sorted(grid.items()) if column == 0]
    source_lines = [c.value for c in first_column if c.kind == "text" and c.value.startswith("Source")]
    return Summary(trades_date, quotes_date, rows, source_lines[0] if source_lines else None)


# --- The newest report ------------------------------------------------------


def latest_summary() -> tuple[date, Summary, Page]:
    """The newest Daily Summary Report: the date it is listed under, what it says, and the file."""
    listed_on, file_url, _ = find_latest()
    file = ministry_get(file_url, FILE_CACHE_SECONDS)
    return listed_on, read_summary(open_sheet(file.body)), file
