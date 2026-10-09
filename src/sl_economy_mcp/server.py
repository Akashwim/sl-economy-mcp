"""The MCP server: what an AI assistant can see and call.

Each tool is a thin wrapper. The real work lives in the other modules so it
can be tested without starting a server. The text under each function is what
the assistant reads when deciding which tool to use.
"""

import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import exchange_rates, inflation, interest_rates, snapshot
from .errors import ExpectedProblem

mcp = MCPServer("sl-economy-mcp")

# Every tool only reads public web pages. Saying so lets an app run them
# without treating them as risky.
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


def explain_problems(tool):
    """Let the assistant read our error messages.

    The SDK hides the details of a crash from the assistant, which is right
    for bugs. Problems we expected already have a plain-English message, so
    we hand those over as a ToolError, the kind the SDK does pass on.
    """

    @functools.wraps(tool)
    def wrapper(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except ExpectedProblem as problem:
            raise ToolError(str(problem)) from problem

    return wrapper


@mcp.tool(annotations=READ_ONLY)
@explain_problems
def get_snapshot() -> dict:
    """Latest headline Sri Lankan economic indicators from the Central Bank of Sri Lanka.

    Returns the overnight policy rate, CCPI inflation (year-on-year), the real
    policy rate (policy rate minus inflation) and the USD/LKR telegraphic
    transfer buying and selling rates, fetched live from cbsl.gov.lk, with the
    date each figure refers to, the source URL and the fetch time.
    """
    return snapshot.get_snapshot()


@mcp.tool(annotations=READ_ONLY)
@explain_problems
def get_exchange_rate(currency: str = "USD", date: str | None = None) -> dict:
    """Sri Lankan rupee (LKR) exchange rate for one currency on one date, from the Central Bank of Sri Lanka.

    Returns CBSL's indicative rate in rupees per 1 unit of the currency and,
    for major currencies, the commercial banks' average buying and selling
    rates. Fetched live from cbsl.gov.lk.

    Args:
        currency: Three-letter code such as USD, GBP, EUR, INR, JPY, AUD or CNY.
            About 55 are available, plus XAU for gold per troy ounce.
        date: Year-month-day, e.g. 2026-10-09. Leave out for the latest rate.
            Data is complete from 2014 and patchy from 2010-05-07 to 2013.
            If nothing was published that day (weekend or holiday), the most
            recent earlier rate is returned.
    """
    return exchange_rates.get_exchange_rate(currency, date)


@mcp.tool(annotations=READ_ONLY)
@explain_problems
def get_exchange_rate_history(
    currency: str, start_date: str, end_date: str | None = None, interval: str = "auto"
) -> dict:
    """Sri Lankan rupee (LKR) exchange rates for one currency over a date range, from the Central Bank of Sri Lanka.

    Returns CBSL's daily indicative rates in rupees per 1 unit of the currency,
    with a summary: first and last rate, percentage change, high, low and
    average. Fetched live from cbsl.gov.lk.

    Args:
        currency: Three-letter code such as USD, GBP, EUR, INR, JPY, AUD or CNY.
        start_date: Year-month-day, e.g. 2026-01-01. Data is complete from
            2014 and patchy from 2010-05-07 to 2013.
        end_date: Year-month-day. Leave out for today.
        interval: "daily" lists every business day (up to about three years),
            "monthly" lists the last business day of each month, and "auto"
            picks daily for short ranges and monthly for long ones. The summary
            always uses every daily rate.
    """
    return exchange_rates.get_exchange_rate_history(currency, start_date, end_date, interval)


@mcp.tool(annotations=READ_ONLY)
@explain_problems
def get_inflation_history(start_month: str | None = None, end_month: str | None = None) -> dict:
    """Monthly Sri Lankan inflation, from the Central Bank of Sri Lanka.

    Returns year-on-year headline and core inflation for the Colombo Consumer
    Price Index (CCPI, the headline measure) and the National Consumer Price
    Index (NCPI), month by month, with the latest, highest and lowest headline
    figures. Fetched live from cbsl.gov.lk.

    Args:
        start_month: Year-month, e.g. 2024-01. Leave out for the earliest
            month CBSL lists (about six years back).
        end_month: Year-month. Leave out for the latest month published.
    """
    return inflation.get_inflation_history(start_month, end_month)


@mcp.tool(annotations=READ_ONLY)
@explain_problems
def get_interest_rates(
    series: str = "lending", start_date: str | None = None, end_date: str | None = None
) -> dict:
    """Sri Lankan interest rates over time, from the Central Bank of Sri Lanka's Data Library.

    Returns each rate's values with a summary: first, last, change in
    percentage points, high, low and average. Long ranges are listed as
    month-end values. Lending rates and Treasury bill yields also come with
    the latest real rate (after inflation).

    Args:
        series: One of:
            "policy" - the Central Bank's own standing deposit and lending
            facility rates, with the date and size of each change. Use this
            to find when policy last moved. At most 12 months per call, and
            it takes about 20 seconds.
            "lending" - commercial bank rates: the weekly prime lending rate
            (AWPR) that company loans are priced from, plus monthly average
            lending and deposit rates, from 2007.
            "treasury_bills" - weekly 91, 182 and 364-day Treasury bill
            yields, the rupee risk-free benchmark.
            "treasury_bonds" - yields on 2 to 30-year Treasury bonds, only in
            weeks when each was auctioned.
            Treasury data takes about 20 seconds and may run months behind.
        start_date: Year-month-day. Leave out for one year before end_date.
        end_date: Year-month-day. Leave out for today.
    """
    return interest_rates.get_interest_rates(series, start_date, end_date)


@mcp.prompt(title="Sri Lanka macro briefing")
def macro_briefing() -> str:
    """A one-page, sourced briefing on Sri Lanka's interest rates, inflation and the rupee."""
    return (
        "Write a one-page briefing on Sri Lanka's economy as it stands now, "
        "using only figures from the sl-economy tools.\n\n"
        "Call these first:\n"
        "- get_snapshot\n"
        "- get_inflation_history for the last 24 months\n"
        "- get_exchange_rate_history for USD over the last 12 months\n"
        "- get_interest_rates with series 'policy' for the last 12 months\n"
        "- get_interest_rates with series 'lending' for the last 12 months\n"
        "- get_interest_rates with series 'treasury_bills' for the last 12 months\n\n"
        "Then cover, in this order:\n"
        "1. Monetary policy: the policy rate, when it last changed, and the real policy rate.\n"
        "2. Inflation: the latest headline and core figures and the trend.\n"
        "3. The rupee: where it is against the dollar and how far it has moved in 12 months.\n"
        "4. Borrowing costs: the prime lending rate and Treasury bill yields, and their direction.\n"
        "5. What to watch: two or three things these figures suggest keeping an eye on.\n\n"
        "Give the date each figure refers to. If a tool reports missing or "
        "out-of-date data, say so plainly instead of estimating. End with the "
        "source links. Do not give investment advice."
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
