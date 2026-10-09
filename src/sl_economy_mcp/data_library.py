"""CBSL's Data Library (cbsl.lk/eResearch): tables of figures by date.

The library is an older kind of website. It only answers a search if you

1. arrive through its front door, which hands you a session cookie, and
2. send back the hidden fields from the search page along with your dates.

A browser does both without you noticing. `search()` does the same two steps.
"""

import re
from datetime import date
from html import unescape

from .errors import PageChanged
from .fetch import Page, cached, download, new_session
from .tables import number, rows_of_cells

FRONT_DOOR = "https://www.cbsl.lk/eResearch/MoneyMarketRatesDefault.aspx?ReportId="
FIELD = "ctl00$ContentPlaceHolder1$"  # prefix the library puts on its form fields
TIMEOUT_SECONDS = 45  # some reports take 15 seconds or more

Row = tuple[date, list[float | None]]  # a date and the figures beside it


def report_url(report_id: int) -> str:
    """The address a person would open to see a report."""
    return f"{FRONT_DOOR}{report_id}"


def search(report_id: int, start: date, end: date) -> Page:
    """One report's results between two dates, kept for a few minutes like any page."""
    return cached(("data-library", report_id, start, end), lambda: _search(report_id, start, end))


def _search(report_id: int, start: date, end: date) -> Page:
    session = new_session()
    search_page = download(report_url(report_id), session=session, timeout=TIMEOUT_SECONDS)
    form = hidden_fields(search_page.text)
    if "__VIEWSTATE" not in form:
        raise PageChanged(
            "CBSL's Data Library search page is missing its hidden form fields. "
            "The site has probably changed and this tool needs updating."
        )
    form[FIELD + "txtFrom"] = start.isoformat()
    form[FIELD + "txtTo"] = end.isoformat()
    form[FIELD + "btnShow"] = "Show"
    return download(search_page.url, form=form, session=session, timeout=TIMEOUT_SECONDS)


def hidden_fields(html: str) -> dict[str, str]:
    """The hidden form fields on a page, which the library expects to get back."""
    fields = {}
    for tag in re.findall(r'<input type="hidden"[^>]*>', html):
        name = re.search(r'name="([^"]*)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            fields[name.group(1)] = unescape(value.group(1)) if value else ""
    return fields


def parse_grid(
    html: str, title: str, value_columns: int, wanted: set[int] | None = None
) -> list[Row]:
    """The rows of a results table, oldest first. Empty if the library found nothing.

    `title` and `value_columns` say what we expect, so a different report or
    a table with a column added or removed is reported and not misread.
    `wanted` lists the positions to read; the rest come back as None. CBSL's
    tables have the odd typo, and one in a column we never use should not
    spoil the columns we do.
    """
    start = html.find('id="statTB"')
    if start == -1 or title not in html:
        raise PageChanged(
            f"CBSL's Data Library did not return its '{title}' table. "
            "The site has probably changed and this tool needs updating."
        )
    grid = html[start : html.find("</table>", start)]

    rows = []
    for cells in rows_of_cells(grid):
        if not cells or not re.fullmatch(r"\d{4}-\d\d-\d\d", cells[0]):
            continue  # title and heading rows
        try:
            if len(cells) != value_columns + 1:
                raise ValueError("wrong number of columns")
            figures = [
                number(cell) if wanted is None or position in wanted else None
                for position, cell in enumerate(cells[1:])
            ]
            rows.append((date.fromisoformat(cells[0]), figures))
        except ValueError as error:
            raise PageChanged(
                f"Unexpected row in CBSL's '{title}' table: {cells}. "
                "The site has probably changed and this tool needs updating."
            ) from error
    return sorted(rows, key=lambda row: row[0])
