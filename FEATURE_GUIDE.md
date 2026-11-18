# Models, scenarios and live simulation

The existing Flask, NumPy, pandas, Plotly and plain JavaScript/CSS stack is retained. No new dependencies. The original `portfolio_sim/simulation.py` GBM function is unchanged; automated tests verify that the new streaming GBM produces exactly the same outputs for the same inputs and seeds in the tested environment. All models keep per-asset, buy-and-hold aggregation and the existing stock/ETF filters, import workflow, FX conversion and history exclusions.

## Try each feature

Start as before with `.venv/bin/python app.py`, open `http://127.0.0.1:8050`, and choose **Use example** or load holdings. Extra controls are in **Models, assumptions & backtest**.

1. **Models:** select GBM, Merton, Heston or Bootstrap. Detailed parameters are handled internally, keeping the controls simple. Enable **Compare models**, then select two to four models. The primary dropdown controls the headline metrics and histogram. Comparison shows only model medians, with 5th/95th ranges in the summary table; single-model mode retains the fan chart. Hover to compare values at the same time, or click a model name to focus its line. Colors reuse the existing palette and line styles distinguish models. Click lines to highlight/clear as before.
2. **Stress:** choose a scenario. Drift, volatility and relevant model inputs update internally. **Return to normal** restores the assumptions and preset active before stress. Stress lasts for the entire chosen horizon: a ten-year crash regime is deliberately severe, not a one-time historical event followed by recovery.
3. **Backtest:** enable **Backtest the last 12 months**. The horizon shows one year; turning it off restores the prior forecast horizon. With real holdings, the chart overlays actual adjusted, reporting-currency returns for the held-out year. It reports the terminal empirical percentile and the number of months outside each model's pointwise 5th–95th band. Dots flag excursions outside the primary model's band. Example mode uses clearly labeled synthetic history. At least 36 contiguous common months are required (24 training + 12 testing); insufficient history yields an explanation and ordinary forecasting remains available.
4. **Live controls:** move a years or paths slider, or type in its neighboring number field. They stay synchronized; recalculation starts 450 ms after the latest change. A newer request cancels the old one and ignores late responses. Drift/volatility come from historical calibration unless a preset or stress scenario is selected. **Use portfolio history** restores automatic fitting. Fields outside their allowed ranges are rejected, never silently accepted.
5. **Presets:** click Conservative, Aggressive or S&P 500 historical. Years, paths and internal model parameters update; the active name is shown. Presets return to a GBM forecast, reset model-specific defaults, set Heston long-run volatility to the preset volatility, and leave any selected comparison models available. Subsequent edits show **Custom**.
6. **Background processing:** set 100,000 paths and run. The page stays interactive and shows progress. Try Heston with 200,000 paths and 30 years, then **Cancel run**, or change a slider to replace it. The server checks cancellation between monthly steps (and Heston substeps). A price request already in flight must return before cancellation completes. A failed/expired job displays an error; previous results remain visibly out of date until a successful rerun.

## Parameter conventions and assumptions

Drift means **annual mean log return**, not arithmetic return or CAGR. A 4% log drift corresponds to roughly 4.08% median one-asset annual growth in constant-volatility GBM. Custom drift shifts every asset's mean by the same amount so the starting-weight average equals the target. Custom volatility scales the historical covariance matrix so starting-weight annual volatility equals the target. Correlations and relative asset volatility are retained. Weights drift under buy and hold, so these are initial-allocation targets, not constant portfolio-level guarantees. A zero-variation history cannot be scaled to positive volatility and gives a clear error.

| Setting | Log drift / year | Volatility / year | Years | Paths |
|---|---:|---:|---:|---:|
| Conservative | 4% | 10% | 10 | 2,000 |
| Aggressive | 10% | 30% | 10 | 5,000 |
| S&P 500 historical | about 7.69% | about 18.03% | 10 | 5,000 |

The historical preset uses the mean and sample standard deviation of 26 annual log total returns, **2000–2025, USD, dividends included**, from [NYU Stern / Aswath Damodaran](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html). The source returns are stored in `portfolio_sim/scenarios.py`. This is a fixed, dated benchmark sample, not a live estimate or an FX-adjusted S&P simulation. The controls round it to two percentage decimal places and apply it to the current portfolio in the chosen reporting currency.

Stress assumptions are editable in `portfolio_sim/scenarios.py`. They are illustrative regimes, **not estimates fitted to those events**; in particular the COVID preset describes crash conditions and not the subsequent recovery.

| Scenario | Annual log drift | Annual volatility | Jumps/year | Mean log jump | Jump deviation | Heston long-run vol | Heston variance vol |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2008 financial crisis | −45% | 45% | 2 | −20% | 12% | 45% | 0.60 |
| 2020 COVID crash | −60% | 60% | 3 | −15% | 15% | 60% | 0.80 |
| Interest rate shock | −18% | 30% | 1 | −10% | 8% | 30% | 0.45 |

