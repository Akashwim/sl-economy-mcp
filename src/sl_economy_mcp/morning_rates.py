"""The morning sheet: the figures a finance team collects by hand each morning.

One call gathers the latest of each, section by section:

    Section           Source
    Inflation         CBSL, Measures of Consumer Price Inflation (NCPI)
    US dollar         CBSL, Daily Indicative Exchange Rates
                      CBSL, Daily Buy and Sell Exchange Rates
    Lending rate      CBSL Data Library, Commercial Bank Lending and Deposit Rates
    Treasury bills    Public Debt Management Office, Treasury bill auction results

and lays them out as one finished table, so the sheet looks the same every
time. The rules are stricter than for the other tools, because these figures
go on to be used at work:

- Every title, heading and label is the source's own wording, and is checked
  against the page each time. Nothing is renamed.
- Every figure has its own date, and says what that date means. Nothing is
  averaged, converted or estimated. A figure older than its source normally
  lets it get is flagged, in case the source has stopped updating.
- Each section stands alone. If a source cannot be reached, or its page no
  longer reads the way this code expects, that section says why and shows no
  figures. The other sections are unaffected.
- A Treasury bill rate is shown only when two Ministry documents agree on it:
  the auction result and the daily report. Without that check, none is shown.
- A section whose website is slow says "Loading" and shows no figures. Its
  downloads carry on, and the assistant is asked to look again, which waits
  for them for up to FOLLOW_UP_SECONDS.
"""

import calendar
import csv
import io
import logging
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import bill_auctions, data_library, exchange_rates, inflation, interest_rates, treasury_yields
from .dates import SRI_LANKA_TIME, today_in_sri_lanka
from .errors import ExpectedProblem, NoData, PageChanged
from .fetch import fetch
from .tables import heading_cells, rows_of_cells

CBSL = "Central Bank of Sri Lanka"
PDMO = "Public Debt Management Office, Ministry of Finance"
SHORT_NAMES = {CBSL: "CBSL", f"{CBSL}, Data Library": "CBSL Data Library", PDMO: "Ministry of Finance (PDMO)"}
SHEET_DEADLINE_SECONDS = 45  # the whole sheet answers within this, even if one source hangs
FOLLOW_UP_SECONDS = 30  # the most a second look waits for a section still loading; the sheet says so

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Unofficial tool, not affiliated with the Central Bank of Sri Lanka or the "
    "Ministry of Finance. Figures are read from their public websites and may "
    "contain errors, so confirm a figure against its source before using it in "
    "a document. Not investment advice."
)


def _same(found, expected, what: str) -> None:
    """Stop unless a heading read from a page is the one this sheet was built on."""
    if found != expected:
        raise PageChanged(
            f"{what} reads {found!r} where this sheet expects {expected!r}. The page "
            "has changed, so its figures are not shown and this tool needs updating."
        )


def _cell(text) -> str:
    """Text made safe for one cell of the table: a "|" would start a new column."""
    return str(text).replace("|", "\\|")


def _day(day: date) -> str:
    """A date for people to read: 14 Oct 2026."""
    return f"{day.day} {day:%b %Y}"


# How old each kind of figure normally gets before its source publishes the
# next one, in days. Older than this, the figure is still shown (it is still
# the source's latest) but flagged: the source may have stopped updating, as
# CBSL's Treasury bill data did in July 2026, and an old figure must not pass
# for a current one.
USUALLY_AT_MOST_DAYS = {
    "month": 75,  # counted from the month's last day: a month is published within about seven weeks
    "week": 21,  # counted from the week's end: AWPR for a week is out by the following Monday
    "auction": 16,  # Treasury bill auctions are weekly; a holiday week can add a few days
}
LOOKS_AFTER = "Please tell the person who looks after this tool for your team."


