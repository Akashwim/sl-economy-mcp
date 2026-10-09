"""Interest rates over time, from CBSL's Data Library.

Two groups are available:

- "lending": what commercial banks charge borrowers and pay depositors.
- "treasury_bills": the yield on short-term government borrowing.

Each group is one table in the Data Library. A `Report` below says which
table it is and which of its columns we pick out.
"""

from dataclasses import dataclass
from datetime import timedelta

from . import DISCLAIMER, data_library
from .dates import parse_day, today_in_sri_lanka
from .errors import InvalidRequest, NoData
from .series import Series, describe, month_ends


@dataclass(frozen=True)
class Report:
    report_id: int  # the Data Library's number for this table
    title: str  # heading on CBSL's page, to check we got the right table
    value_columns: int  # figures per row, to notice if CBSL adds or removes one
    description: str
    columns: dict[str, tuple[int, str]]  # our name -> (position in the row, meaning)


REPORTS = {
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
    ),
}

DEFAULT_RANGE_DAYS = 365
MONTHLY_ABOVE = 120  # longer series are listed as month-ends instead
BEHIND_AFTER_DAYS = 21  # weekly data this old means CBSL's library is running behind


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

    page = data_library.search(report.report_id, start, end)
    rows = data_library.parse_grid(page.text, report.title, report.value_columns)

    rates, latest_dates = {}, []
    for column, (position, meaning) in report.columns.items():
        values = [(day, figures[position]) for day, figures in rows if figures[position] is not None]
        if values:
            rates[column] = present(values, meaning)
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

    source = data_library.report_url(report.report_id)
    return {**result, **page.stamp(source), "disclaimer": DISCLAIMER}
