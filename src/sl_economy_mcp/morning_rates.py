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
  averaged, converted or estimated.
- Each section stands alone. If a source cannot be reached, or its page no
  longer reads the way this code expects, that section says why and shows no
  figures. The other sections are unaffected.
"""

import csv
import io
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
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
        figures.append({
            "label": label,
            "value": value,
            "date": latest,
            "shown": f"{value:.2f}%" if latest else "—",
            "for": f"{month:%b %Y}" if latest else "none published",
        })  # fmt: skip
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


# --- The prime lending rate -------------------------------------------------

LENDING_TITLE = "Commercial Bank Lending and Deposit Rates ( Per cent per annum )"
AWPR = "Average Weighted Prime Lending Rate (AWPR)"
AWPR_LOOK_BACK_DAYS = 35  # five weeks, so one late or missing week still leaves a figure


def _prime_lending_rate() -> dict:
    report = interest_rates.REPORTS["lending"]
    position, _ = report.columns["prime_lending_rate"]
    today = today_in_sri_lanka()
    start = today - timedelta(days=AWPR_LOOK_BACK_DAYS)
    page = data_library.search(report.report_id, start, today)
    rows = data_library.parse_grid(page.text, report.title, report.value_columns, {position})
    weeks = [(day, figures[position]) for day, figures in rows if figures[position] is not None]
    if not weeks:
        raise NoData(f"CBSL's Data Library lists no weekly AWPR between {start} and {today}.")

    # The table's first row of headings has six cells, and the AWPR one spans
    # three columns. The second row names those three: Weekly, Monthly, 6 months.
    # So the first column under AWPR, the one read above, is the weekly rate.
    title, groups, kinds = (data_library.heading_rows(page.text) + [[], [], []])[:3]
    _same(title, [LENDING_TITLE], "The title of CBSL's lending rates table")
    _same((len(groups), len(kinds)), (6, 5), "The number of headings in CBSL's lending rates table")
    _same([groups[2], kinds[0]], [AWPR, "Weekly"], "The prime lending rate headings in CBSL's table")

    day, rate = weeks[-1]
    figure = {
        "label": f"{AWPR}: {kinds[0]}",
        "value": rate,
        "date": day.isoformat(),
        "shown": f"{rate:.2f}%",
        "for": f"week ending {_day(day)}",
    }
    return {
        "dates_are": f"the week ending on that day (CBSL's '{groups[0]}' column)",
        "unit": "percent per year",
        "figures": [figure],
        **page.stamp(data_library.report_url(report.report_id)),
    }


# --- Treasury bills -------------------------------------------------------------


def _treasury_bills() -> dict:
    result, file_url, page, previous = bill_auctions.latest_result()
    daily_url = None
    try:
        listed_on, summary, daily = treasury_yields.latest_summary()
        daily_url = daily.url
        report = f"the Ministry's Daily Summary Report listed on {_day(listed_on)}"
        problems, check = bill_auctions.cross_check(result, previous, summary, report)
    except ExpectedProblem as problem:
        problems, check = {}, f"Not cross-checked today, because the daily report could not be read: {problem}"

    figures = []
    for days in bill_auctions.TENORS:
        isin, current, _ = result.rows.get(days, (None, None, None))
        if current is None:
            reason = f"The results table has no row for {days} days."
        elif not bill_auctions.RATE.fullmatch(current):
            reason = f"The results table shows '{current}' for {days} days, not a rate."
        else:
            reason = problems.get(days)
        figure = {
            "label": f"{days} days",
            "isin": isin,
            "value": None if reason else float(current),
            "date": result.held_on.isoformat(),
            "shown": "—" if reason else f"{current}%",
            "for": f"auction of {_day(result.held_on)}",
        }
        if reason:
            figure["not_shown_because"] = reason
        figures.append(figure)
    return {
        "report_title": result.title,
        "file_url": file_url,
        "figures_are": "Weighted Average Yield Rate (WAYR) (%), Current Auction",
        "dates_are": "the day the auction was held",
        "cross_check": check,
        "daily_report_url": daily_url,
        "figures": figures,
        **page.stamp(),
    }


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
        "Lending rate",
        LENDING_TITLE,
        f"{CBSL}, Data Library",
        data_library.report_url(interest_rates.REPORTS["lending"].report_id),
        _prime_lending_rate,
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
        notes.append(text)
        return f"note {len(notes)}"

    shown_group = None
    for section in sections:
        group = "" if section["group"] == shown_group else f"**{section['group']}**"
        shown_group = section["group"]
        source = f"[{SHORT_NAMES[section['publisher']]}: {_cell(section['title'])}]({section['source_url']})"
        if "not_available" in section:
            lines.append(f"| {group} | Not available just now ({note(section['not_available'])}) | — | — | {source} |")
            continue
        flag = f" ⚠ ({note(section['note'])})" if "note" in section else ""
        if "cross_check" in section:
            checked = f"Figures are the '{section['figures_are']}' column. {section['cross_check']}"
            group += f" ({note(checked)})"
        for figure in section["figures"]:
            why = f" ({note(figure['not_shown_because'])})" if "not_shown_because" in figure else ""
            lines.append(
                f"| {group} | {_cell(figure['label'])} | {_cell(figure['shown'])}{why} "
                f"| {_cell(figure['for'])}{flag} | {source} |"
            )
            group = ""
    for item in NOT_SHOWN:
        name = item["item"].split(" (")[0]
        lines.append(f"| **{name}** | {item['in_short']} | — | — | — |")

    lines += ["", *[f"{n}. {text}" for n, text in enumerate(notes, start=1)]] if notes else []
    lines += ["", f"*{DISCLAIMER}*"]
    return "\n".join(lines)


def get_morning_rates() -> dict:
    # Every source is read at the same time, so the sheet takes as long as the
    # slowest one, and a source that hangs cannot hold up the others: after
    # the deadline its section says so and the rest of the sheet is shown.
    pool = ThreadPoolExecutor(max_workers=len(SECTIONS))
    try:
        futures = [pool.submit(section.read) for section in SECTIONS]
        wait(futures, timeout=SHEET_DEADLINE_SECONDS)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    sections = []
    for section, future in zip(SECTIONS, futures):
        entry = {
            "group": section.group,
            "title": section.title,
            "publisher": section.publisher,
            "source_url": section.source_url,
        }
        if not future.done():
            entry["not_available"] = (
                f"{SHORT_NAMES[section.publisher]} did not answer within "
                f"{SHEET_DEADLINE_SECONDS} seconds, so this section was left out. "
                "Try again in a few minutes."
            )
        else:
            try:
                entry.update(future.result())  # a bug in this project's own code is raised here
            except ExpectedProblem as problem:
                entry["not_available"] = str(problem)
        sections.append(entry)
    today = today_in_sri_lanka()
    prepared = datetime.now(SRI_LANKA_TIME).strftime("%H:%M")
    return {
        "sheet": "Morning Sheet",
        "date": today.isoformat(),
        "prepared_at_sri_lanka": prepared,
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
        notes = [section.get("note"), section.get("cross_check")]
        for figure in section["figures"]:
            note = " ".join(text for text in notes + [figure.get("not_shown_because")] if text)
            writer.writerow([section["group"], figure["label"], figure["shown"], figure["for"], source, section["source_url"], note])
    for item in NOT_SHOWN:
        writer.writerow([item["item"].split(" (")[0], item["in_short"], "", "", "", "", ""])
    writer.writerow([])
    writer.writerow([DISCLAIMER])
    return out.getvalue()


def save_csv() -> None:
    """The `sl-economy-sheet` command: save today's sheet as morning-sheet-<date>.csv."""
    sheet = get_morning_rates()
    path = f"morning-sheet-{sheet['date']}.csv"
    # utf-8-sig lets Excel read the dashes and other characters correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        file.write(csv_text(sheet))
    unavailable = [s["group"] for s in sheet["sections"] if "not_available" in s]
    print(f"Saved {path}" + (f" (not available: {', '.join(unavailable)})" if unavailable else ""), file=sys.stderr)
