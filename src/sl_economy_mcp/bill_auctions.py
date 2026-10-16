"""Treasury bill auction results, from the Public Debt Management Office.

Each week the government sells 91, 182 and 364-day Treasury bills at an
auction. The Public Debt Management Office (PDMO) at the Ministry of Finance
publishes the result as a one-page PDF, listed on the Ministry's website
under Government Securities, Auction Result, Treasury Bills:

    TREASURY BILL AUCTION HELD ON 14 OCTOBER 2026

    Maturity   Amount    Bids       Amount         Weighted Average Yield Rate (WAYR) (%)
    (Days)     Offered   Received   Accepted (a)   Current Auction    Last Auction
    91
    LKA09127A158  40,000   71,300    40,192         9.30               9.26
    ...

The morning sheet shows the "Current Auction" rates, dated by the auction.
Before a rate is shown it is checked against the Ministry's Daily Summary
Report, whose "Last Primary Auctions" column carries the same rates. If the
two official documents disagree, that rate is not shown.

Tested on every result from 2 December 2025 to 14 October 2026: 46 auctions,
each with one results table. Every table was read, each week's "Last Auction"
rates matched the previous week's "Current Auction" rates in all 135 cases,
and the daily report agreed on all 14 days compared.
"""

import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape

import pypdf

from .dates import today_in_sri_lanka
from .errors import NoData, PageChanged
from .fetch import Page
from .treasury_yields import (
    BILLS,
    FILE_CACHE_SECONDS,
    PAGE_CACHE_SECONDS,
    Summary,
    ministry_file,
    ministry_get,
)

LISTING_URL = "https://www.treasury.gov.lk/web/result-treasury-bills"  # leads to this year's list
LISTING_TITLE = "Treasury Bills"
TENORS = (91, 182, 364)  # the "Maturity (Days)" of the three bills

# The table's headings in order, as the PDF prints them once line breaks and
# extra spaces are taken out. The order matters: the two rates are read by
# position, "Current Auction" first.
HEADINGS = (
    "Maturity (Days) Amount Offered Bids Received Amount Accepted (a) "
    "Weighted Average Yield Rate (WAYR) (%) Current Auction Last Auction"
)
TITLE = re.compile(r"TREASURY BILL AUCTION HELD ON\s+(\d{1,2})\s*(?:ST|ND|RD|TH)?\s+([A-Z]+)\s+(\d{4})")
# One row of the table: the days on one line, then the ISIN and five figures.
ROW = re.compile(r"^\s*(91|182|364)\s*\n\s*(LKA\w+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", re.M)
RATE = re.compile(r"\d{1,2}\.\d\d")  # a rate as the table prints it, e.g. 9.30

# The daily report's rows for the same three bills. That they carry the same
# rates was checked on 14 days from December 2025 to October 2026.
DAILY_ROWS = {"< 91 Days": 91, "< 182 Days": 182, "< 364 Days": 364}

logging.getLogger("pypdf").setLevel(logging.ERROR)  # it warns about harmless quirks in these files


@dataclass(frozen=True)
class Result:
    held_on: date
    title: str  # as printed, e.g. "TREASURY BILL AUCTION HELD ON 14 OCTOBER 2026"
    rows: dict[int, tuple[str, str, str]]  # days -> ISIN, Current Auction, Last Auction, as printed


