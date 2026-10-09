"""Monthly inflation, from the table on CBSL's inflation page.

The table lists each year as a heading row followed by a row per month:

    2026
    January   | 2.30 | 2.30 | 2.40 | 2.20
    February  | 1.60 | 2.10 | 1.60 | 2.20

The four figures are year-on-year inflation: headline and core for the
Colombo index (CCPI), then headline and core for the national index (NCPI).
"""

import re

from . import DISCLAIMER
from .dates import parse_month
from .errors import InvalidRequest, NoData, PageChanged
from .fetch import fetch
from .tables import number, rows_of_cells

TABLE_URL = "https://www.cbsl.gov.lk/cbsl_custom/inflation/inflationwindow.php"
PUBLIC_URL = "https://www.cbsl.gov.lk/en/measures-of-consumer-price-inflation"

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]  # fmt: skip

MEASURES = {
    "ccpi_headline": (
        "Colombo Consumer Price Index, all items. This is Sri Lanka's "
        "headline inflation rate and the one CBSL targets."
    ),
    "ccpi_core": "Colombo index without volatile food, energy and transport prices.",
    "ncpi_headline": "National Consumer Price Index, all items. Covers the whole country.",
    "ncpi_core": "National index without volatile food, energy and transport prices.",
}

Table = dict[str, dict[str, float | None]]  # "2026-09" -> {"ccpi_headline": 8.0, ...}


def parse_inflation_table(html: str) -> Table:
    """Every month in CBSL's table, oldest first."""
    colombo = html.find("Colombo Consumer Price Index")
    national = html.find("National Consumer Price Index")
    if colombo == -1 or not colombo < national or "Headline Inflation" not in html:
        raise PageChanged(
            "CBSL's inflation table no longer has the expected CCPI and NCPI "
            "columns. The page has probably changed and this tool needs updating."
        )

    table, year = {}, None
    for cells in rows_of_cells(html):
        if len(cells) == 1 and re.fullmatch(r"\d{4}", cells[0]):
            year = cells[0]
        elif len(cells) == 5 and cells[0] in MONTHS and year:
            month = f"{year}-{MONTHS.index(cells[0]) + 1:02d}"
            try:
                table[month] = dict(zip(MEASURES, (number(cell) for cell in cells[1:])))
            except ValueError as error:
                raise PageChanged(f"Unexpected row in CBSL's inflation table: {cells}.") from error
    if not table:
        raise PageChanged(
            "Could not find any monthly figures in CBSL's inflation table. "
            "The page has probably changed and this tool needs updating."
        )
    return dict(sorted(table.items()))


def months_between(first: str, last: str) -> list[str]:
    """Every month from `first` to `last` inclusive, e.g. "2025-11", "2025-12", "2026-01"."""
    year, month = int(first[:4]), int(first[5:])
    months = []
    while f"{year}-{month:02d}" <= last:
        months.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def get_inflation_history(start_month: str | None = None, end_month: str | None = None) -> dict:
    page = fetch(TABLE_URL)
    table = parse_inflation_table(page.text)
    first_available, last_available = min(table), max(table)
    coverage = f"CBSL's table runs from {first_available} to {last_available}"
    skipped = [m for m in months_between(first_available, last_available) if m not in table]
    if skipped:
        coverage += f", but skips {skipped[0]} to {skipped[-1]}"

    start = parse_month(start_month) if start_month else first_available
    end = parse_month(end_month) if end_month else last_available
    if start > end:
        raise InvalidRequest(f"start_month ({start}) must be on or before end_month ({end}).")

    months = {month: figures for month, figures in table.items() if start <= month <= end}
    if not months:
        raise NoData(f"CBSL's inflation table has no figures between {start} and {end}. {coverage}.")

    headline = {m: f["ccpi_headline"] for m, f in months.items() if f["ccpi_headline"] is not None}
    result = {
        "unit": "percent change on the same month a year earlier",
        "measures": MEASURES,
        "requested_start": start,
        "requested_end": end,
        "months": months,
    }
    if headline:
        picks = {
            "latest": max(headline),
            "highest": max(headline, key=headline.get),
            "lowest": min(headline, key=headline.get),
        }
        result["ccpi_headline_summary"] = {
            label: {"month": month, "value": headline[month]} for label, month in picks.items()
        }

    covered = months_between(max(start, first_available), min(end, last_available))
    missing = [month for month in covered if month not in months]
    if missing:
        result["note"] = (
            f"CBSL's table has no figures for {len(missing)} months between "
            f"{missing[0]} and {missing[-1]}. Do not fill the gap by guessing."
        )
    result["coverage"] = (
        f"{coverage}. A '-' on CBSL's page (not yet published) is shown as null. "
        "Different years may use index baskets with different base years."
    )

    return {**result, **page.stamp(PUBLIC_URL), "disclaimer": DISCLAIMER}
