# sl-economy-mcp

[![tests](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/Akashwim/sl-economy-mcp/actions/workflows/tests.yml)

An unofficial [MCP](https://modelcontextprotocol.io) server that lets Claude and other AI assistants fetch live, official Sri Lankan economic data from the [Central Bank of Sri Lanka](https://www.cbsl.gov.lk) (CBSL).

Several MCP servers already cover Colombo Stock Exchange share prices. This one covers the macro side: interest rates, inflation and the rupee.

Every call fetches fresh data from CBSL, and every answer says where the data came from, when it was fetched and which date it refers to.

## Tools

| Tool | What it returns |
| --- | --- |
| `get_snapshot` | Today's policy rate, inflation, real policy rate (policy rate minus inflation), and USD/LKR bank buying and selling rates |
| `get_exchange_rate` | The rupee rate for one currency on one date (latest if no date is given). About 55 currencies, plus gold |
| `get_exchange_rate_history` | Daily or month-end rupee rates over a date range, with percentage change, high, low and average |
| `get_inflation_history` | Monthly headline and core inflation for the Colombo (CCPI) and national (NCPI) price indices |
| `get_interest_rates` | Bank lending and deposit rates (weekly prime lending rate from 2007) or Treasury bill yields, with change, high, low and average |

All exchange rates are rupees per 1 unit of the foreign currency, so a rising number means a weaker rupee.

There is also one ready-made prompt, **Sri Lanka macro briefing**. Choose it from your assistant's prompt menu and it calls all the tools and writes a one-page briefing with sources.

## Example questions

- "What is Sri Lanka's policy rate and inflation right now? Is the real rate positive?"
- "How much did the rupee move against the dollar during 2022?"
- "How did the prime lending rate change between 2021 and today?"
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

- **Live, not stored.** Nothing is saved between runs. A 5-minute cache stops repeated questions from hitting CBSL again and again.
- **One outside dependency**, the official MCP Python SDK. Downloading and reading pages uses Python's standard library.
- **Fail loudly.** If a CBSL page changes shape, the tool says so. It never guesses a number.
- **Honest about gaps.** Where CBSL's data is missing or running behind, the answer says so.
- **Tested offline.** The tests run against saved copies of real CBSL pages, so they need no internet and always give the same result.

## Data sources and limits

| Data | CBSL source |
| --- | --- |
| Policy rate, inflation, USD buy/sell | [Rate window](https://www.cbsl.gov.lk/cbsl_custom/param/ratewindow.php) |
| Daily indicative rates | [Daily Indicative Exchange Rates](https://www.cbsl.gov.lk/en/rates-and-indicators/exchange-rates/daily-indicative-exchange-rates) |
| Bank buying and selling rates | [Daily Buy and Sell Exchange Rates](https://www.cbsl.gov.lk/en/rates-and-indicators/exchange-rates/daily-buy-and-sell-exchange-rates) |
| Monthly inflation | [Measures of Consumer Price Inflation](https://www.cbsl.gov.lk/en/measures-of-consumer-price-inflation) |
| Lending and deposit rates | [Data Library: Commercial Banks Lending and Deposit Rates](https://www.cbsl.lk/eResearch/MoneyMarketRatesDefault.aspx?ReportId=6277) |
| Treasury bill yields | [Data Library: Rates on Government Securities](https://www.cbsl.lk/eResearch/MoneyMarketRatesDefault.aspx?ReportId=6169) |

- The rate window shows no date, so `get_snapshot` reports the time it was fetched instead.
- Exchange rates are published on business days. Ask for a weekend or holiday and you get the most recent earlier rate, clearly labelled.
- CBSL's online exchange rate lookup starts on 7 May 2010. It is complete from 2014 onwards and has many missing days before that.
- Bank buying and selling rates exist for nine currencies: AUD, CAD, CHF, CNY, EUR, GBP, JPY, SGD and USD.
- CBSL's inflation table covers about six years and currently skips 2023. The tool points out the gap.
- Treasury bill searches can take 15 seconds or more, and the Data Library sometimes runs months behind. The tool reports the date of the latest figure it found.
- There is no history of the policy rate itself yet. CBSL's only online source for it is too slow to use.

## Running the tests

```bash
.venv/bin/pip install ".[dev]"
.venv/bin/python -m pytest
```

## Disclaimer

This is an unofficial project. It is not affiliated with, endorsed by or supported by the Central Bank of Sri Lanka. The data is read from CBSL's public websites and may contain errors or be out of date. Nothing here is investment advice. For anything that matters, check the figure with CBSL.

## Credit

All data belongs to the [Central Bank of Sri Lanka](https://www.cbsl.gov.lk), which publishes it freely.

## Licence

[MIT](LICENSE)
