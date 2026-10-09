# sl-economy-mcp

An unofficial [MCP](https://modelcontextprotocol.io) server that lets Claude and other AI assistants fetch live, official Sri Lankan economic data from the [Central Bank of Sri Lanka](https://www.cbsl.gov.lk) (CBSL).

Several MCP servers already cover Colombo Stock Exchange share prices. This one covers the macro side: the policy interest rate, inflation and the rupee.

Every call fetches fresh data from cbsl.gov.lk, and every answer says where the data came from, when it was fetched and which date it refers to.

## Tools

| Tool | What it returns |
| --- | --- |
| `get_snapshot` | Overnight policy rate, CCPI inflation (year-on-year), and USD/LKR bank buying and selling rates |
| `get_exchange_rate` | The rupee rate for one currency on one date (latest if no date is given). About 55 currencies, plus gold |
| `get_exchange_rate_history` | Daily or month-end rupee rates over a date range, with percentage change, high, low and average |

All exchange rates are rupees per 1 unit of the foreign currency, so a rising number means a weaker rupee.

## Example questions

- "What is Sri Lanka's policy rate and inflation right now?"
- "What was the USD/LKR rate on 12 May 2022?"
- "How much did the rupee move against the dollar during 2022?"
- "Compare the rupee against the pound and the Indian rupee over the last six months."
- "What is the price of gold in rupees today?"

## Install

You need Python 3.10 or newer.

```bash
git clone https://github.com/YOUR-USERNAME/sl-economy-mcp.git
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

Save the file and open Claude again. The three tools should appear in the tools menu.

## How it works

```
src/sl_economy_mcp/
  server.py          the list of tools the assistant can call
  snapshot.py        reads CBSL's headline "rate window"
  exchange_rates.py  submits CBSL's exchange rate search forms and reads the results
  fetch.py           downloads pages: 5-minute cache, honest User-Agent, clear errors
  errors.py          the problems we expect, each with a plain-English message
```

Design choices:

- **Live, not stored.** Nothing is saved between runs. A 5-minute cache stops repeated questions from hitting CBSL again and again.
- **One outside dependency**, the official MCP Python SDK. Downloading and reading pages uses Python's standard library.
- **Fail loudly.** If a CBSL page changes shape, the tool says so. It never guesses a number.
- **Tested offline.** The tests run against saved copies of real CBSL pages, so they need no internet and always give the same result.

## Data sources and limits

| Data | CBSL page |
| --- | --- |
| Policy rate, inflation, USD buy/sell | [Rate window](https://www.cbsl.gov.lk/cbsl_custom/param/ratewindow.php) |
| Daily indicative rates | [Daily Indicative Exchange Rates](https://www.cbsl.gov.lk/en/rates-and-indicators/exchange-rates/daily-indicative-exchange-rates) |
| Bank buying and selling rates | [Daily Buy and Sell Exchange Rates](https://www.cbsl.gov.lk/en/rates-and-indicators/exchange-rates/daily-buy-and-sell-exchange-rates) |

- The rate window shows no date, so `get_snapshot` reports the time it was fetched instead.
- Exchange rates are published on business days. Ask for a weekend or holiday and you get the most recent earlier rate, clearly labelled.
- CBSL's online exchange rate lookup starts on 7 May 2010. It is complete from 2014 onwards and has many missing days before that.
- Bank buying and selling rates exist for nine currencies: AUD, CAD, CHF, CNY, EUR, GBP, JPY, SGD and USD.

## Running the tests

```bash
.venv/bin/pip install ".[dev]"
.venv/bin/python -m pytest
```

## Disclaimer

This is an unofficial project. It is not affiliated with, endorsed by or supported by the Central Bank of Sri Lanka. The data is read from CBSL's public website and may contain errors or be out of date. Nothing here is investment advice. For anything that matters, check the figure on cbsl.gov.lk.

## Credit

All data belongs to the [Central Bank of Sri Lanka](https://www.cbsl.gov.lk), which publishes it freely.

## Licence

[MIT](LICENSE)
