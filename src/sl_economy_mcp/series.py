"""Working with a series of numbers over time. No internet needed."""

from datetime import date

Series = list[tuple[date, float]]  # one value per date, oldest first


def describe(series: Series) -> dict:
    """First, last, highest, lowest and average of a series."""
    high = max(series, key=lambda point: point[1])
    low = min(series, key=lambda point: point[1])
    return {
        "first": _point(series[0]),
        "last": _point(series[-1]),
        "high": _point(high),
        "low": _point(low),
        "average": round(sum(value for _, value in series) / len(series), 4),
        "observations": len(series),
    }


def _point(point: tuple[date, float]) -> dict:
    return {"date": point[0].isoformat(), "value": point[1]}


def month_ends(series: Series) -> Series:
    """Keep only the last published value of each calendar month."""
    last_in_month = {}
    for day, value in series:  # oldest first, so later days overwrite earlier ones
        last_in_month[(day.year, day.month)] = (day, value)
    return list(last_in_month.values())