def _late(day: date, kind: str, what: str) -> str | None:
    """A warning if a figure dated `day` is older than its kind usually gets, else None."""
    age, limit = (today_in_sri_lanka() - day).days, USUALLY_AT_MOST_DAYS[kind]
    if age <= limit:
        return None
    return (
        f"Older than usual: {what} is normally no more than {limit} days old, and this one "
        f"is {age} days old. The source may have stopped updating, so check it before using "
        f"this figure. If this lasts more than a few days: {LOOKS_AFTER.lower()}"
    )


# --- Inflation ------------------------------------------------------------

INDEXES = ["Colombo Consumer Price Index (CCPI)", "National Consumer Price Index (NCPI)"]
MEASURES = ["Headline Inflation (Y-o-Y)", "Core Inflation (Y-o-Y)"] * 2  # under each index
SHOWN_MEASURES = ("ncpi_headline", "ncpi_core")  # the team uses NCPI, not CCPI (Akash, 14 Oct 2026)


def inflation_labels(html: str) -> list[str]:
    """CBSL's own headings for the four columns of its inflation table.

    The table has two rows of headings, the index and then the measure. Each
    label joins the two, for example "National Consumer Price Index (NCPI)
    (NCPI, 2021=100): Headline Inflation (Y-o-Y)". The base year in brackets
    is read from the page, because CBSL moves it from time to time.
    """
    rows = rows_of_cells(html)
    top = next((n for n, cells in enumerate(rows[:-1]) if cells[:1] == ["Date"]), None)
    if top is None:
        raise PageChanged(
            "CBSL's inflation table no longer has a heading row starting 'Date'. The "
            "page has changed, so its figures are not shown and this tool needs updating."
        )
    indexes, measures = rows[top][1:], rows[top + 1][1:]
    starts = [index[: len(expected)] for index, expected in zip(indexes, INDEXES)]
    _same(starts if len(indexes) == 2 else indexes, INDEXES, "The index headings of CBSL's inflation table")
    _same(measures, MEASURES, "The column headings of CBSL's inflation table")
    return [f"{indexes[n // 2]}: {measure}" for n, measure in enumerate(measures)]


def _inflation() -> dict:
    page = fetch(inflation.TABLE_URL)
    table = inflation.parse_inflation_table(page.text)
    figures = []
    for measure, label in zip(inflation.MEASURES, inflation_labels(page.text)):
        if measure not in SHOWN_MEASURES:
            continue
        published = [month for month, row in table.items() if row[measure] is not None]
        latest = max(published) if published else None
        value = table[latest][measure] if latest else None
        month = datetime.strptime(latest, "%Y-%m") if latest else None
        figure = {
            "label": label,
            "value": value,
            "date": latest,
            "shown": f"{value:.2f}%" if latest else "—",
            "for": f"{month:%b %Y}" if latest else "none published",
        }
        if month:
            late = _late(_month_end(month.date()), "month", "a month's inflation figure, counted from the month's end,")
            if late:
                figure["late"] = late
        figures.append(figure)
    return {
        "dates_are": "the month the inflation figure measures",
        "unit": "percent",
        "figures": figures,
        **page.stamp(inflation.PUBLIC_URL),
    }


# --- The US dollar ---------------------------------------------------------


