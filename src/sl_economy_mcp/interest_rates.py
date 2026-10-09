"""Interest rates over time, from CBSL's Data Library.

Four groups are available:

- "policy": the rates CBSL itself sets, and the dates it changed them.
- "lending": what commercial banks charge borrowers and pay depositors.
- "treasury_bills": the yield on short-term government borrowing.
- "treasury_bonds": the yield on longer-term government borrowing.

Each group is one table in the Data Library. A `Report` below says which
table it is and which of its columns we pick out.
"""

from dataclasses import dataclass
from datetime import timedelta

from . import DISCLAIMER, data_library, inflation
from .dates import parse_day, today_in_sri_lanka
from .errors import ExpectedProblem, InvalidRequest, NoData
from .series import Series, describe, fisher_real_rate, month_ends


@dataclass(frozen=True)
class Report:
    report_id: int  # the Data Library's number for this table
    title: str  # heading on CBSL's page, to check we got the right table
    value_columns: int  # figures per row, to notice if CBSL adds or removes one
    description: str
    columns: dict[str, tuple[int, str]]  # our name -> (position in the row, meaning)
    max_days: int | None = None  # longest range allowed, for reports that are slow
    list_changes: bool = False  # rates that are set, not traded: list each change
    real_rates: bool = False  # also give the latest rate after inflation


BOND_YEARS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 30]  # in CBSL's column order

REPORTS = {
    "policy": Report(
        report_id=1059,
        title="Daily Operations",
        value_columns=13,
        description=(
            "The interest rates the Central Bank sets for its overnight "
            "dealings with commercial banks. A change in these is a change in "
            "monetary policy. Since 27 November 2024 CBSL announces a single "
            "Overnight Policy Rate, and these two rates move with it at a "
            "fixed margin either side."
        ),
        columns={
            "standing_deposit_facility_rate": (
                8,
                "SDFR. What CBSL pays banks that park spare cash with it overnight. "
                "The floor for overnight interest rates.",
            ),
            "standing_lending_facility_rate": (
                10,
                "SLFR. What CBSL charges banks that borrow from it overnight. "
                "The ceiling for overnight interest rates.",
            ),
        },
        max_days=366,
        list_changes=True,
    ),
    "lending": Report(
        report_id=6277,
        title="Commercial Bank Lending and Deposit Rates",
        value_columns=8,
        description=(
            "What Sri Lanka's commercial banks charge borrowers and pay "
            "depositors, averaged across banks and weighted by amount."
        ),
        columns={
            "prime_lending_rate": (
                1,
                "AWPR, weekly. The average rate banks charged their most "
                "creditworthy corporate customers on short-term loans that "
                "week. Company loans are often priced as AWPR plus a margin.",
            ),
            "average_lending_rate": (
                0,
                "AWLR, monthly. The average rate on all outstanding rupee bank loans.",
            ),
            "average_deposit_rate": (
                4,
                "AWDR, monthly. The average rate banks pay on all interest-bearing rupee deposits.",
            ),
            "average_fixed_deposit_rate": (
                6,
                "AWFDR, monthly. The average rate banks pay on rupee fixed deposits.",
            ),
        },
        real_rates=True,
    ),
    "treasury_bills": Report(
        report_id=6169,
        title="Rates on Government Securities",
        value_columns=16,
        description=(
            "Weekly yields on Sri Lankan government Treasury bills. They are "
            "the benchmark for other rupee interest rates and are often used "
            "as the rupee risk-free rate."
        ),
        columns={
            "91_day": (0, "Yield on 91-day (3-month) Treasury bills."),
            "182_day": (1, "Yield on 182-day (6-month) Treasury bills."),
            "364_day": (2, "Yield on 364-day (1-year) Treasury bills."),
        },
        real_rates=True,
    ),
    "treasury_bonds": Report(
        report_id=6169,
        title="Rates on Government Securities",
        value_columns=16,
        description=(
            "Yields on longer-term Sri Lankan government Treasury bonds. A "
            "maturity only has a figure in weeks when CBSL auctioned it, so "
            "expect few values and uneven dates."
        ),
        columns={
            f"{years}_year": (3 + position, f"Yield on {years}-year Treasury bonds.")
            for position, years in enumerate(BOND_YEARS)
        },
    ),
}

DEFAULT_RANGE_DAYS = 365
MONTHLY_ABOVE = 120  # longer series are listed as month-ends instead
BEHIND_AFTER_DAYS = 21  # weekly data this old means CBSL's library is running behind


