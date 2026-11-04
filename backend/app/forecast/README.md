# `app/forecast` — Phase 6 cash-flow forecasting

Answers "what will income, expenses and (if you told us a starting balance) the
cash balance look like over the next 1–12 months?" with a projection, an
uncertainty interval, and the assumptions behind it. No FastAPI imports, so
Phase 8's agent can call `engine.forecast_cashflow` as a tool. Nothing is stored:
a forecast is a pure function of your transactions, your balances and the
request parameters, so persisting one would only create something that goes
stale on the next upload.

> **Read this first.** This is decision support, not financial advice, and the
> accuracy numbers below come from **synthetic** series written by the same
> author as the models. They show how the methods behave under assumptions, not
> how well they predict *your* spending.

## How a forecast is built

```
transactions (per currency, duplicates excluded)
   │
   ├─ detect recurring series on data ≤ origin        (reuses app/ml/recurring.py)
   │     trusted = confidence ≥ 0.5
   │     ├─ active trusted series  → projected onto dates   (schedule.py, exact amounts)
   │     └─ all trusted members    → REMOVED from the history the models see
   │
   ├─ monthly "variable" history = everything else     (history.py: cleaning rules below)
   │     expense series, income series, each forecast on its own   (backtest.py + methods.py)
   │
   └─ per period:  recurring + variable  →  expense, income, net
                   opening balance + Σ net →  end-of-period balance (+ interval, verdict)
```

Recurring payments are **re-detected here** from transactions on or before the
origin instead of read from the stored `recurring_series` rows: stored rows
cover the whole history, so a what-if `as_of` would leak the future into the
schedule, and they go stale between uploads.

**Origin** (`as_of` in the response) = the last transaction date on or before the
`as_of` query parameter, **per currency**. Periods are: the rest of the origin's
month (a *stub*, if the origin isn't a month-end) followed by `horizon_months`
full calendar months (UTC).

## History cleaning (`history.py`)

Each rule exists because the naive alternative biases a "can I afford it" answer.

| Rule | Why |
|---|---|
| The month containing the origin is dropped unless the origin is its last day | half a month of spending looks like a sudden saving |
| The first month is dropped if the first transaction is after day 7 *and* ≥3 months remain | can't tell a statement starting on the 12th from a user who spent nothing on the 1st–11th (a heuristic) |
| A month with **no** transactions inside the data span is a missing statement, not zero spending; only the history after the newest such hole is used | zero-filling would teach a model that spending collapses (Phase 4's monthly view zero-fills for display, harmlessly) |
| Rows belonging to trusted recurring series are removed from the variable amounts but still count as "this month has data" | a month holding only a rent payment is not missing |

## Methods (`methods.py`) and selection (`backtest.py`)

Nine methods for one short monthly series, all non-negative (negative
extrapolations are clipped to 0, and the backtest scores the clipped values).

| Method | Min history to fit | Usable in the selector from |
|---|---:|---:|
| `naive` (last month) | 2 | 7 months |
| `moving_average_3` | 3 | 7 |
| `median_12` | 3 | 7 |
| `drift` (first→last slope) | 4 | 12 |
| `moving_average_6` | 6 | 14 |
| `ets_ann` (statsmodels `ETSModel`, additive error, level only) | 6 | 14 |
| `ets_damped_trend` | 10 | 18 |
| `seasonal_naive` (same month last year) | 12 | 20 |
| `ets_seasonal` (additive seasonality, period 12) | 36 | 44 |

Seasonal ETS needs three years because a 12-period seasonal state spends 11
degrees of freedom (Hyndman, *Fitting models to short time series*); on 24
points that is more parameters than the data supports, so it is not offered.

**Selection = rolling-origin backtest** (Hyndman, *Time series
cross-validation*): train on everything before each origin, record the 1..h
step-ahead errors, roll forward. Rules:

* every contestant is scored on the **same** origins;
* a method enters only if it can be scored on `max(4, min(8, n−3))` origins;
* lowest MAE wins, but any model within **2 %** of the best MAE ties and the
  **simplest** tied model is taken (a convention, not a tuned value; see
  sensitivity below);
* the winner is refit on the full history to produce the forecast.

Modes reported per series: `backtested`; `limited` (fewer than 7 usable months:
last-3-month average, **no interval**); `all_zero` (every month 0 → forecast 0,
the normal state for the income side of a salaried user, not a warning);
`unavailable` (fewer than 3 usable months).

## Intervals

Per step, the half-width is an empirical `(m+1)`-adjusted quantile of the
**selected model's own absolute backtest errors** at that step (split-conformal
style, no distribution assumed). A step with fewer than 5 errors borrows the
nearest shorter step's width and says so in `interval_basis` (borrowed intervals
are usually too narrow, since error grows with horizon). Net and balance
intervals combine the income and expense widths, and successive months, **in
quadrature, assuming independent errors**. That combination is **not
validated** by any test or evaluation here.

## Balance and verdict

* `Account.opening_balance` / `balance_as_of` (migration 0007) are
  **user-supplied** via `PUT /accounts/{id}/balance`. Signed: negative = money
  owed. True at the **end** of `balance_as_of`; later transactions are added on
  top, earlier-or-equal ones are already inside it.
* A projected balance is produced only if **every account with transactions in
  that currency has a balance**; otherwise balances are withheld (projecting
  one account's flows against another's balance would be wrong) and the
  response says which accounts are missing one.