def _usd(form: exchange_rates.LookupForm, headings: list[str], shown: int) -> dict:
    """The latest US dollar row of one CBSL exchange rate table.

    `headings` is the table's heading row as this sheet expects it, and
    `shown` is how many of the columns after the date go on the sheet.
    """
    names = exchange_rates.currencies(form)
    if "USD" not in names:
        raise PageChanged("CBSL's exchange rate form no longer lists USD. This tool needs updating.")
    today = today_in_sri_lanka()
    start = today - timedelta(days=exchange_rates.LOOK_BACK_DAYS)
    rows, page = exchange_rates.lookup(form, "USD", start, today)
    _same(heading_cells(page.text), headings, "The heading row of CBSL's exchange rate table")
    if names["USD"] not in page.text:
        raise PageChanged(
            f"CBSL's exchange rate results do not name the currency asked for ({names['USD']}). "
            "The page has changed, so its figures are not shown and this tool needs updating."
        )
    if not rows:
        raise NoData(f"CBSL lists no US dollar rate between {start} and {today}.")
    day, *rates = rows[-1]
    figures = [
        {"label": label, "value": rate, "date": day.isoformat(), "shown": f"{rate:.4f}", "for": _day(day)}
        for label, rate in zip(headings[1 : 1 + shown], rates)
    ]
    section = {
        "currency": names["USD"],
        "dates_are": "the day the rate is for (CBSL's 'Date' column)",
        "unit": "Sri Lankan rupees (LKR) per 1 US dollar",
        "figures": figures,
        **page.stamp(form.public_url),
    }
    if day < today:  # these are published every business day
        section["note"] = f"The latest published rate is for {_day(day)}, not today ({_day(today)})."
    return section


def _usd_indicative() -> dict:
    return _usd(exchange_rates.INDICATIVE, ["Date", "1 USD -> LKR", "1 LKR -> USD"], shown=1)


def _usd_buy_and_sell() -> dict:
    return _usd(exchange_rates.TT, ["Date", "Buy Rate (LKR)", "Sell Rate (LKR)"], shown=2)


# --- Lending and deposit rates ------------------------------------------------

LENDING_TITLE = "Commercial Bank Lending and Deposit Rates ( Per cent per annum )"
AWPR = "Average Weighted Prime Lending Rate (AWPR)"
# CBSL's own headings, as printed, typos included ("Weigted"). The deposit
# rate's second column, "6 months", is never explained by CBSL and is not in
# its weekly report, so it is not shown.
AWLR = "Average Weigted Lending Rate (AWLR)"
AWDR = "Average Weighted Deposit Rate"
AWFDR = "Average Weighted Fixed Deposit Rate (AWFDR) Rate (% )"
AWPR_LOOK_BACK_DAYS = 35  # five weeks, so one late or missing week still leaves a figure
# The monthly rates come out about a month after the month ends and are dated
# by its last day, so mid-month the latest can be over two months old.
MONTHLY_LOOK_BACK_DAYS = 100


