"""Dates: Sri Lanka's clock, and reading the dates a caller typed."""

import re
from datetime import date, datetime, timedelta, timezone

from .errors import InvalidRequest

# Sri Lanka is UTC+5:30 all year round (no daylight saving).
SRI_LANKA_TIME = timezone(timedelta(hours=5, minutes=30), "Asia/Colombo")


def today_in_sri_lanka() -> date:
    return datetime.now(SRI_LANKA_TIME).date()


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise InvalidRequest(
            f"'{text}' is not a valid date. Use year-month-day, for example 2026-10-09."
        ) from None


def parse_month(text: str) -> str:
    """A month as "2026-09". A full date such as 2026-09-30 is accepted too."""
    match = re.fullmatch(r"(\d{4})-(\d{2})(-\d{2})?", text.strip())
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise InvalidRequest(f"'{text}' is not a valid month. Use year-month, for example 2026-09.")
    return f"{match.group(1)}-{match.group(2)}"