def _text(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _held_on(title: re.Match) -> date:
    """The date in "TREASURY BILL AUCTION HELD ON 14 OCTOBER 2026". ValueError if it is not one."""
    day, month, year = title.groups()
    return datetime.strptime(f"{day} {month.title()} {year}", "%d %B %Y").date()


# --- Step 1: the list of results ----------------------------------------------


def parse_listing(html: str) -> list[tuple[date, str | None]]:
    """Every English results file on the page with the date of its auction, top line first.

    A file whose link does not lead to the Ministry's file store comes back
    with None instead of an address, so that its auction is not silently skipped.

    The page is typed by hand, one line per file:

        > 15.10.2026  Press Release-TREASURY BILL AUCTION HELD ON 14 October 2026 | English

    Each auction has two English files: the results table, and a "Phase II"
    notice the next day about further sales at the same rates.
    """
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)  # the page's data, not its text
    if LISTING_TITLE not in _text(html):
        raise PageChanged(
            f"Sri Lanka's Ministry of Finance did not return its '{LISTING_TITLE}' auction "
            "results page. The site may be blocking this tool, or the page has changed."
        )
    found = []
    for line in re.findall(r"<p\b[^>]*>(.*?)</p>", html, re.S):
        title = TITLE.search(_text(line).upper())
        if not title:
            continue
        try:
            held_on = _held_on(title)
        except ValueError:
            continue  # a mistyped date: that line is left out
        words: dict[str, str] = {}  # address -> all the words that link to it on this line
        for address, said in re.findall(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', line, re.S):
            words[address] = words.get(address, "") + _text(said)
        for address, said in words.items():
            if "".join(said.split()).lower().endswith("english"):  # "Eng lish" counts too
                found.append((held_on, ministry_file(address)))
    if not found and "TREASURY BILL AUCTION" in _text(html).upper():
        raise PageChanged(
            "The Treasury bill auction results page lists results but its lines could "
            "not be read. The page has probably changed and this tool needs updating."
        )
    return found


# --- Step 2: read one result ----------------------------------------------------


def pdf_text(body: bytes) -> str:
    """The text of a one-page PDF. This is the only function that deals with PDFs."""
    try:
        return pypdf.PdfReader(io.BytesIO(body)).pages[0].extract_text()
    except Exception as error:  # pypdf raises many kinds of error for a file it cannot read
        raise PageChanged(
            "A Treasury bill auction result is no longer a PDF this tool can read. "
            "The results have probably changed and this tool needs updating."
        ) from error


def read_result(text: str, held_on: date) -> Result | None:
    """The results table in one release, or None if it has no table (a Phase II notice)."""
    flat = " ".join(text.split())
    rows = ROW.findall(text)
    if HEADINGS not in flat:
        if rows:
            raise PageChanged(
                f"The Treasury bill auction result for {held_on} no longer has the headings "
                f"'{HEADINGS}'. No rates were read and this tool needs updating."
            )
        return None
    title = TITLE.search(flat.upper())
    try:
        printed_date = _held_on(title) if title else None
    except ValueError:
        printed_date = None
    if printed_date != held_on:
        raise PageChanged(
            f"The Ministry's page lists a Treasury bill auction result under {held_on}, but "
            "the PDF's own title gives a different date. No rates were read."
        )
    if not rows:
        raise PageChanged(
            f"The Treasury bill auction result for {held_on} has its headings but no rows "
            "this tool can read. The layout has probably changed and this tool needs updating."
        )
    found = {}
    for days, isin, _, _, _, current, last in rows:
        if int(days) in found:
            raise PageChanged(
                f"The Treasury bill auction result for {held_on} has more than one row for "
                f"{days} days, and this tool will not choose between them. Check it by hand."
            )
        found[int(days)] = (isin, current, last)
    return Result(held_on, " ".join(title.group(0).split()), found)


def latest_result() -> tuple[Result, str, Page, date | None]:
    """The newest auction's results table.

    Returns the result, the PDF's address, the list it was found on, and the
    date of the auction before it (None if that is not on the same list).
    """
    page = ministry_get(LISTING_URL, PAGE_CACHE_SECONDS)
    files = parse_listing(page.text)
    if not files:  # early in January this year's list can still be empty
        last_year = f"{LISTING_URL}/section/{today_in_sri_lanka().year - 1}"
        page = ministry_get(last_year, PAGE_CACHE_SECONDS)
        files = parse_listing(page.text)
    if not files:
        raise NoData(f"The Ministry's Treasury bill auction results page at {page.url} lists no results.")

    auctions = sorted({held_on for held_on, _ in files}, reverse=True)
    newest = auctions[0]
    tables = []
    for held_on, address in files:
        if held_on == newest and address:
            result = read_result(pdf_text(ministry_get(address, FILE_CACHE_SECONDS).body), newest)
            if result:
                tables.append((result, address))
    if not tables:
        raise PageChanged(
            f"None of the English releases for the Treasury bill auction of {newest} has a "
            f"results table this tool can read. Open {page.url} to check by hand."
        )
    if any(result.rows != tables[0][0].rows for result, _ in tables[1:]):
        raise PageChanged(
            f"The Ministry lists more than one results table for the Treasury bill auction "
            f"of {newest}, and they differ. This tool will not guess which is right; open "
            f"{page.url} to check by hand."
        )
    result, address = tables[0]
    return result, address, page, auctions[1] if len(auctions) > 1 else None


# --- Step 3: the check against the daily report -------------------------------------


def cross_check(
    result: Result, previous: date | None, summary: Summary, report: str
) -> tuple[dict[int, str], str]:
    """Compare the auction rates with the daily report's "Last Primary Auctions" column.

    The daily report shows the rates of the latest auction held on or before
    its trading day. If that is this auction, they must equal its "Current
    Auction" rates; if it is the auction before, its "Last Auction" rates.
    `report` names the daily report in the messages.

    Returns the disagreements by bill, and one sentence saying what was checked.
    """
    if summary.trades_date >= result.held_on:
        column, compared = 1, "Current Auction"
    elif previous and summary.trades_date >= previous:
        column, compared = 2, "Last Auction"
    else:
        return {}, (
            f"Not cross-checked: {report} is for trading on {summary.trades_date}, before "
            "the last two auctions, so it cannot confirm these rates."
        )
    daily = {DAILY_ROWS[label]: figures[0] for group, label, figures in summary.rows if group == BILLS}
    problems, not_compared = {}, []
    for days, row in sorted(result.rows.items()):
        printed = row[column]
        if not RATE.fullmatch(printed):
            not_compared.append(f"{days} days")  # e.g. "-": nothing to compare
        elif daily.get(days) != float(printed):
            shown = "no figure" if daily.get(days) is None else f"{daily[days]:.2f}%"
            problems[days] = (
                f"The auction result's '{compared}' rate for {days} days is {printed}%, but "
                f"{report} shows {shown} in its 'Last Primary Auctions' column. "
                "The two official documents disagree, so this rate is not shown."
            )
    if problems:
        said = f"Checked against {report}: disagreements are listed for each bill."
    else:
        said = (
            f"Checked: the rates agree with the 'Last Primary Auctions' column of {report} "
            f"(compared with the auction result's '{compared}' column)."
        )
    if not_compared:
        said += f" Not compared, because the result shows no rate to compare: {', '.join(not_compared)}."
    return problems, said