def _lending_and_deposit_rates() -> dict:
    report = interest_rates.REPORTS["lending"]
    # Positions among the table's eight figures: AWLR, AWPR (Weekly, Monthly,
    # 6 months), AWDR (Monthly, 6 months), AWFDR, AWSR.
    weekly, lending, deposit, fixed = 1, 0, 4, 6
    today = today_in_sri_lanka()
    start = today - timedelta(days=MONTHLY_LOOK_BACK_DAYS)
    page = data_library.search(report.report_id, start, today)
    rows = data_library.parse_grid(page.text, report.title, report.value_columns, {weekly, lending, deposit, fixed})

    # The first row of headings has six cells: End Week, AWLR, AWPR (over
    # three columns), AWDR (over two), AWFDR, AWSR. The second row names the
    # columns under AWPR and AWDR: Weekly, Monthly, 6 months, Monthly, 6 months.
    title, groups, kinds = (data_library.heading_rows(page.text) + [[], [], []])[:3]
    _same(title, [LENDING_TITLE], "The title of CBSL's lending rates table")
    _same((len(groups), len(kinds)), (6, 5), "The number of headings in CBSL's lending rates table")
    _same(groups[1:5], [AWLR, AWPR, AWDR, AWFDR], "The rate headings in CBSL's lending rates table")
    _same([kinds[0], kinds[3]], ["Weekly", "Monthly"], "The AWPR and deposit rate column headings in CBSL's table")
    if not any(figures[p] is not None for _, figures in rows for p in (weekly, lending, deposit, fixed)):
        raise NoData(f"CBSL's Data Library lists no lending or deposit rates between {start} and {today}.")

    def latest(position: int, since: date) -> tuple[date, float] | None:
        found = [(day, figures[position]) for day, figures in rows if day >= since and figures[position] is not None]
        return found[-1] if found else None

    figures = []
    week_start = today - timedelta(days=AWPR_LOOK_BACK_DAYS)
    found = latest(weekly, week_start)
    figure = {"label": f"{AWPR}: {kinds[0]}", "value": None, "date": None, "shown": "—", "for": "—"}
    if found:
        day, rate = found
        figure.update({"value": rate, "date": day.isoformat(), "shown": f"{rate:.2f}%", "for": f"week ending {_day(day)}"})
        late = _late(day, "week", "the weekly AWPR, counted from the week's end,")
        if late:
            figure["late"] = late
    else:
        figure["not_shown_because"] = f"CBSL's Data Library lists no weekly AWPR between {week_start} and {today}."
    figures.append(figure)

    for position, label in ((lending, AWLR), (deposit, f"{AWDR}: {kinds[3]}"), (fixed, AWFDR)):
        figure = {"label": label, "value": None, "date": None, "shown": "—", "for": "—"}
        found = latest(position, start)
        if not found:
            figure["not_shown_because"] = f"CBSL's Data Library lists no '{label}' between {start} and {today}."
        elif found[0] != _month_end(found[0]):
            # A monthly figure is dated by its month's last day. Any other date
            # would leave its month unclear, so it is not shown.
            figure["not_shown_because"] = f"CBSL dates this monthly figure {found[0]}, not the last day of a month."
        else:
            day, rate = found
            figure.update({"value": rate, "date": day.isoformat(), "shown": f"{rate:.2f}%", "for": f"{day:%b %Y}"})
            late = _late(day, "month", "a monthly bank rate, counted from the month's end,")
            if late:
                figure["late"] = late
        figures.append(figure)
    return {
        "dates_are": (
            f"for AWPR, the week ending on that day (CBSL's '{groups[0]}' column); for the "
            "monthly rates, the month, which CBSL's table dates by its last day"
        ),
        "unit": "percent per year",
        "figures": figures,
        **page.stamp(data_library.report_url(report.report_id)),
    }


def _month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


# --- Treasury bills -------------------------------------------------------------


def _treasury_bills() -> dict:
    # The auction result and the daily report that confirms it do not depend on
    # each other, so they are read side by side: the section takes as long as
    # the slower of the two, not both added together.
    helper = ThreadPoolExecutor(max_workers=1)
    confirming = helper.submit(treasury_yields.latest_summary)
    helper.shutdown(wait=False)
    result, file_url, page, previous = bill_auctions.latest_result()
    try:
        listed_on, summary, daily = confirming.result()
    except ExpectedProblem as problem:
        # No rate without the check. The same kind of problem is raised, so a
        # site that is down still counts as down rather than as a changed page.
        raise type(problem)(
            "The Treasury bill auction rates are not shown, because the Ministry's daily "
            f"report, which must confirm them, could not be read. {problem}"
        ) from problem
    report = f"the Ministry's Daily Summary Report listed on {_day(listed_on)}"
    compared, problems, check = bill_auctions.cross_check(result, previous, summary, report)
    if compared is None:
        raise NoData(f"The Treasury bill auction rates are not shown, because {check}")

    # Only the column the daily report confirmed is shown. Until a daily report
    # covers the newest auction, that is the result's "Last Auction" column:
    # the rates of the auction before, dated by that auction.
    newest = compared == "Current Auction"
    held_on = result.held_on if newest else previous
    position = 1 if newest else 2  # in each row: ISIN, Current Auction, Last Auction
    figures = []
    for days in bill_auctions.TENORS:
        row = result.rows.get(days)
        printed = row[position] if row else None
        if printed is None:
            reason = f"The results table has no row for {days} days."
        elif not bill_auctions.RATE.fullmatch(printed):
            reason = f"The results table shows '{printed}' for {days} days in its '{compared}' column, not a rate."
        else:
            reason = problems.get(days)
        figure = {
            "label": f"{days} days",
            "isin": row[0] if row and newest else None,  # the ISINs printed are this week's bills
            "value": None if reason else float(printed),
            "date": held_on.isoformat(),
            "shown": "—" if reason else f"{printed}%",
            "for": f"auction of {_day(held_on)}",
        }
        if reason:
            figure["not_shown_because"] = reason
        else:
            late = _late(held_on, "auction", "a Treasury bill auction, counted from the day it was held,")
            if late:
                figure["late"] = late
        figures.append(figure)
    section = {
        "report_title": result.title,
        "file_url": file_url,
        "figures_are": f"Weighted Average Yield Rate (WAYR) (%), {compared}",
        "dates_are": "the day the auction was held",
        "cross_check": check,
        "daily_report_url": daily.url,
        "figures": figures,
        **page.stamp(),
    }
    if not newest:
        section["note"] = (
            f"The auction of {_day(result.held_on)} has results, but no daily report confirms "
            f"them yet, so these are the rates of the auction before it, {_day(previous)}, "
            "which the daily report confirms. The newer rates will appear once a daily "
            "report covers them."
        )
    return section