* `verdict` is judged on the end of the **first full month**: `shortfall` if the
  point balance is negative, `at_risk` if the lower interval bound is negative,
  else `covered`; `unknown` when no verdict can be supported (no/partial
  balance, too little history). `verdict_basis` says whether an interval backed it.
* Only **period-end** balances exist. A large bill early in a month can overdraw
  an account that ends the month positive; that is invisible here.

## Recurring payments

Projected at the series' recent typical amount (median of the last three) on
calendar-stepped dates (the 5th stays the 5th; the 31st clamps to month-end and
the clamp persists, so a 28 Feb payment shows as 28 Mar — always the right
*month*, so totals are unaffected). A payment already overdue by no more than
its cadence tolerance is assumed still pending and placed on the first forecast
day (under-counting a bill is the unsafe direction); further overdue it is
treated as skipped. Variable-amount bills (utilities) use their typical amount
with **no uncertainty band**. Series confidence < 0.5 is not trusted, so those
flows stay in the statistical (variable) forecast.

## API

```
PUT    /accounts/{id}/balance     {opening_balance, balance_as_of}   signed, ≤ 2 dp, ≤ 14 digits, date ≤ today+1
DELETE /accounts/{id}/balance     idempotent; forecasts for that account become flow-only
GET    /forecast/cashflow         ?horizon_months=1..12 (3)  &interval_level=0.5..0.95 (0.8)  &as_of=YYYY-MM-DD  &account_id
```

The response carries per currency: `periods[]` (recurring lines, variable and
total expense/income/net with lows/highs, projected balances), the expense and
income model summaries **including the full backtest leaderboard**,
`balance` info, `verdict`, `assumptions[]` and `warnings[]` (stale data,
excluded months, pending bills, withheld balances, few backtest origins…).
Money is a JSON string; statistics are floats. Cost: one backtest per series per
request, measured 1 ms at 12 months of history, 75 ms at 18, 119 ms at 24, 221 ms
at 36, 391 ms at 48 (one series, this sandbox, single-threaded; a currency needs two).

## Evaluation (`python -m app.forecast.eval`)

Full tables: [`../../docs/forecast_eval/report.md`](../../docs/forecast_eval/report.md).
600 synthetic series (six archetypes, train lengths 12–48 months, 3-month
holdout, seed 7). MASE = MAE ÷ the train part's in-sample one-step naive MAE;
values above 1 are expected because the holdout is 1–3 steps ahead.

| Finding | Evidence (paired difference in MASE, 95 % bootstrap CI) |
|---|---|
| The shipped selector beats the simple baselines | vs `naive` −0.097 [−0.152, −0.041]; vs `moving_average_3` −0.086 [−0.138, −0.033]; vs `median_12` −0.218 [−0.296, −0.143] |
| **…but not "always use level-ETS"** | vs `ets_ann` **+0.010 [−0.030, +0.052]**: a tie. On a second corpus (seed 11, 400 series) it was −0.048 [−0.102, +0.004]. Sign flips; both include 0 |
| Selection captures little of the available headroom | hindsight oracle (best fixed method per series) MASE 0.727 vs `auto` 1.107 |
| The pooled GBM (**eval-only**, trained on other synthetic series from the same archetypes, so flattered) does not beat the shipped pipeline | GBM − auto **+0.029 [−0.023, +0.078]**; supports keeping it out of the user path |
| Single-series intervals were close to nominal on this data | observed coverage of the nominal 80 % interval: 83.0 / 81.8 / 79.5 % at steps 1/2/3; by history length 84.4, 84.2, 79.7, 81.4, 77.5 % (12→48 months) |
| The 2 % tie-break does not matter | auto mean MASE 1.0476 / 1.0465 / 1.0462 for tolerance 0 / 0.02 / 0.05 (seed 11, 400 series) |

What this does **not** show: anything about real spending; the combined
net/balance intervals; behaviour with transfers or card-bill payments in the data;
long horizons (only 3 steps were held out).

## Known gaps (Phase 6)

* **Origin = last transaction date.** A user whose last transaction isn't on the
  final day of its month has that month treated as partial and dropped (one month
  less history) and gets a prorated stub month. Conservative, but lossy.
* **Balance intervals are unvalidated** (independence assumed across months and between income and expense).
* **Transfers and card-bill payments count as income/expense** (inherited from Phase 4/5). For someone who pays a credit card from checking this can badly distort both forecasts.
* **The starting balance is whatever the user typed.** Nothing reconciles it with statements (Phase 3 doesn't parse a running-balance column); a wrong number gives wrong balances.
* Recurring misses (e.g. dates that wander > ±4.5 days) fall into the variable forecast; false positives are projected as bills. Rows with no `merchant_normalized` can never be recurring.
* No seasonality below ~20 months (naive) / 44 months (ETS): annual bills and festival months are invisible unless caught as a yearly recurring series (which needs ≥2 occurrences).
* Additive ETS only; no covariates, no scenario inputs ("I'll buy a laptop in March"), no budget projection (Phase 9).
* Multi-account currencies are forecast pooled; per-account forecasts only via `account_id`.
* Forecasts are not stored, so there is no live record of how past forecasts fared against what happened.
* Synchronous request-time compute; no caching. Fine at these lengths, not designed for bulk.
* UTC months and UTC "today" for the stale-data warning (an IST user sees month rollover at 05:30).
