"""The headline numbers from CBSL's "rate window" (the box on their homepage).

The page is a small HTML table. Numbers and their % signs are split across
several tags, e.g. `8.00&nbsp;</span>%`, so searching the raw HTML is fragile.
Instead we strip the tags to get plain text like

    ... 8.00 % (CCPI) 8.75 % TT Buy 326.4384 TT Sell 335.4464

and find each number by the label next to it.
"""

import re
from datetime import timedelta
from html.parser import HTMLParser

from . import DISCLAIMER, exchange_rates, inflation
from .dates import today_in_sri_lanka
from .errors import ExpectedProblem, PageChanged
from .fetch import fetch
from .series import fisher_real_rate

RATE_WINDOW_URL = "https://www.cbsl.gov.lk/cbsl_custom/param/ratewindow.php"

NUMBER = r"(-?\d+(?:\.\d+)?)"  # inflation can be negative (deflation)

PATTERNS = {
    "ccpi_inflation_percent": NUMBER + r"\s*%\s*\(CCPI\)",
    "overnight_policy_rate_percent": r"\(CCPI\)\s*" + NUMBER + r"\s*%",
    "usd_lkr_tt_buy": r"TT Buy\s*" + NUMBER,
    "usd_lkr_tt_sell": r"TT Sell\s*" + NUMBER,
}


class _TextOnly(HTMLParser):
    """Collects the visible text of a page, ignoring tags, CSS and scripts."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skipping += 1

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self._skipping:
            self._skipping -= 1

    def handle_data(self, data):
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


def parse_rate_window(html: str) -> dict[str, float]:
    """Pull the four headline numbers out of the rate window page."""
    text = html_to_text(html)

    # The policy rate has no label beside the number, only a column heading,
    # so make sure that heading is still there before trusting the position.
    if "Overnight Policy Rate" not in text:
        raise PageChanged(
            "CBSL's rate window no longer has an 'Overnight Policy Rate' heading. "
            "The page layout has probably changed and this tool needs updating."
        )

    values = {}
    for name, pattern in PATTERNS.items():
        match = re.search(pattern, text)
        if not match:
            raise PageChanged(
                f"Could not find '{name}' on CBSL's rate window. "
                "The page layout has probably changed and this tool needs updating."
            )
        values[name] = float(match.group(1))

    if values["usd_lkr_tt_buy"] > values["usd_lkr_tt_sell"]:
        raise PageChanged(
            "CBSL's rate window shows a USD buying rate above the selling rate, "
            "which should never happen. The page layout has probably changed."
        )
    return values


def inflation_month(rate: float) -> str:
    """Which month the headline inflation figure is for, from CBSL's monthly table."""
    try:
        table = inflation.load_table()
    except ExpectedProblem:
        return "not confirmed (CBSL's inflation table could not be read)"
    published = [month for month, figures in table.items() if figures["ccpi_headline"] is not None]
    latest = max(published)
    if table[latest]["ccpi_headline"] == rate:
        return latest
    return f"not confirmed (CBSL's table shows {table[latest]['ccpi_headline']} for {latest})"


def usd_rate_date(buy: float, sell: float) -> str:
    """Which day the USD buying and selling rates are for, from CBSL's dated lookup."""
    today = today_in_sri_lanka()
    try:
        rows, _ = exchange_rates.lookup(exchange_rates.TT, "USD", today - timedelta(days=14), today)
    except ExpectedProblem:
        return "not confirmed (CBSL's dated rates could not be read)"
    matches = [day for day, dated_buy, dated_sell in rows if (dated_buy, dated_sell) == (buy, sell)]
    if matches:
        return max(matches).isoformat()
    return "not confirmed (no matching day in CBSL's dated rates)"


def get_snapshot() -> dict:
    page = fetch(RATE_WINDOW_URL)
    values = parse_rate_window(page.text)
    policy_rate, price_rise = values["overnight_policy_rate_percent"], values["ccpi_inflation_percent"]
    return {
        **values,
        "real_policy_rate_percent": round(policy_rate - price_rise, 2),
        "real_policy_rate_fisher_percent": fisher_real_rate(policy_rate, price_rise),
        "notes": {
            "ccpi_inflation_percent": (
                "Year-on-year change in the Colombo Consumer Price Index, latest month published."
            ),
            "overnight_policy_rate_percent": "CBSL's main policy interest rate.",
            "real_policy_rate_percent": (
                "Policy rate minus inflation, worked out by this tool. A rough "
                "guide to how tight policy is once price rises are allowed for."
            ),
            "real_policy_rate_fisher_percent": (
                "The same idea by the Fisher equation, (1 + rate) / (1 + inflation) - 1, "
                "which is more exact when inflation is high."
            ),
            "usd_lkr_tt_buy / usd_lkr_tt_sell": (
                "Rupees per US dollar: average telegraphic transfer rates quoted "
                "by commercial banks in Colombo at 9.30 a.m."
            ),
        },
        "data_dates": {
            "ccpi_inflation_percent": inflation_month(values["ccpi_inflation_percent"]),
            "overnight_policy_rate_percent": (
                "The rate in force when fetched. For when it last changed, use "
                "get_interest_rates with series 'policy'."
            ),
            "usd_lkr_tt_buy / usd_lkr_tt_sell": usd_rate_date(
                values["usd_lkr_tt_buy"], values["usd_lkr_tt_sell"]
            ),
            "how_dated": (
                "CBSL's headline page shows no dates, so each figure is matched "
                "against CBSL's dated tables."
            ),
        },
        **page.stamp(),
        "disclaimer": DISCLAIMER,
    }