# --- The sheet --------------------------------------------------------------


@dataclass(frozen=True)
class Section:
    group: str  # the sheet's own heading for this part, e.g. "Inflation"
    title: str  # the source's own title for the page, table or report
    publisher: str
    source_url: str  # the page a person would open
    read: Callable[[], dict]  # fetches the figures, or raises one of our expected problems


SECTIONS = [
    Section("Inflation", "Measures of Consumer Price Inflation", CBSL, inflation.PUBLIC_URL, _inflation),
    Section(
        "US dollar",
        "Daily Indicative Exchange Rates",
        CBSL,
        exchange_rates.INDICATIVE.public_url,
        _usd_indicative,
    ),
    Section(
        "US dollar",
        "Daily Buy and Sell Exchange Rates",
        CBSL,
        exchange_rates.TT.public_url,
        _usd_buy_and_sell,
    ),
    Section(
        "Lending and deposit rates",
        LENDING_TITLE,
        f"{CBSL}, Data Library",
        data_library.report_url(interest_rates.REPORTS["lending"].report_id),
        _lending_and_deposit_rates,
    ),
    Section(
        "Treasury bills",
        "Auction Result: Treasury Bills",
        PDMO,
        bill_auctions.LISTING_URL,
        _treasury_bills,
    ),
]

DIRECTIONS = "https://www.cbsl.gov.lk/sites/default/files/cbslweb_documents/laws/cdg/"
NOT_SHOWN = [
    {
        "item": "Treasury bonds",
        "reason": (
            "To be developed with the primary dealer. Until then, please refer to "
            "the primary dealer's information."
        ),
        "in_short": (
            "To be developed with the primary dealer. Until then, please refer to "
            "the primary dealer's information."
        ),
    },
    {
        "item": "FD ceiling rate (maximum interest rates on finance company deposits)",
        "reason": (
            "Still in development. CBSL's directions set the maximum as a margin over the "
            "simple average of the latest four primary Treasury bill auction yields in "
            "the preceding quarter. No CBSL-published figure for a quarter has been found "
            "yet, and a figure worked out by this tool must be checked against an official "
            "one before it is shown. Until then, please refer to the team's existing source."
        ),
        "in_short": "Still in development. Until then, please refer to the team's existing source.",
        "rules": [
            {
                "title": "Finance Business Act Directions No.01 of 2025: "
                "Maximum Interest Rates on Deposits and Debt Instruments",
                "issued": "2025-06-23",
                "url": DIRECTIONS + "snbfi_finance_business_act_directions_no_1_of_2025_e.pdf",
            },
            {
                "title": "Finance Business Act Directions No.01 of 2026: "
                "Amendments to Maximum Interest Rates on Deposits and Debt Instruments",
                "issued": "2026-01-12",
                "url": DIRECTIONS + "snbfi_finance_business_act_directions_no_1_of_2026_e.pdf",
            },
        ],
        "rules_last_checked": "2026-10-13",
    },
]


