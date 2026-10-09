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


def fisher_real_rate(rate: float, inflation: float) -> float:
    """A rate after inflation, by the Fisher equation: (1 + rate) / (1 + inflation) - 1.

    Subtracting inflation from the rate is a shortcut that is close when both
    are small and drifts as they grow. Both arguments and the result are in
    percent, e.g. 11.04 and 8.0 give 2.81.
    """
    return round(((1 + rate / 100) / (1 + inflation / 100) - 1) * 100, 2)


def month_ends(series: Series) -> Series:
    """Keep only the last published value of each calendar month."""
    last_in_month = {}
    for day, value in series:  # oldest first, so later days overwrite earlier ones
        last_in_month[(day.year, day.month)] = (day, value)
    return list(last_in_month.values())
