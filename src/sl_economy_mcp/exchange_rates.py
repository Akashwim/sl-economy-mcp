"""Daily rupee exchange rates from CBSL's online lookup forms.

CBSL has two search forms, both updated every business day:

- Indicative rates: one reference rate per day, for about 55 currencies.
- TT rates: the average buying and selling rates quoted by commercial banks
  for telegraphic transfers, for nine major currencies.

We submit a form the same way a browser would and read the table that comes
back. Every rate is rupees (LKR) per 1 unit of the foreign currency, so a
bigger number means a weaker rupee.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape

from . import DISCLAIMER
from .dates import parse_day, today_in_sri_lanka
from .errors import InvalidRequest, NoData, PageChanged
from .fetch import Page, fetch
from .series import Series, describe, month_ends
from .tables import number

CBSL = "https://www.cbsl.gov.lk"


@dataclass(frozen=True)
class LookupForm:
    form_url: str  # the form itself; lists the currencies on offer
    results_url: str  # where the form is submitted
    public_url: str  # the page a person would open; quoted as the source
    heading: str  # text in the results table's heading, to check the layout


INDICATIVE = LookupForm(
    form_url=f"{CBSL}/cbsl_custom/exrates/exrates.php",
    results_url=f"{CBSL}/cbsl_custom/exrates/exrates_results.php",
    public_url=f"{CBSL}/en/rates-and-indicators/exchange-rates/daily-indicative-exchange-rates",
    heading="-> LKR",
)
TT = LookupForm(
    form_url=f"{CBSL}/cbsl_custom/exratestt/exratestt.php",
    results_url=f"{CBSL}/cbsl_custom/exratestt/exrates_resultstt.php",
    public_url=f"{CBSL}/en/rates-and-indicators/exchange-rates/daily-buy-and-sell-exchange-rates",
    heading="Buy Rate",
)

EARLIEST = date(2010, 5, 7)  # first day in CBSL's online lookup
COMPLETE_FROM = date(2014, 1, 1)  # before this, many business days are missing
COVERAGE = (
    f"CBSL's online lookup starts on {EARLIEST} and has many missing business "
    f"days before {COMPLETE_FROM.year}."
)
LOOK_BACK_DAYS = 14  # how far back to search for the last business day
AUTO_DAILY_LIMIT = 120  # longer histories are listed as month-ends instead
MAX_DAILY_ROWS = 800  # about three years of business days

Row = tuple[date, float, float]  # a date and the two numbers beside it


# --- Reading CBSL's pages -------------------------------------------------


def parse_currencies(form_html: str) -> dict[str, str]:
    """The currencies a form offers, e.g. {"USD": "US Dollar", ...}."""
    found = re.findall(r'name="chk_cur\[\]"\s+value="([A-Z]{3})~([^"]+)"', form_html)
    if not found:
        raise PageChanged(
            "Could not find the list of currencies on CBSL's exchange rate form. "
            "The page layout has probably changed and this tool needs updating."
        )
    return {code: " ".join(name.split()) for code, name in found}


def parse_rate_table(results_html: str, heading: str) -> list[Row]:
    """The rows of a results table, oldest first. Empty if CBSL found nothing."""
    html = unescape(results_html)
    if heading not in html:
        raise PageChanged(
            f"CBSL's exchange rate results no longer have a '{heading}' column. "
            "The page layout has probably changed and this tool needs updating."
        )
    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [cell.strip() for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]
        if not cells:
            continue  # the heading row uses <th>, not <td>
        try:
            day, first, second = cells
            rows.append((date.fromisoformat(day), _number(first), _number(second)))
        except ValueError as error:
            raise PageChanged(
                f"Unexpected row in CBSL's exchange rate results: {cells}. "
                "The page layout has probably changed and this tool needs updating."
            ) from error
    return sorted(rows)


def _number(text: str) -> float:
    value = number(text)
    if value is None:
        raise ValueError("no figure")
    return value


def currencies(form: LookupForm) -> dict[str, str]:
    return parse_currencies(fetch(form.form_url).text)


def lookup(form: LookupForm, code: str, start: date, end: date) -> tuple[list[Row], Page]:
    """Ask one CBSL form for one currency's daily rates between two dates."""
    page = fetch(
        form.results_url,
        form={
            "lookupPage": "lookup_daily_exchange_rates.php",
            "startRange": "2006-11-11",
            "rangeType": "dates",
            "txtStart": start.isoformat(),
            "txtEnd": end.isoformat(),
            "chk_cur[]": f"{code}~{currencies(form)[code]}",
            "submit_button": "Submit",
        },
    )
    rows = parse_rate_table(page.text, form.heading)
    # Don't rely on CBSL honouring the dates we asked for.
    return [row for row in rows if start <= row[0] <= end], page


# --- Summarising and checking ---------------------------------------------


