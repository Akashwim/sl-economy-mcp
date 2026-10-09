# sl-economy-mcp

[![tests](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/tests.yml)
[![live check](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/live-check.yml/badge.svg)](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/live-check.yml)

An unofficial [MCP](https://modelcontextprotocol.io) server that lets Claude and other AI assistants fetch live, official Sri Lankan economic data from the [Central Bank of Sri Lanka](https://www.cbsl.gov.lk) (CBSL).

Several MCP servers already cover Colombo Stock Exchange share prices. This one covers the macro side: interest rates, inflation and the rupee.

Every call fetches fresh data from CBSL, and every answer says where the data came from, when it was fetched and which date it refers to.

## Tools

| Tool | What it returns |
| --- | --- |
| `get_snapshot` | Today's policy rate, inflation, real policy rate (policy rate minus inflation), and USD/LKR bank buying and selling rates, each with the date it refers to |
| `get_exchange_rate` | The rupee rate for one currency on one date (latest if no date is given). About 55 currencies, plus gold |
| `get_exchange_rate_history` | Daily or month-end rupee rates over a date range, with percentage change, high, low and average |
| `get_inflation_history` | Monthly headline and core inflation for the Colombo (CCPI) and national (NCPI) price indices |
| `get_interest_rates` | One of four groups: the Central Bank's policy rates with the date of each change, bank lending and deposit rates (weekly prime lending rate from 2007), Treasury bill yields, or Treasury bond yields. Lending rates and bill yields include the real rate after inflation |

All exchange rates are rupees per 1 unit of the foreign currency, so a rising number means a weaker rupee.

There is also one ready-made prompt, **Sri Lanka macro briefing**. Choose it from your assistant's prompt menu and it calls all the tools and writes a one-page briefing with sources.

## Example questions

- "What is Sri Lanka's policy rate and inflation right now? Is the real rate positive?"
- "How much did the rupee move against the dollar during 2022?"
- "When did the Central Bank last change interest rates, and by how much?"
- "How did the prime lending rate change between 2021 and today? What is it in real terms?"
- "Show monthly inflation since January 2024. When did it turn negative?"
- "What is the one-year Treasury bill yield, and how does it compare with a year ago?"
- "What is the price of gold in rupees today?"

## Install

You need Python 3.10 or newer.

```bash
git clone https://github.com/Akashwim/sl-economy-mcp.git
cd sl-economy-mcp
python3 -m venv .venv
.venv/bin/pip install .
```

Then tell the Claude desktop app about it. **Settings → Developer → Edit Config** shows you where the settings file is. Quit Claude completely before you change it, because the running app can overwrite the file. Then add:

```json
{
  "mcpServers": {
    "sl-economy": {
      "command": "/full/path/to/sl-economy-mcp/.venv/bin/sl-economy-mcp"
    }
  }
}
```

Save the file and open Claude again. The five tools should appear in the tools menu.

## How it works

```
src/sl_economy_mcp/
  server.py          what the assistant can see: five tools and one prompt
  snapshot.py        reads CBSL's headline "rate window"
  exchange_rates.py  submits CBSL's exchange rate search forms and reads the results
  inflation.py       reads the monthly table on CBSL's inflation page
  interest_rates.py  picks lending rates and Treasury yields out of the Data Library
  data_library.py    searches CBSL's Data Library, which needs a cookie and hidden form fields
  fetch.py           downloads pages: 5-minute cache, honest User-Agent, clear errors
  series.py          first, last, high, low, average and month-ends of a series
  tables.py          turns an HTML table into rows of text
  dates.py           Sri Lanka's clock and reading typed dates
  errors.py          the problems we expect, each with a plain-English message
```

Design choices:

- **Live, not stored.** Nothing is saved between runs. A short cache stops repeated questions from hitting CBSL again and again: 5 minutes for most pages, an hour for the slow Data Library tables, which change weekly at most.
- **One outside dependency**, the official MCP Python SDK. Downloading and reading pages uses Python's standard library.
- **Fail loudly.** If a CBSL page changes shape, the tool says so. It never guesses a number.
- **Honest about gaps.** Where CBSL's data is missing or running behind, the answer says so.
- **Read only what is needed.** CBSL's tables contain the odd typo. A bad cell in a column the tool does not use is ignored; a bad cell in one it does use is an error.
- **Tested offline.** The tests run against saved copies of real CBSL pages, so they need no internet and always give the same result.

## Data sources and limits

| Data | CBSL source |
| --- | --- |
| Policy rate, inflation, USD buy/sell | [Rate window](https://www.cbsl.gov.lk/cbsl_custom/param/ratewindow.php) |
| Daily indicative rates | [Daily Indicative Exchange Rates](https://www.cbsl.gov.lk/en/rates-and-indicators/exchange-rates/daily-indicative-exchange-rates) |
| Bank buying and selling rates | [Daily Buy and Sell Exchange Rates](https://www.cbsl.gov.lk/en/rates-and-indicators/exchange-rates/daily-buy-and-sell-exchange-rates) |
| Monthly inflation | [Measures of Consumer Price Inflation](https://www.cbsl.gov.lk/en/measures-of-consumer-price-inflation) |
| Lending and deposit rates | [Data Library: Commercial Banks Lending and Deposit Rates](https://www.cbsl.lk/eResearch/MoneyMarketRatesDefault.aspx?ReportId=6277) |
| Treasury bill and bond yields | [Data Library: Rates on Government Securities](https://www.cbsl.lk/eResearch/MoneyMarketRatesDefault.aspx?ReportId=6169) |
| Policy rates | [Data Library: Daily Operations](https://www.cbsl.lk/eResearch/MoneyMarketRatesDefault.aspx?ReportId=1059) |

- The rate window shows no dates, so `get_snapshot` matches each figure against CBSL's dated tables. If they disagree it says "not confirmed" and does not guess.
- Exchange rates are published on business days. Ask for a weekend or holiday and you get the most recent earlier rate, clearly labelled.
- CBSL's online exchange rate lookup starts on 7 May 2010. It is complete from 2014 onwards and has many missing days before that.
- Bank buying and selling rates exist for nine currencies: AUD, CAD, CHF, CNY, EUR, GBP, JPY, SGD and USD.
- CBSL's inflation table covers about six years and currently skips 2023. The tool points out the gap.
- Treasury and policy rate searches take about 20 seconds, and the Data Library's Treasury figures sometimes run months behind. The tool reports the date of the latest figure it found.
- Policy rate history is limited to 12 months per request because CBSL's source is slow.
- Treasury bond yields exist only for weeks in which CBSL auctioned that maturity, so they are sparse.
- Real rates are given two ways: the rate minus inflation, and the Fisher equation, which is more exact when inflation is high. Both use past inflation (the latest year-on-year figure), so they are a rough guide, not a forecast.

## Running the tests

```bash
.venv/bin/pip install ".[dev]"
.venv/bin/python -m pytest
```

## Live check

The tests above use saved pages, so they cannot notice CBSL changing its website. A second check does: every weekday GitHub calls each tool against the real CBSL site and checks the answers are plausible (for example, a buying rate below the selling rate, and a prime lending rate no more than three weeks old). If a page has changed shape, the check fails and the maintainer is emailed. If CBSL is simply unreachable, it only warns.

```bash
.venv/bin/python checks/live_check.py
```

## Disclaimer

This is an unofficial project. It is not affiliated with, endorsed by or supported by the Central Bank of Sri Lanka. The data is read from CBSL's public websites and may contain errors or be out of date. Nothing here is investment advice. For anything that matters, check the figure with CBSL.

## Credit

All data belongs to the [Central Bank of Sri Lanka](https://www.cbsl.gov.lk), which publishes it freely.

## Licence

[MIT](LICENSE)