def changes(series: Series) -> list[dict]:
    """Each date the value differed from the one before it."""
    return [
        {"date": day.isoformat(), "from": before, "to": after, "change": round(after - before, 2)}
        for (_, before), (day, after) in zip(series, series[1:])
        if after != before
    ]


def real_rate(point: tuple, table: inflation.Table) -> dict | None:
    """A rate minus headline inflation for the same month (or up to two months earlier)."""
    day, rate = point
    month = f"{day.year}-{day.month:02d}"
    earliest = inflation.months_back(month, 2)
    usable = [m for m in table if earliest <= m <= month and table[m]["ccpi_headline"] is not None]
    if not usable:
        return None
    price_rise = table[max(usable)]["ccpi_headline"]
    return {
        "value": round(rate - price_rise, 2),
        "fisher_value": fisher_real_rate(rate, price_rise),
        "rate": rate,
        "rate_date": day.isoformat(),
        "inflation": price_rise,
        "inflation_month": max(usable),
    }


def present(series: Series, meaning: str) -> dict:
    """One column of a report: what it means, a summary, and the values."""
    basics = describe(series)
    result = {
        "meaning": meaning,
        "summary": {
            "first": basics["first"],
            "last": basics["last"],
            "change_percentage_points": round(series[-1][1] - series[0][1], 2),
            "high": basics["high"],
            "low": basics["low"],
            "average": basics["average"],
            "observations": basics["observations"],
        },
    }
    listed = series
    if len(series) > MONTHLY_ABOVE:
        listed = month_ends(series)
        result["values_note"] = (
            "Showing the last value of each month. The summary uses every value."
        )
    result["values"] = {day.isoformat(): value for day, value in listed}
    return result


def get_interest_rates(
    series: str = "lending", start_date: str | None = None, end_date: str | None = None
) -> dict:
    name = series.strip().lower()
    if name not in REPORTS:
        raise InvalidRequest(
            f"'{series}' is not an available series. Choose from: {', '.join(REPORTS)}. "
            "For today's policy rate use get_snapshot."
        )
    report = REPORTS[name]
    end = parse_day(end_date) if end_date else today_in_sri_lanka()
    start = parse_day(start_date) if start_date else end - timedelta(days=DEFAULT_RANGE_DAYS)
    if start > end:
        raise InvalidRequest(f"start_date ({start}) must be on or before end_date ({end}).")
    if report.max_days and (end - start).days > report.max_days:
        raise InvalidRequest(
            f"CBSL's source for {name} rates is slow, so ask for 12 months or less "
            f"at a time. You asked for {start} to {end}."
        )

    page = data_library.search(report.report_id, start, end)
    wanted = {position for position, _ in report.columns.values()}
    rows = data_library.parse_grid(page.text, report.title, report.value_columns, wanted)

    rates, latest_dates = {}, []
    for column, (position, meaning) in report.columns.items():
        values = [(day, figures[position]) for day, figures in rows if figures[position] is not None]
        if values:
            rates[column] = present(values, meaning)
            if report.list_changes:
                rates[column]["changes"] = changes(values)
            latest_dates.append(values[-1][0])
    if not rates:
        raise NoData(f"CBSL's Data Library has no {name} rates between {start} and {end}.")

    latest = max(latest_dates)
    result = {
        "series": name,
        "description": report.description,
        "unit": "percent per year",
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "latest_data_date": latest.isoformat(),
        "rates": rates,
    }
    if (min(end, today_in_sri_lanka()) - latest).days > BEHIND_AFTER_DAYS:
        result["note"] = (
            f"CBSL's Data Library has nothing after {latest} for this series, "
            "so it appears to be running behind. Treat the latest figure as "
            f"the position on {latest}, not today."
        )

    if report.real_rates:
        try:
            table = inflation.load_table()
            for column, (position, _) in report.columns.items():
                values = [(d, f[position]) for d, f in rows if f[position] is not None]
                after_inflation = real_rate(values[-1], table) if values else None
                if after_inflation:
                    rates[column]["real_rate_latest"] = after_inflation
            result["real_rate_note"] = (
                "real_rate_latest is worked out by this tool from the latest rate "
                "and headline CCPI inflation for that month. 'value' is the rate "
                "minus inflation. 'fisher_value' uses the Fisher equation, "
                "(1 + rate) / (1 + inflation) - 1, which is more exact when "
                "inflation is high. Both use past inflation, so they are a rough "
                "guide to the return or cost after price rises, not a forecast."
            )
        except ExpectedProblem as problem:
            result["real_rate_note"] = f"Real rates left out: {problem}"

    source = data_library.report_url(report.report_id)
    return {**result, **page.stamp(source), "disclaimer": DISCLAIMER}
