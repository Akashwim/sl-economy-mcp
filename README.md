# sl-economy-mcp

[![tests](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/tests.yml)
[![live check](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/live-check.yml/badge.svg)](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/live-check.yml)

An unofficial [MCP](https://modelcontextprotocol.io) server that lets Claude and other AI assistants fetch live, official Sri Lankan economic data from the [Central Bank of Sri Lanka](https://www.cbsl.gov.lk) (CBSL) and the Ministry of Finance's [Public Debt Management Office](https://www.treasury.gov.lk/web/public-debt-management-office) (PDMO).

Several MCP servers already cover Colombo Stock Exchange share prices. This one covers the macro side: interest rates, inflation, the rupee and Treasury bills.

Every call fetches fresh data from the source, and every answer says where each figure came from, when it was fetched and which date it is for. A figure that cannot be read reliably is left out with the reason, never estimated.

## The Morning Sheet

`get_morning_rates` gathers the figures a finance team collects by hand each morning into one finished table:

| Section | What it shows | Source |
| --- | --- | --- |
| Inflation | NCPI headline and core inflation, year on year, each for the month it measures | CBSL, Measures of Consumer Price Inflation (compiled by the Department of Census and Statistics) |
| US dollar | CBSL's indicative USD/LKR spot rate, and the banks' average buying and selling rates at 9.30 a.m. | CBSL, Daily Indicative Exchange Rates and Daily Buy and Sell Exchange Rates |
| Lending rate | The weekly Average Weighted Prime Lending Rate (AWPR) | CBSL Data Library |
| Treasury bills | The 91, 182 and 364-day weighted average yield rates at the latest auction, dated by the auction | PDMO auction results, checked against the Ministry of Finance's Daily Summary Report |
| Treasury bonds | Not shown yet: to be developed with a primary dealer | |
| FD ceiling rate | Not shown yet: there is no official figure to check a calculation against | |

How the sheet keeps its figures trustworthy:

- **The source's own words.** Every label is the source's own, checked against the page each time. If a source renames or moves a column, that section is left out with the reason instead of being misread.
- **A date on every figure,** saying what the date means: the month measured, the day the rate is for, the week ending, or the auction date. Daily rates that are not today's are flagged.
- **Nothing worked out.** Nothing is averaged, converted or estimated. A Treasury bill rate appears only when two official documents agree: the auction result and the Ministry's daily report.
- **Each section stands alone.** A source that is down, or slower than 45 seconds, blanks only its own row.

The answer comes in two parts: the finished sheet, which the assistant shows as it is, and the same figures as data for follow-up questions.

## Other tools

| Tool | What it returns |
| --- | --- |
| `get_snapshot` | Today's policy rate, inflation, real policy rate (policy rate minus inflation), and USD/LKR bank buying and selling rates, each with the date it refers to |
| `get_exchange_rate` | The rupee rate for one currency on one date (latest if no date is given). About 55 currencies, plus gold |
| `get_exchange_rate_history` | Daily or month-end rupee rates over a date range, with percentage change, high, low and average |
| `get_inflation_history` | Monthly headline and core inflation for the Colombo (CCPI) and national (NCPI) price indices |
| `get_interest_rates` | Either the Central Bank's policy rates, with the date of each change, or bank lending and deposit rates (weekly prime lending rate from 2007), with the latest real rate after inflation |

All exchange rates are rupees per 1 unit of the foreign currency, so a rising number means a weaker rupee.

There is also one ready-made prompt, **Sri Lanka macro briefing**. Choose it from your assistant's prompt menu and it calls the tools and writes a one-page briefing with sources.

## Example questions

- "Give me the morning rates sheet."
- "What were the Treasury bill rates at the latest auction?"
- "What is Sri Lanka's policy rate and inflation right now? Is the real rate positive?"
- "How much did the rupee move against the dollar during 2022?"
- "When did the Central Bank last change interest rates, and by how much?"
- "How did the prime lending rate change between 2021 and today? What is it in real terms?"
- "Show monthly inflation since January 2024. When did it turn negative?"
- "What is the price of gold in rupees today?"

## Install

**Version note:** the Morning Sheet and the Ministry of Finance data are in the source code here and will be on PyPI from version 0.2.0. Version 0.1.0 on PyPI has the CBSL tools only. To use the Morning Sheet now, install from the source code (the last option below).

In each case, quit Claude completely before changing its settings file, because the running app can overwrite it. **Settings → Developer → Edit Config** shows you where the file is.

### If you have uv

With [uv](https://docs.astral.sh/uv/) installed there is nothing to install by hand. Add this to the settings file:

```json
{
  "mcpServers": {
    "sl-economy": {
      "command": "uvx",
      "args": ["sl-economy-mcp"]
    }
  }
}
```

### With plain Python

You need Python 3.10 or newer.

```bash
python3 -m venv ~/sl-economy-mcp-env
~/sl-economy-mcp-env/bin/pip install sl-economy-mcp
```

Then add this to the settings file, with your own username in the path:

```json
{
  "mcpServers": {
    "sl-economy": {
      "command": "/Users/YOUR-NAME/sl-economy-mcp-env/bin/sl-economy-mcp"
    }
  }
}
```

Save the file and open Claude again. The tools should appear in the tools menu.

### From the source code

To read or change the code, or to use the newest tools before they reach PyPI, clone the repository and install it from the folder:

```bash
git clone https://github.com/Akashwim/sl-economy-mcp.git
cd sl-economy-mcp
python3 -m venv .venv
.venv/bin/pip install ".[dev]"
```

Then point the settings file at `.venv/bin/sl-economy-mcp` in that folder, as in the plain Python example.

## How it works

```
src/sl_economy_mcp/
  server.py          what the assistant can see: six tools and one prompt
  morning_rates.py   the Morning Sheet: reads each source, checks its headings, builds the table
  bill_auctions.py   reads the Treasury bill auction results (PDF) and checks them against the daily report
  treasury_yields.py reads the Ministry of Finance's Daily Summary Report (Excel), used for that check
  snapshot.py        reads CBSL's headline "rate window"
  exchange_rates.py  submits CBSL's exchange rate search forms and reads the results
  inflation.py       reads the monthly table on CBSL's inflation page
  interest_rates.py  picks policy and lending rates out of CBSL's Data Library
  data_library.py    searches CBSL's Data Library, which needs a cookie and hidden form fields
  fetch.py           downloads pages: short cache, honest User-Agent, size limit, clear errors
  series.py          first, last, high, low, average and month-ends of a series
  tables.py          turns an HTML table into rows of text and reads numbers strictly
  dates.py           Sri Lanka's clock and reading typed dates
  errors.py          the problems we expect, each with a plain-English message
```

Design choices:

- **Live, not stored.** Nothing is saved between runs. A short cache stops repeated questions from hitting the sources again and again: 5 minutes for most pages, an hour for CBSL's slow Data Library tables and for the Ministry's report files, since a new or amended report is published as a new file.
- **Three outside dependencies:** the official MCP Python SDK, `xlrd` to read the Ministry's old-format Excel report, and `pypdf` to read the auction results. Downloading and reading pages uses Python's standard library.
- **Fail loudly.** If a page or file changes shape, the tool says so. It never guesses a number.
- **Two documents must agree.** Treasury bill rates are read from the auction results and shown only if the Ministry's daily report carries the same rates.
- **As the source shows it.** The Ministry's Excel report stores more decimal places than it displays, so figures read from it are rounded the way Excel displays them. This was checked by eye in Excel.
- **Honest about gaps.** Where data is missing, late or running behind, the answer says so.
- **Read only what is needed.** CBSL's tables contain the odd typo. A bad cell in a column the tool does not use is ignored; a bad cell in one it does use is an error.
- **Tested offline.** The tests run against saved copies of real CBSL and Ministry of Finance pages and files, so they need no internet and always give the same result.

## Data sources and limits

| Data | Source |
| --- | --- |
| Policy rate, inflation, USD buy/sell | CBSL: [Rate window](https://www.cbsl.gov.lk/cbsl_custom/param/ratewindow.php) |
| Daily indicative rates | CBSL: [Daily Indicative Exchange Rates](https://www.cbsl.gov.lk/en/rates-and-indicators/exchange-rates/daily-indicative-exchange-rates) |
| Bank buying and selling rates | CBSL: [Daily Buy and Sell Exchange Rates](https://www.cbsl.gov.lk/en/rates-and-indicators/exchange-rates/daily-buy-and-sell-exchange-rates) |
| Monthly inflation | CBSL: [Measures of Consumer Price Inflation](https://www.cbsl.gov.lk/en/measures-of-consumer-price-inflation) |
| Lending and deposit rates | CBSL: [Data Library, Commercial Banks Lending and Deposit Rates](https://www.cbsl.lk/eResearch/MoneyMarketRatesDefault.aspx?ReportId=6277) |
| Policy rates | CBSL: [Data Library, Daily Operations](https://www.cbsl.lk/eResearch/MoneyMarketRatesDefault.aspx?ReportId=1059) |
| Treasury bill auction results | Ministry of Finance: [Government Securities, Auction Result, Treasury Bills](https://www.treasury.gov.lk/web/result-treasury-bills) |
| Daily Summary Report, for the cross-check | Ministry of Finance: [Daily Report](https://www.treasury.gov.lk/web/report-daily-report) |

- The rate window shows no dates, so `get_snapshot` matches each figure against CBSL's dated tables. If they disagree it says "not confirmed" and does not guess.
- Exchange rates are published on business days. Ask for a weekend or holiday and you get the most recent earlier rate, clearly labelled.
- CBSL's online exchange rate lookup starts on 7 May 2010. It is complete from 2014 onwards and has many missing days before that.
- Bank buying and selling rates exist for nine currencies: AUD, CAD, CHF, CNY, EUR, GBP, JPY, SGD and USD.
- CBSL's inflation table covers about six years and currently skips 2023. The tool points out the gap.
- Treasury bill rates on the Morning Sheet are those of the latest weekly auction, dated by the auction. The Ministry's online list of results starts in December 2025.
- Treasury yields are no longer offered by `get_interest_rates`. Sri Lanka's debt data moved from CBSL to the PDMO, and CBSL's Data Library has had no Treasury figures since 9 July 2026.
- The Ministry's pages are typed by hand, so the same kind of link is written in several ways. The tool reads them carefully, and reports anything it cannot follow rather than skipping it.
- Policy rate searches are slow, and CBSL's speed varies from day to day: about 30 seconds for 6 months and up to a minute for 12. The tool looks at the last 6 months unless you ask for more, waits up to 90 seconds and tries twice before reporting a failure. Policy rate history is limited to 12 months per request.
- Real rates are given two ways: the rate minus inflation, and the Fisher equation, which is more exact when inflation is high. Both use past inflation (the latest year-on-year figure), so they are a rough guide, not a forecast.
- Neither CBSL nor the Ministry of Finance states terms for automated access that we could find. That is not the same as permission, so an organisation that relies on this tool should ask them. The tool identifies itself with an honest User-Agent, keeps pages for a few minutes, and tries again at most once.

## Running the tests

From a copy of the source code (see above):

```bash
.venv/bin/python -m pytest
```

## Live check

The tests above use saved pages, so they cannot notice a source changing its website. A second check does: every weekday GitHub calls each tool against the real CBSL and Ministry of Finance sites and checks the answers are plausible. For example, it checks that a buying rate is below the selling rate, that the latest Treasury bill auction is no more than ten days old, and that its rates agree with the Ministry's daily report. If a page has changed shape, the check fails and the maintainer is emailed. If one or two tools cannot reach their site, it only warns. If more than that are unreachable it fails, so a green tick always means the tools were really tested.

CBSL's site sometimes refuses GitHub's servers ("HTTP 403") while working normally for everyone else. A red live check with that message means GitHub was blocked that day, not that the tool is broken. The check can be run from any ordinary connection:

```bash
.venv/bin/python checks/live_check.py
```

## Disclaimer

This is an unofficial project. It is not affiliated with, endorsed by or supported by the Central Bank of Sri Lanka or the Ministry of Finance. The data is read from their public websites and may contain errors or be out of date. Nothing here is investment advice. For anything that matters, check the figure with its source.

## Credit

All data belongs to the [Central Bank of Sri Lanka](https://www.cbsl.gov.lk), the [Ministry of Finance, Planning and Economic Development](https://www.treasury.gov.lk) and its Public Debt Management Office, and, for the price indices, the [Department of Census and Statistics](https://www.statistics.gov.lk), which publish it freely.

## Licence

[MIT](LICENSE)
