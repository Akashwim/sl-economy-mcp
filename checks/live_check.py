"""Call every tool against the real CBSL website and check the answers look sane.

The normal tests use saved pages, so they cannot notice CBSL changing its
website. This script can. GitHub runs it every weekday (see
.github/workflows/live-check.yml); you can also run it yourself:

    python checks/live_check.py

It fails if a page has changed shape or a number is implausible. If one or
two tools cannot reach CBSL it only warns, because CBSL's slow pages time
out now and then. If more than that are unreachable it fails, because a
check that could not check anything must not look like a pass. (CBSL's site
sometimes refuses GitHub's servers with "HTTP 403" while working normally
for everyone else.)
"""

import sys
from datetime import date, timedelta

from sl_economy_mcp import exchange_rates, inflation, interest_rates, snapshot
from sl_economy_mcp.dates import today_in_sri_lanka
from sl_economy_mcp.errors import ExpectedProblem, SourceUnavailable

TODAY = today_in_sri_lanka()


def days_ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def age_in_days(day: str) -> int:
    return (TODAY - date.fromisoformat(day)).days


def check_snapshot():
    result = snapshot.get_snapshot()
    assert 0 < result["overnight_policy_rate_percent"] < 40, result
    assert -10 < result["ccpi_inflation_percent"] < 100, result
    assert 100 < result["usd_lkr_tt_buy"] < result["usd_lkr_tt_sell"] < 1000, result
    dates = result["data_dates"]
    assert not dates["ccpi_inflation_percent"].startswith("not confirmed"), dates
    return f"policy rate {result['overnight_policy_rate_percent']}%"


def check_exchange_rate():
    result = exchange_rates.get_exchange_rate("USD")
    assert 100 < result["indicative_rate"] < 1000, result
    assert age_in_days(result["data_date"]) <= 10, result["data_date"]
    bank = result["bank_tt_rates"]
    if isinstance(bank, dict):  # otherwise a note that today's are not out yet
        assert bank["buy"] < bank["sell"], result
    return f"USD/LKR {result['indicative_rate']} on {result['data_date']}"


def check_exchange_rate_history():
    result = exchange_rates.get_exchange_rate_history("GBP", days_ago(30))
    assert result["summary"]["business_days"] >= 10, result["summary"]
    return f"{result['summary']['business_days']} GBP rates in 30 days"


def check_inflation():
    result = inflation.get_inflation_history()
    latest = result["ccpi_headline_summary"]["latest"]
    assert -10 < latest["value"] < 100, latest
    assert age_in_days(latest["month"] + "-01") <= 125, latest
    return f"inflation {latest['value']}% for {latest['month']}"


def check_lending_rates():
    result = interest_rates.get_interest_rates("lending", days_ago(90))
    prime = result["rates"]["prime_lending_rate"]["summary"]["last"]
    assert 0 < prime["value"] < 50, prime
    assert age_in_days(prime["date"]) <= 21, prime
    return f"prime lending rate {prime['value']}% on {prime['date']}"


def check_treasury_bills():
    # CBSL's Data Library often runs months behind here, so only the shape is checked.
    result = interest_rates.get_interest_rates("treasury_bills", days_ago(365))
    one_year = result["rates"]["364_day"]["summary"]["last"]
    assert 0 < one_year["value"] < 50, one_year
    return f"364-day yield {one_year['value']}% on {one_year['date']}"


def check_policy_rates():
    result = interest_rates.get_interest_rates("policy", days_ago(30))
    floor = result["rates"]["standing_deposit_facility_rate"]["summary"]["last"]["value"]
    ceiling = result["rates"]["standing_lending_facility_rate"]["summary"]["last"]["value"]
    assert 0 < floor < ceiling < 40, (floor, ceiling)
    return f"policy corridor {floor}% to {ceiling}%"


CHECKS = [
    check_snapshot,
    check_exchange_rate,
    check_exchange_rate_history,
    check_inflation,
    check_lending_rates,
    check_treasury_bills,
    check_policy_rates,
]


MAX_UNREACHABLE = 2


def main() -> int:
    failures = unreachable = 0
    for check in CHECKS:
        name = check.__name__.removeprefix("check_")
        try:
            print(f"ok       {name}: {check()}")
        except SourceUnavailable as problem:
            unreachable += 1
            # "::warning::" makes GitHub show this on the run's summary page.
            print(f"::warning::{name}: CBSL could not be reached. {problem}")
        except (ExpectedProblem, AssertionError, KeyError) as problem:
            failures += 1
            print(f"::error::{name}: {type(problem).__name__}: {problem}")
    passed = len(CHECKS) - failures - unreachable
    print(f"\n{passed} passed, {failures} failed, {unreachable} could not reach CBSL.")
    if unreachable > MAX_UNREACHABLE:
        print(
            f"::error::{unreachable} of {len(CHECKS)} checks could not reach CBSL from "
            "this computer, so this run proves nothing either way. If the tools work "
            "from a normal connection, CBSL is refusing this server, not the project."
        )
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
