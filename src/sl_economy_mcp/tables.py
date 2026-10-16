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


def heading_cells(html: str) -> list[str]:
    """The text of every heading cell (<th>) in `html`, in order."""
    cells = re.findall(r"<th[^>]*>(.*?)</th>", html, re.S)
    return [" ".join(unescape(re.sub(r"<[^>]+>", " ", cell)).split()) for cell in cells]


NUMBER = re.compile(r"-?\d+(?:\.\d+)?")  # e.g. 11.04, -0.30 or 2,100.00 once the commas are gone


def number(text: str) -> float | None:
    """A cell as a number. CBSL leaves a cell blank or writes "-" when it has no figure.

    Anything else that is not plainly a number raises ValueError. Python's own
    float() would also accept words such as "nan" and "inf".
    """
    if text in ("", "-"):
        return None
    plain = text.replace(",", "")
    if not NUMBER.fullmatch(plain):
        raise ValueError(f"not a number: {text!r}")
    return float(plain)
