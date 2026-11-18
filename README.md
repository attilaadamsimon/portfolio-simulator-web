# Portfolio Monte Carlo

A minimal, single-page Python web app. It opens with an empty chart and no automatic simulation: upload a CSV, download the template, choose up to 10 stocks (one share each initially), or explicitly run the synthetic example. The stock picker includes a company/ticker search and editable quantities in Holdings. Upload current stock/ETF holdings, select EUR or USD, and simulate all holdings, stocks only or ETFs only. Interactive percentile fan chart, final-value distribution and PNG download. Neutral charcoal dark mode and light mode follow your system initially and remember your choice. The median outcome includes its total return percentage in muted parentheses, calculated as (median / starting value - 1) × 100, not annualized. Interface separators use vertical bars. Click any of the 25 displayed sample paths (or percentile lines) to highlight it, and click again to clear; a Clear highlight button is also provided. No accounts or broker credentials.

## Run in VS Code

Open `Portfolio Simulator.code-workspace`. Python 3.11+ is required.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python app.py
```

Open http://127.0.0.1:8050. Or select the virtual environment in VS Code and press F5. On Windows, use `.venv\Scripts\activate` and select `.venv\Scripts\python.exe` as the interpreter.

## CSV compatibility

Upload a **full Scalable Capital transaction export** or **current holdings**, with a ticker or ISIN and a quantity. Name and Stock/ETF type are optional. Import recognizes English/German headers, UTF-8/Windows-1252, comma/semicolon/tab delimiters, fractional shares and either decimal convention. Unknown layouts use the same-page column mapper. Select the correct decimal convention and review the imported quantities.

Examples are in `examples/`. These are illustrative holdings layouts, **not verified native broker exports**. Scalable Capital, Trade Republic and Robinhood are supported through this normalized holdings/mapping workflow. Scalable Capital transaction exports with the recognized date/status/reference/assetType/type/ISIN/shares schema are automatically reconstructed: executed buys, savings plans and distribution reinvestments add shares; sells subtract shares. Pending/cancelled trades, cash movements and distributions without reinvestment do not change shares. Duplicate references are deduplicated; conflicting references, unknown share-changing events and sales exceeding earlier purchases stop the import. Decimal conventions are detected automatically. Use the full history and review the derived positions: missing initial holdings, transfers, corporate actions or later trades cannot be inferred. Other transaction layouts are still rejected; use a current holdings snapshot for those. No claim is made that every broker offers a holdings CSV or that every native layout works unchanged.

ISINs are resolved automatically from exact-ISIN Yahoo searches, with a source-verified Alphabet Class A fallback for a known search-index gap. The app prefers US primary listings for US securities and, otherwise, listings in the selected reporting currency when available. Candidate tickers must have usable stock/ETF price data. Successful choices are cached on the server for 30 days and remembered in this browser; manual changes made with the ticker field or “Find listing” take precedence on later uploads. If no usable match exists, the app leaves it unresolved rather than inventing a ticker. A single security may have multiple tickers and trading currencies. Ticker examples: `AAPL`, `MSFT`, `VWCE.DE`. A ticker must match the shares/listing actually held. The app verifies instrument type and native currency with the provider. Unsupported positions are excluded during CSV import when identified; anything discovered later stops the run with an explicit error. Zero positions are excluded; short positions are rejected. Duplicate identifiers are summed. Limit: 50 distinct holdings, 500 snapshot rows or 20,000 Scalable transaction rows, 2 MB.

## Closing prices and reliability

- Yahoo Finance completed daily closes; adjusted close history for simulation. Today's incomplete session is excluded; a 30-minute buffer follows the reported regular close. No live quote is presented as an end-of-day close.
- Two Yahoo endpoints are tried with timeouts and a brief retry delay. They are **the same provider**, not independent feeds. We tested Stooq during development, but its download returned a browser-verification page, so it is not advertised as a reliable fallback.
- Public price history is saved to `.cache/market.sqlite3`, shared across requests, with a 15-minute freshness period. Each run checks data; “Refresh prices & run” bypasses the cache. An active, unchanged portfolio refreshes every 15 minutes. Cache failures/old prices require explicit opt-in and show visible dates/warnings. No fabricated prices or silent missing-holding omissions.
- Prices over four calendar days old are marked older (a deliberately conservative rule; long exchange holidays can trigger it). Latest available is provider-relative, not a completeness guarantee across all exchanges. Outages, unsupported symbols and data revisions remain possible. First-time holdings cannot be simulated offline.
- Frankfurter daily currency history, with Yahoo daily FX as fallback. FX is aligned to each price date without look-ahead, with a maximum seven-day gap. Both valuation and historical returns convert to the selected reporting currency. Minor units such as GBp are normalized. FX dates/sources appear under holdings.

## Simulation assumptions

Up to five years of adjusted daily history is converted into complete calendar-month returns. Require at least 252 daily observations per holding and 24 common monthly returns. Holdings with fewer than 252 daily closes (approximately one trading year), or fewer than 24 complete monthly returns needed by the model, are automatically excluded from the simulation. The app names each exclusion and its reason, and removes its value from the starting portfolio; the uploaded position stays visible for review and is reconsidered on future runs. If nothing eligible remains, it explains why instead of generating an empty simulation. Price-fetch failures still raise an error rather than silently excluding holdings. Incomplete months and months with missing end-of-month prices are excluded. Historical FX movements are included before estimating covariance.

Correlated geometric Brownian motion uses the sample mean of monthly **log** returns and sample covariance. Negative numerical eigenvalues are clipped to zero. Log-return drift is used directly (no double subtraction of half-variance). Each asset evolves separately; portfolio values are summed every month. Buy and hold, dividends reinvested within each asset, no rebalancing, cash flows, options, taxes or fees. The starting value uses actual unadjusted closing prices × shares, not adjusted historical prices. Starting quotes can have different dates across exchanges; this is disclosed.

The fan chart shows pointwise 5th/25th/50th/75th/95th percentiles, not a simultaneous confidence interval. Loss probability means ending below the starting nominal value, not experiencing an interim loss. Returns/correlations are assumed stationary and normal in log space; the model does not represent all tail risks or regime changes. Historical mean return estimates can produce unrealistic long-horizon outcomes. No investment recommendation is made.

## Test

```sh
python -m pytest -q
```

Deterministic tests cover CSV layouts/decimal conventions, transaction rejection, asset exclusions, completed sessions, FX alignment, stale caches, portfolio aggregation, correlations and API validation. The synthetic example is deterministic and works without internet. All financial calculations run in Python; JavaScript only handles the one-page interface and Plotly charts. New runs use bounded background jobs with progress and cancellation. The original synchronous endpoint and GBM function remain available for compatibility. See [FEATURE_GUIDE.md](FEATURE_GUIDE.md) for the four models, live sliders, stress scenarios, presets, backtest methodology, and testing instructions.

## Publish later

For a public CV showcase, use **synthetic example mode**:

```sh
DEMO_ONLY=1 gunicorn --bind 0.0.0.0:8050 --workers 1 --threads 8 --timeout 180 app:app
```

Use **one web worker process** with multiple request threads: job state is kept in process memory. Multiple Gunicorn workers would not share the job registry. The two background calculation threads are separate from the request threads. A restart clears jobs; the UI reports this and lets you rerun. A shared job service would be needed before deploying multiple web processes. A Dockerfile defaults to this mode too. Set the host's `PORT` and use HTTPS. This project has not been deployed. Free access to Yahoo data does not grant unrestricted public redistribution rights: verify the provider's terms before enabling market mode on a public deployment. Keep `DEMO_ONLY=1` for the shareable example without those external-data dependencies. For a deployment authorized to use the data, `DEMO_ONLY=0` enables uploads and market requests; add host-level rate limiting for public traffic.

Uploads/holdings remain in browser session and request memory; only public market data is written to disk. Closing the tab clears the portfolio. On a hosted instance the server processes uploads, and tickers/search terms (not share quantities) are sent to the data providers. Set `MARKET_CACHE` to a writable persistent file if needed. Only the theme and identifier-to-ticker preferences are stored in browser local storage, not share quantities or transaction histories. Clearing browser site data resets these preferences.

Sources: [Yahoo chart interface via yfinance documentation](https://ranaroussi.github.io/yfinance/), [Yahoo data-use note](https://github.com/ranaroussi/yfinance), [Frankfurter API](https://frankfurter.dev/), [Flask deployment](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/), [Robinhood transaction reports](https://robinhood.com/us/en/support/articles/finding-your-account-documents/), [Scalable transaction export](https://es.scalable.capital/en/product-news/transactions-export).
