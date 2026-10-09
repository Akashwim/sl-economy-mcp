"""The MCP server: the list of tools an AI assistant is allowed to call.

Each tool is a thin wrapper. The real work lives in the other modules so it
can be tested without starting a server. The text under each function is what
the assistant reads when deciding which tool to use.
"""

import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import exchange_rates, snapshot
from .errors import ExpectedProblem

mcp = MCPServer("sl-economy-mcp")


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


@mcp.tool()
@explain_problems
def get_snapshot() -> dict:
    """Latest headline Sri Lankan economic indicators from the Central Bank of Sri Lanka.

    Returns the overnight policy rate, CCPI inflation (year-on-year) and the
    USD/LKR telegraphic transfer buying and selling rates, fetched live from
    cbsl.gov.lk, with the source URL and fetch time.
    """
    return snapshot.get_snapshot()


@mcp.tool()
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


@mcp.tool()
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