- **GBM:** unchanged empirical monthly log mean, sample covariance and eigenvalue clipping. No second subtraction of half-variance. Same seeded normal draws and per-asset sum as the original implementation.
- **Merton:** default jump intensity 0.5/year, log jump mean −15%, standard deviation 10%. Compound Poisson Gaussian log jumps are common across holdings (systemic shocks), independent of diffusion. The compensation `lambda * (exp(mean + std²/2) - 1)` preserves the underlying diffusion's arithmetic expectation. Thus the slider is the **diffusion log drift**, not total log drift after compensation; jump risk adds variance beyond the volatility slider. A −15% log jump is approximately a −13.9% price change. Zero jump frequency exactly matches GBM. Reference: [MathWorks Merton model](https://www.mathworks.com/help/finance/merton.html).
- **Heston:** per-asset initial annual variance from calibration; default mean reversion 2/year, long-run initial-weight portfolio volatility 20%, volatility-of-variance coefficient 0.30, return/variance correlation −0.60. The target scales each holding's historical variance proportionally. Asset return Brownian shocks retain the fitted correlation matrix; variance shocks combine these with independent normals. Full-truncation Euler uses four steps/month and monthly chart observations. Arithmetic drift is initialized from GBM (`annual log mean + half initial variance`); changing variance adjusts instantaneous log drift. This is an approximate multi-asset extension, not options calibration or an exact transition sampler. Reference for the discretization: [QuantLib Heston implementation](https://github.com/lballabio/QuantLib/blob/master/ql/processes/hestonprocess.cpp).
- **Bootstrap:** default one-month blocks; selectable circular blocks of 1–12 months. A whole row is sampled for all holdings, preserving contemporaneous relationships. Longer blocks retain within-block serial sequences. Normal historical mode uses the actual observed returns without modification; explicit drift/volatility or stress overrides shift and scale them and are disclosed. Synthetic example history stays synthetic.
- **Backtest:** fit on all available months before the final 12; never use held-out returns for calibration. No missing-month compression is allowed in a backtest. Starting values and allocation match the forward simulation and the observed replay is normalized to that same starting value; it is not historical account valuation. The current selected universe/weights imply survivorship and allocation-selection bias. Explicit scenarios and hand-selected presets can introduce hindsight. The terminal percentile is the fraction of simulated ends below the actual end, with half weight for ties; it is displayed rounded to a whole percentile. Bands are pointwise intervals, not a probability of staying within them for an entire year.

## Limits, hosting and reproducibility

- Controls: drift −80% to +40%; volatility 0% to 100%; horizon 1–30 whole years; 100–200,000 paths. Backtests use one year. Model parameter bounds appear on their number fields. The default remains 2,000 paths and 10 years.
- The new engine keeps current per-asset log growth, monthly percentiles, 25 sample paths and a terminal histogram. It does not store every full simulated path, so memory does not grow as paths × years × assets. Requests above one billion asset-substeps per model are rejected; Heston has four substeps/month. Runs time out after ten minutes, and actual speed depends on holdings, model, horizon and hardware.
- Background jobs use two Python calculation threads, bounded to eight outstanding jobs and sixteen retained job records. Jobs expire after fifteen minutes; results live only in memory. Closing/reloading a page requests cancellation. Queue overload, numerical failures and missing history are visible errors.
- **Run one Gunicorn worker process with multiple request threads** (`--workers 1 --threads 8`). The Docker command and README reflect this because the job registry is in process memory. Server restart clears jobs; polling reports that and offers a rerun. A future multi-process deployment would need a shared queue/result service.
- `/api/jobs` creates a run, `/api/jobs/<id>` reports progress/results, and `/api/jobs/<id>/cancel` requests cancellation. IDs are unguessable capabilities; same-origin POST checks and no-store API responses remain in force. `/api/model-options` exposes public defaults. Showcase mode still blocks live market use and uploads.
- `/api/simulate` retains the original synchronous behavior and limits for compatibility. New UI runs use the extended background endpoint. Direct and background executions use the same new numerical function; comparison mode runs each model with the same inputs and seed, but different models consume random numbers differently. Exact reproducibility is tested within the installed environment, not promised across arbitrary NumPy/platform changes.

## Validation

Run `.venv/bin/python -m pytest -q`. Tests cover original GBM equality, deterministic repeats, Merton zero-jump and compensation behavior, constant-variance Heston behavior, bootstrap row pairing, custom scaling, held-out data separation, calendar gaps, percentile ties, 100,000-path output, background/direct equality, progress, cancellation, errors and showcase restrictions, alongside the existing importer/market tests.

Changed files: `app.py` connects the new job API and exposes demo inputs without changing its values; `templates/index.html` and `static/app.js` connect controls and plots; `static/style.css` only adds rules using existing tokens; `Dockerfile` sets the compatible process count; `README.md` documents usage. Added: `portfolio_sim/models.py`, `scenarios.py`, `experiments.py`, `jobs.py`, `static/experiments.js`, this guide, and focused model/job tests. No dependency files changed.

## Help page and personal credits

The top-right **How does it work?** link opens `/how-it-works` in a new tab, preserving the current simulator tab. It uses the same styles and saved theme. To personalize Credits, edit `creator_name` and `linkedin_url` near the bottom of `templates/how-it-works.html`. An empty URL shows a placeholder rather than a broken link; supply your full LinkedIn URL to activate it.

## Chart responsiveness

`static/chart-data.js` keeps every monthly line point while combining visible endpoints and backtest markers into one sparse marker trace. Click targets still identify the original path. Path selection updates only affected traces in one redraw; initial rendering no longer triggers an unnecessary highlight redraw. No financial calculations or chart data are reduced.

Local browser check (30-year synthetic portfolio, 25 sample paths, 30 measured axis-range updates after two warm-ups): median redraw including the next animation frame fell from 127.5 ms to 16.7 ms; 95th percentile fell from 137.9 ms to 17.8 ms. SVG marker count fell from 9,025 to 25. These are local benchmark results, not a guaranteed frame rate on every device.
