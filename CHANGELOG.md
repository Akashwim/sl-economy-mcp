# Changelog

## Unreleased

- `get_morning_rates`: the Morning Sheet, one finished table with numbered notes. NCPI headline and core inflation, the USD/LKR indicative rate and the banks' buying and selling rates, the weekly prime lending rate (AWPR), and the 91, 182 and 364-day Treasury bill rates from the latest auction. Every label is the source's own wording and is checked against the page, every figure has its own date and says what the date means, daily rates that are not today's are flagged, and a source that cannot be read blanks only its own section.
- Treasury bill rates come from the Public Debt Management Office's auction results (PDFs) and are shown only if the Ministry of Finance's Daily Summary Report agrees. Tested on every result from December 2025 to October 2026.
- Treasury bonds and the FD ceiling rate are listed as not shown, with the reason. Bonds are to be developed with the primary dealer.
- Removed the `treasury_bills` and `treasury_bonds` series from `get_interest_rates`: Sri Lanka's debt data moved from CBSL to the Public Debt Management Office, and CBSL's Data Library has had no Treasury figures since 9 July 2026.
- New dependencies: `xlrd`, to read the Ministry's old-format Excel file, and `pypdf`, to read the auction results.
- The live check now covers the Ministry of Finance's site as well.
- The Morning Sheet reads its five sources at the same time and answers within 45 seconds even if one source hangs; that source's row says it did not answer in time. The finished sheet is returned as plain text first, then the figures as data.
- Every tool now has a title and a description for each argument; `interval` and `series` list their allowed values. The server gives its version and short instructions to the assistant.
- Hardening from a full audit: figures must be plain numbers ("nan" or "1e5" are refused); downloads over 20 MB are refused; Excel-reader warnings go to the error log, never the channel the server talks to Claude on; the Ministry's file links are recognised however they are typed, and a newest line that cannot be followed is reported, never silently skipped; a bill auction result with two rows for one bill, or headings but no readable rows, is refused; table cells are escaped.
- GitHub workflows use actions/checkout v5 and actions/setup-python v6 (Node.js 24).
- New command `sl-economy-sheet` saves the Morning Sheet as `morning-sheet-<date>.csv`, figures written exactly as displayed, with no AI involved.
- The Ministry of Finance's site gets 20 seconds per attempt instead of 60, so a hung page fails fast and the retry still fits within the sheet's 45-second limit (a page hung for 71 seconds on 16 October 2026).
- No Treasury bill rate without the double check: if the Ministry's daily report cannot be read, or is too old to confirm either of the last two auctions, no bill rate is shown (it used to show them marked "Not cross-checked today"). Until a daily report covers the newest auction, the sheet shows the auction before it, which the report confirms, dated by that auction and with a note.
- A section still downloading at 45 seconds now says "Loading, up to 30 seconds" instead of being left out, and the answer says `check_again`. The assistant is told to call once more; that second look waits for the downloads already under way (up to 30 seconds) instead of starting them again. Only one second look: if it is still loading, it says to try again later. `sl-economy-sheet` takes the second look itself.
- The bill auction result and the daily report are downloaded side by side. The Ministry's site is retried after 10 seconds instead of 5: on 19 October 2026 pages nobody had opened for a while took 6 to 30 seconds the first time and about 1 second after that, which made the first sheet of a session miss the bills.
- Every download, and every section of the sheet, is timed in the server's log (stderr).
- A figure older than its source normally lets it get is still shown but flagged "Older than usual", with its age: inflation more than 75 days after the month's end, AWPR more than 21 days after the week's end, a Treasury bill auction more than 16 days old. This catches a source that quietly stops updating.
- When a source's page has changed, the sheet also says "Please tell the person who looks after this tool for your team." The same note is numbered once in the table, however many rows use it.
- The GitHub live check runs by hand only: since 13 October 2026 CBSL refuses GitHub's servers, so the daily run failed every day.

## 0.1.0 - 2026-10-13

First public version.

- `get_snapshot`: policy rate, inflation, real policy rate and USD/LKR bank rates, each dated against CBSL's own tables.
- `get_exchange_rate` and `get_exchange_rate_history`: rupee rates for about 55 currencies and gold.
- `get_inflation_history`: monthly headline and core inflation (CCPI and NCPI).
- `get_interest_rates`: policy rates with each change, bank lending and deposit rates, Treasury bill and bond yields, with real rates.
- "Sri Lanka macro briefing" prompt.
- Weekday live check against the real CBSL site.
- Slow Data Library searches: shorter default ranges, a 90-second limit and one retry.