def summarise(series: Series, code: str) -> dict:
    """Start, end, percentage change, high, low and average of a series of rates."""
    basics = describe(series)
    change = (series[-1][1] / series[0][1] - 1) * 100
    if change > 0:
        direction = f"{code} became more expensive in rupees"
    elif change < 0:
        direction = f"{code} became cheaper in rupees"
    else:
        direction = "unchanged"
    return {
        "first": _rate(basics["first"]),
        "last": _rate(basics["last"]),
        "change_percent": round(change, 2),
        "direction": direction,
        "high": _rate(basics["high"]),
        "low": _rate(basics["low"]),
        "average": basics["average"],
        "business_days": basics["observations"],
    }


def _rate(point: dict) -> dict:
    return {"date": point["date"], "rate": point["value"]}


def check_currency(currency: str) -> tuple[str, str]:
    """Return (code, name) for a currency CBSL publishes, or say what is available."""
    code = currency.strip().upper()
    names = currencies(INDICATIVE)
    if code not in names:
        raise InvalidRequest(
            f"'{currency}' is not a currency code CBSL publishes a rupee rate for. "
            f"Available codes: {', '.join(sorted(names))}."
        )
    return code, names[code]


# --- The two tools --------------------------------------------------------


def get_exchange_rate(currency: str = "USD", on_date: str | None = None) -> dict:
    code, name = check_currency(currency)
    wanted = parse_day(on_date) if on_date else today_in_sri_lanka()
    window_start = wanted - timedelta(days=LOOK_BACK_DAYS)

    rows, page = lookup(INDICATIVE, code, window_start, wanted)
    if not rows:
        raise NoData(f"CBSL has no {code} rate between {window_start} and {wanted}. {COVERAGE}")
    day, rate, _ = rows[-1]

    result = {
        "currency": code,
        "currency_name": name,
        "unit": f"LKR per 1 {code}",
        "requested_date": wanted.isoformat(),
        "data_date": day.isoformat(),
        "indicative_rate": rate,
    }
    if day != wanted:
        result["note"] = (
            f"CBSL published no rate for {wanted} (weekend, holiday or not yet "
            "released), so this is the most recent earlier business day."
        )

    tt_currencies = currencies(TT)
    if code in tt_currencies:
        tt_rows, _ = lookup(TT, code, window_start, wanted)
        for tt_day, buy, sell in tt_rows:
            if tt_day == day:
                result["bank_tt_rates"] = {
                    "buy": buy,
                    "sell": sell,
                    "explanation": (
                        "Average rates at which commercial banks buy and sell "
                        f"{code} by telegraphic transfer, quoted at 9.30 a.m."
                    ),
                    "source_url": TT.public_url,
                }
                break
        else:
            result["bank_tt_rates"] = (
                f"Not published for {day}. CBSL posts buying and selling rates "
                "separately from the indicative rate, and they can appear later in the day."
            )
    else:
        result["bank_tt_rates"] = (
            "Not published for this currency. CBSL gives buying and selling "
            f"rates only for: {', '.join(sorted(tt_currencies))}."
        )

    return {**result, **page.stamp(INDICATIVE.public_url), "disclaimer": DISCLAIMER}


def get_exchange_rate_history(
    currency: str, start_date: str, end_date: str | None = None, interval: str = "auto"
) -> dict:
    code, name = check_currency(currency)
    start = parse_day(start_date)
    end = parse_day(end_date) if end_date else today_in_sri_lanka()
    if start > end:
        raise InvalidRequest(f"start_date ({start}) must be on or before end_date ({end}).")
    if interval not in ("auto", "daily", "monthly"):
        raise InvalidRequest(f"interval must be 'auto', 'daily' or 'monthly', not '{interval}'.")

    rows, page = lookup(INDICATIVE, code, start, end)
    if not rows:
        raise NoData(f"CBSL has no {code} rates between {start} and {end}. {COVERAGE}")
    series = [(day, rate) for day, rate, _ in rows]

    if interval == "auto":
        interval = "daily" if len(series) <= AUTO_DAILY_LIMIT else "monthly"
    if interval == "daily" and len(series) > MAX_DAILY_ROWS:
        raise InvalidRequest(
            f"That range has {len(series)} daily rates, too many to return at once. "
            f"Use interval='monthly', or a range with at most {MAX_DAILY_ROWS} business days."
        )
    listed = series if interval == "daily" else month_ends(series)

    result = {
        "currency": code,
        "currency_name": name,
        "unit": f"LKR per 1 {code}",
        "rate_type": "CBSL daily indicative rate",
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "summary": summarise(series, code),
        "how_to_read": (
            f"Rates are rupees per 1 {code}. A positive change_percent means "
            f"{code} costs more rupees than before; for a currency, that is the "
            "rupee weakening against it."
        ),
        "interval": interval,
        "rates": {day.isoformat(): rate for day, rate in listed},
    }
    if interval == "monthly":
        result["interval_note"] = (
            "Showing the last business day of each month. The summary is still "
            "calculated from every daily rate in the range."
        )
    if start < COMPLETE_FROM:
        result["note"] = f"{COVERAGE} Expect gaps in the early part of this range."

    return {**result, **page.stamp(INDICATIVE.public_url), "disclaimer": DISCLAIMER}