def render(sections: list[dict], today: date, prepared: str) -> str:
    """The finished sheet as one table, with numbered notes underneath."""
    lines = [
        f"## Morning Sheet: {today:%A} {today.day} {today:%B %Y}",
        "",
        f"Prepared at {prepared}, Sri Lanka time. Every figure is the source's own, "
        "under the source's own label, with the date it is for.",
        "",
        "| Section | Item | Figure | For | Source |",
        "|---|---|---|---|---|",
    ]
    notes: list[str] = []

    def note(text: str) -> str:
        if text not in notes:  # the same message is numbered once, however many rows use it
            notes.append(text)
        return f"note {notes.index(text) + 1}"

    shown_group = None
    for section in sections:
        group = "" if section["group"] == shown_group else f"**{section['group']}**"
        shown_group = section["group"]
        source = f"[{SHORT_NAMES[section['publisher']]}: {_cell(section['title'])}]({section['source_url']})"
        if "not_available" in section:
            lines.append(f"| {group} | Not available just now ({note(section['not_available'])}) | — | — | {source} |")
            continue
        if "loading" in section:
            wait_at_most = f"up to {FOLLOW_UP_SECONDS} seconds"
            lines.append(f"| {group} | Loading, {wait_at_most} ({note(section['loading'])}) | — | — | {source} |")
            continue
        if "cross_check" in section:
            checked = f"Figures are the '{section['figures_are']}' column. {section['cross_check']}"
            group += f" ({note(checked)})"
        flag = f" ⚠ ({note(section['note'])})" if "note" in section else ""
        for figure in section["figures"]:
            why = f" ({note(figure['not_shown_because'])})" if "not_shown_because" in figure else ""
            late = f" ⚠ ({note(figure['late'])})" if "late" in figure else ""
            lines.append(
                f"| {group} | {_cell(figure['label'])} | {_cell(figure['shown'])}{why} "
                f"| {_cell(figure['for'])}{flag}{late} | {source} |"
            )
            group = ""
    for item in NOT_SHOWN:
        name = item["item"].split(" (")[0]
        lines.append(f"| **{name}** | {item['in_short']} | — | — | — |")

    lines += ["", *[f"{n}. {text}" for n, text in enumerate(notes, start=1)]] if notes else []
    lines += ["", f"*{DISCLAIMER}*"]
    return "\n".join(lines)


def _read(section: Section) -> dict:
    """One section's figures, with the time it took in the log."""
    started = time.monotonic()
    try:
        return section.read()
    finally:
        log.info("%s: section read in %.1f s", section.title, time.monotonic() - started)


# Sections still being read when an earlier sheet was handed over, by title.
# A second look waits for these instead of starting the downloads again.
_reading: dict[str, Future] = {}
_reading_lock = threading.Lock()


