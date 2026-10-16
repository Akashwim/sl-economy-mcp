"""The MCP server: what an AI assistant can see and call.

Each tool is a thin wrapper. The real work lives in the other modules so it
can be tested without starting a server. The text under each function, and
the description of each argument, is what the assistant reads when deciding
which tool to use and how to call it.
"""

import functools
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, exchange_rates, inflation, interest_rates, morning_rates, snapshot
from .errors import ExpectedProblem

INSTRUCTIONS = (
    "Live Sri Lankan economic figures from official sources: the Central Bank of "
    "Sri Lanka and the Ministry of Finance's Public Debt Management Office. Every "
    "answer says where each figure comes from and the date it is for; pass both "
    "on. Never estimate, fill a gap from memory, or present a figure as today's "
    "when its date is earlier. If a tool says a figure is missing, say so plainly. "
    "For the morning rates sheet use get_morning_rates and show the sheet exactly "
    "as it is returned."
)

mcp = MCPServer(
    "sl-economy-mcp",
    title="Sri Lanka Economy",
    instructions=INSTRUCTIONS,
    version=__version__,
    website_url="https://github.com/Akashwim/sl-economy-mcp",
)

# Every tool only reads public web pages. Saying so lets an app run them
# without treating them as risky.
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

DAY = "Year-month-day, for example 2026-10-09."


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


@mcp.tool(title="Morning Sheet", annotations=READ_ONLY)
@explain_problems
def get_morning_rates() -> list:
    """The Morning Sheet: Sri Lankan inflation, the US dollar, the prime lending rate and Treasury bill auction rates, as one finished table.

    Returns the latest figures from the Central Bank of Sri Lanka and the
    Ministry of Finance's Public Debt Management Office: NCPI headline and
    core inflation, the USD/LKR indicative rate, the banks' USD buying and
    selling rates, the weekly prime lending rate (AWPR), and the 91, 182 and
    364-day Treasury bill rates from the latest auction, checked against the
    Ministry's daily report. Every figure has the source's own label, the
    date it is for and a link to its source. Takes up to about 45 seconds.

    The answer has two parts. The first is the finished sheet: show it
    exactly as it is, notes and all, and do not rebuild, reorder, shorten or
    add to it, or fill a gap from another tool. The second part holds the same
    figures as data; use it only to answer questions about a figure.
    """
    sheet = morning_rates.get_morning_rates()
    return [sheet["table"], {key: value for key, value in sheet.items() if key != "table"}]


@mcp.tool(title="Snapshot of headline indicators", annotations=READ_ONLY)
@explain_problems
def get_snapshot() -> dict:
    """Latest headline Sri Lankan economic indicators from the Central Bank of Sri Lanka.

    Returns the overnight policy rate, CCPI inflation (year-on-year), the real
    policy rate (policy rate minus inflation) and the USD/LKR telegraphic
    transfer buying and selling rates, fetched live from cbsl.gov.lk, with the
    date each figure refers to, the source URL and the fetch time.
    """
    return snapshot.get_snapshot()


@mcp.tool(title="Exchange rate on one date", annotations=READ_ONLY)
@explain_problems
def get_exchange_rate(
    currency: Annotated[
        str,
        Field(
            description="Three-letter code such as USD, GBP, EUR, INR, JPY, AUD or CNY. "
            "About 55 are available, plus XAU for gold per troy ounce."
        ),
    ] = "USD",
    date: Annotated[
        str | None,
        Field(
            description=f"{DAY} Leave out for the latest rate. If nothing was published "
            "that day (weekend or holiday), the most recent earlier rate is returned. "
            "Complete from 2014; patchy from 2010-05-07 to 2013."
        ),
    ] = None,
) -> dict:
    """Sri Lankan rupee (LKR) exchange rate for one currency on one date, from the Central Bank of Sri Lanka.

    Returns CBSL's indicative rate in rupees per 1 unit of the currency and,
    for major currencies, the commercial banks' average buying and selling
    rates. Fetched live from cbsl.gov.lk.
    """
    return exchange_rates.get_exchange_rate(currency, date)


