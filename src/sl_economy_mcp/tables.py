"""Reading HTML tables as plain rows of text."""

import re
from html import unescape


def rows_of_cells(html: str) -> list[list[str]]:
    """Every table row in `html` as a list of its cells' text."""
    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
        rows.append([" ".join(unescape(re.sub(r"<[^>]+>", " ", cell)).split()) for cell in cells])
    return rows


def number(text: str) -> float | None:
    """A cell as a number. CBSL leaves a cell blank or writes "-" when it has no figure."""
    if text in ("", "-"):
        return None
    return float(text.replace(",", ""))