def get_morning_rates() -> dict:
    # Every source is read at the same time, so the sheet takes as long as the
    # slowest one, and a source that hangs cannot hold up the others: after
    # the deadline the rest of the sheet is handed over, and the slow section
    # says it is still loading. Its downloads carry on, and "check_again" asks
    # the assistant for a second look, which waits for them (up to
    # FOLLOW_UP_SECONDS) rather than starting them again.
    pool = ThreadPoolExecutor(max_workers=len(SECTIONS))
    try:
        with _reading_lock:
            futures, second_look = [], []
            for section in SECTIONS:
                earlier = _reading.get(section.title)
                if earlier is not None and not earlier.done():
                    futures.append(earlier)
                    second_look.append(True)
                else:
                    _reading[section.title] = pool.submit(_read, section)
                    futures.append(_reading[section.title])
                    second_look.append(False)
        wait(futures, timeout=FOLLOW_UP_SECONDS if any(second_look) else SHEET_DEADLINE_SECONDS)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    sections, check_again = [], False
    for section, future, again in zip(SECTIONS, futures, second_look):
        entry = {
            "group": section.group,
            "title": section.title,
            "publisher": section.publisher,
            "source_url": section.source_url,
        }
        site = SHORT_NAMES[section.publisher]
        if not future.done() and again:
            entry["not_available"] = (
                f"Still loading: the {site} website has still not answered. Please ask for "
                "the sheet again in a few minutes."
            )
        elif not future.done():
            entry["loading"] = (
                f"Loading: the {site} website is slow to respond. The assistant will look "
                f"again automatically and show the finished sheet; this takes up to "
                f"{FOLLOW_UP_SECONDS} seconds. No figure is shown until it has been read and checked."
            )
            check_again = True
        else:
            try:
                entry.update(future.result())  # a bug in this project's own code is raised here
            except ExpectedProblem as problem:
                entry["not_available"] = str(problem)
                if isinstance(problem, PageChanged):  # only someone who looks after the tool can fix this
                    entry["not_available"] += f" {LOOKS_AFTER}"
        sections.append(entry)
    today = today_in_sri_lanka()
    prepared = datetime.now(SRI_LANKA_TIME).strftime("%H:%M")
    return {
        "sheet": "Morning Sheet",
        "date": today.isoformat(),
        "prepared_at_sri_lanka": prepared,
        "check_again": check_again,
        "table": render(sections, today, prepared),
        "sections": sections,
        "not_shown": NOT_SHOWN,
        "disclaimer": DISCLAIMER,
    }


# --- The sheet as a file, without an assistant ---------------------------------

CSV_COLUMNS = ["Section", "Item", "Figure", "For", "Source", "Link", "Note"]


def csv_text(sheet: dict) -> str:
    """The sheet as CSV, one row per figure, each figure written exactly as the table shows it."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([f"Morning Sheet: {sheet['date']}, prepared at {sheet['prepared_at_sri_lanka']} Sri Lanka time"])
    writer.writerow(CSV_COLUMNS)
    for section in sheet["sections"]:
        source = f"{SHORT_NAMES[section['publisher']]}: {section['title']}"
        if "not_available" in section:
            writer.writerow([section["group"], "Not available", "", "", source, section["source_url"], section["not_available"]])
            continue
        if "loading" in section:
            writer.writerow([section["group"], "Loading", "", "", source, section["source_url"], section["loading"]])
            continue
        notes = [section.get("cross_check"), section.get("note")]
        for figure in section["figures"]:
            note = " ".join(text for text in notes + [figure.get("late"), figure.get("not_shown_because")] if text)
            writer.writerow([section["group"], figure["label"], figure["shown"], figure["for"], source, section["source_url"], note])
    for item in NOT_SHOWN:
        writer.writerow([item["item"].split(" (")[0], item["in_short"], "", "", "", "", ""])
    writer.writerow([])
    writer.writerow([DISCLAIMER])
    return out.getvalue()


def save_csv() -> None:
    """The `sl-economy-sheet` command: save today's sheet as morning-sheet-<date>.csv."""
    sheet = get_morning_rates()
    if sheet["check_again"]:
        sheet = get_morning_rates()  # the second look an assistant would take
    path = f"morning-sheet-{sheet['date']}.csv"
    # utf-8-sig lets Excel read the dashes and other characters correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        file.write(csv_text(sheet))
    unavailable = [s["group"] for s in sheet["sections"] if "not_available" in s]
    print(f"Saved {path}" + (f" (not available: {', '.join(unavailable)})" if unavailable else ""), file=sys.stderr)