@mcp.tool(title="Exchange rate history", annotations=READ_ONLY)
@explain_problems
def get_exchange_rate_history(
    currency: Annotated[str, Field(description="Three-letter code such as USD, GBP, EUR, INR, JPY, AUD or CNY.")],
    start_date: Annotated[
        str, Field(description=f"{DAY} Complete from 2014; patchy from 2010-05-07 to 2013.")
    ],
    end_date: Annotated[str | None, Field(description=f"{DAY} Leave out for today.")] = None,
    interval: Annotated[
        Literal["auto", "daily", "monthly"],
        Field(
            description='"daily" lists every business day (up to about three years), '
            '"monthly" lists the last business day of each month, and "auto" picks daily '
            "for short ranges and monthly for long ones. The summary always uses every daily rate."
        ),
    ] = "auto",
) -> dict:
    """Sri Lankan rupee (LKR) exchange rates for one currency over a date range, from the Central Bank of Sri Lanka.

    Returns CBSL's daily indicative rates in rupees per 1 unit of the currency,
    with a summary: first and last rate, percentage change, high, low and
    average. Fetched live from cbsl.gov.lk.
    """
    return exchange_rates.get_exchange_rate_history(currency, start_date, end_date, interval)


@mcp.tool(title="Inflation history", annotations=READ_ONLY)
@explain_problems
def get_inflation_history(
    start_month: Annotated[
        str | None,
        Field(
            description="Year-month, for example 2024-01. Leave out for the earliest month "
            "CBSL lists (about six years back)."
        ),
    ] = None,
    end_month: Annotated[
        str | None, Field(description="Year-month. Leave out for the latest month published.")
    ] = None,
) -> dict:
    """Monthly Sri Lankan inflation, from the Central Bank of Sri Lanka.

    Returns year-on-year headline and core inflation for the Colombo Consumer
    Price Index (CCPI, the headline measure) and the National Consumer Price
    Index (NCPI), month by month, with the latest, highest and lowest headline
    figures. Fetched live from cbsl.gov.lk.
    """
    return inflation.get_inflation_history(start_month, end_month)


@mcp.tool(title="Interest rates over time", annotations=READ_ONLY)
@explain_problems
def get_interest_rates(
    series: Annotated[
        Literal["policy", "lending"],
        Field(
            description='"policy": the Central Bank\'s standing deposit and lending facility '
            "rates, with the date and size of each change; use it to find when policy last "
            "moved. Last 6 months by default, at most 12 months per call, and slow: about 30 "
            'seconds for 6 months and up to a minute for 12. "lending": commercial bank '
            "rates: the weekly prime lending rate (AWPR) that company loans are priced from, "
            "plus monthly average lending and deposit rates, from 2007."
        ),
    ] = "lending",
    start_date: Annotated[
        str | None,
        Field(description=f"{DAY} Leave out for the default range (6 months for policy, 12 for lending)."),
    ] = None,
    end_date: Annotated[str | None, Field(description=f"{DAY} Leave out for today.")] = None,
) -> dict:
    """Sri Lankan interest rates over time, from the Central Bank of Sri Lanka's Data Library.

    Returns each rate's values with a summary: first, last, change in
    percentage points, high, low and average. Long ranges are listed as
    month-end values. Lending rates also come with the latest real rate
    (after inflation). For the latest Treasury bill auction rates use
    get_morning_rates.
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
        "- get_morning_rates, for the latest Treasury bill auction rates\n\n"
        "Then cover, in this order:\n"
        "1. Monetary policy: the policy rate, when it last changed, and the real policy rate.\n"
        "2. Inflation: the latest headline and core figures and the trend.\n"
        "3. The rupee: where it is against the dollar and how far it has moved in 12 months.\n"
        "4. Borrowing costs: the prime lending rate and its direction, and the latest Treasury bill auction rates.\n"
        "5. What to watch: two or three things these figures suggest keeping an eye on.\n\n"
        "Give the date each figure refers to. If a tool reports missing or "
        "out-of-date data, say so plainly instead of estimating. End with the "
        "source links. Do not give investment advice."
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
