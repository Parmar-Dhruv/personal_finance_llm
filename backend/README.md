# FinSight backend

FastAPI + Celery + SQLAlchemy 2 + Alembic. This README is the backend
deep-dive: how the code is layered, exactly what the Phase 4 analytics
compute (and don't), how the Phase 5 ML layer and Phase 6 forecaster behave, and how to run the test suite. For the project-level
overview see the [root README](../README.md); for decisions and history see
[`PROGRESS_TRACKER.md`](../docs/PROGRESS_TRACKER.md).

**Status: Phases 0–6 of 13 built.** Phase 6 adds on-demand cash-flow forecasting (statistical, with intervals; no stored forecasts). Classical ML (scikit-learn) and statistical detectors exist. An opt-in LLM classifier (Anthropic + Gemini adapters) exists but is not wired into the pipeline; the Gemini adapter was run against the real API for evaluation, the Anthropic adapter remains unverified.

---

## Layering

```
HTTP request
   │
   ▼
app/api/*          routers: parse input, authenticate, authorize (ownership → 404), delegate
   │
   ├──► app/schemas/*     Pydantic request/response models (money = Decimal → JSON string)
   │
   ├──► app/analytics/*   Phase 4 – pure SQL + Decimal functions: (Session, Scope) → dataclasses.
   │                      No FastAPI imports, on purpose: Phase 8's agent will call these directly as tools.
   │
   ├──► app/ml/*          Phase 5 – classifier, duplicate/recurring/anomaly detectors. Pure Python/sklearn;
   │                      only ml/service.py touches the DB (per-user advisory lock, never commits).
   │
   ├──► app/forecast/*    Phase 6 – recurring schedule + backtest-selected statistical forecast + balance projection.
   │                      Pure functions plus one DB-reading module (history.py) and one DB wrapper (engine.forecast_cashflow).
   │                      No FastAPI imports; reuses ml/recurring.py's detector. See app/forecast/README.md.
   │
   ├──► app/pipeline/*    Phases 2–5 – Celery tasks, extractors, normalization
   │
   └──► app/db/*          SQLAlchemy models + session
        app/core/*        config, security (Argon2id/JWT), S3 storage client, Celery app
```

Rules every layer follows: ownership is checked in code (`user_id` filters;
a row that is missing *or* someone else's returns 404, never 403); money is
`Numeric(14,2)`/`Decimal`, never float; UUIDv7 primary keys.

## Folder structure

```
backend/
├── alembic/versions/
│   ├── 0001_initial_schema.py       users, accounts, categories, documents, transactions
│   ├── 0002_document_pages.py       DocumentPage (provenance)
│   ├── 0003_normalization.py        normalization status, merchant_aliases + seed
│   ├── 0004_analytics_budgets.py    budgets, category uniqueness fix, 10 system categories, indexes
│   ├── 0005_ml_layer.py             recurring_series; category/duplicate/anomaly provenance; self-FK indexes
│   ├── 0006_merchant_alias_uniqueness.py   MerchantAlias UNIQUE NULLS NOT DISTINCT
│   └── 0007_account_balance.py      accounts.opening_balance + balance_as_of, both-or-neither CHECK (Phase 6)
├── app/
│   ├── main.py
│   ├── core/            config.py security.py storage.py celery_app.py
│   ├── db/              base.py models.py
│   ├── schemas/         auth account document transaction category budget analytics ml forecast
│   ├── api/
│   │   ├── auth.py accounts.py documents.py transactions.py deps.py      (Phases 0–3)
│   │   ├── categories.py budgets.py analytics.py                          (Phase 4)
│   │   ├── ml.py   (+ suggestion/duplicate actions in transactions.py)    (Phase 5)
│   │   └── forecast.py   (+ PUT/DELETE /accounts/{id}/balance in accounts.py)  (Phase 6)
│   ├── analytics/       (Phase 4)
│   │   ├── common.py        Scope, shared WHERE clause, money/pct helpers, month math
│   │   ├── cashflow.py      summary() and monthly()
│   │   ├── breakdowns.py    by_category() by_merchant() by_account()
│   │   ├── budgets.py       utilization(), category_subtree_ids()
│   │   └── recurring.py     monthly-equivalent recurring totals (Phase 5)
│   ├── ml/              (Phase 5)
│   │   ├── taxonomy.py rules.py classifier.py llm_classifier.py
│   │   ├── duplicates.py recurring.py anomalies.py      pure detectors
│   │   ├── service.py       DB glue; enrich_user() runs all four steps in order
│   │   ├── synthetic.py eval.py train.py eval_llm.py eval_public.py
│   │   └── (models/ is git-ignored: `python -m app.ml.train` writes classifier.joblib + .meta.json)
│   ├── forecast/        (Phase 6)  methods backtest schedule history engine eval  + README.md
│   └── pipeline/        extractors/ (Phase 2)  normalize/ (Phase 3)  tasks.py
├── docs/ml_eval/        synthetic CV (report.md/json), public OOD, real Gemini run
├── docs/forecast_eval/  Phase 6: synthetic backtest, GBM benchmark, interval coverage (report.md/json)
├── tests/               real-Postgres pytest suite (see "Testing")
├── pytest.ini  requirements.txt  requirements-dev.txt  Dockerfile  alembic.ini
```

---

## Phase 4: what the analytics compute

All endpoints are `GET`, read-only, per-user, and accept the same optional
filters: `date_from`, `date_to` (both **inclusive**), `account_id`.
Everything is computed live in SQL on every request (no caching).

### Ground rules (apply to every number)

1. **Per currency, never converted.** Results are lists keyed by `currency`.
   INR and USD are never added, compared or converted. There is no FX data
   anywhere in the system. (Decision: Dhruv, 2026-10-18.)
2. **Direction comes from `transaction_type`.** `credit` = income, `debit` =
   expense. `Transaction.amount` is always a positive magnitude.
3. **Flagged duplicates are excluded** (`duplicate_of_id IS NOT NULL`). Nothing
   sets that flag until Phase 5, so today this is a forward-compatible no-op.
4. **Every transaction counts equally.** `confidence_score` is not used as a
   filter or weight — a row the normalizer was unsure about (e.g. an unsigned
   single-amount column defaulted to debit) is summed like any other.
5. **Calendar dates, UTC.** The pipeline stores each date as midnight UTC, so
   months are bucketed in UTC. `date_to` is made inclusive by comparing
   `< date_to + 1 day`.
6. **Exact arithmetic.** SQL `SUM` over `Numeric`, Python `Decimal` for
   percentages (2 dp, half-up). Money and percentages serialize as JSON
   strings (`"1250.50"`) so clients can't lose cents.

### Endpoints

| Endpoint | Returns |
|---|---|
| `GET /analytics/summary` | per currency: `income`, `expense`, `net`, counts, `savings_rate_pct` (net ÷ income; `null` when income is 0) |
| `GET /analytics/monthly` | per currency: one point per calendar month — income/expense/net, count, `partial`, and change vs the previous calendar month (absolute and %) |
| `GET /analytics/categories?type=&limit=` | per currency: totals per **directly assigned** category, plus an explicit `Uncategorized` row, `pct_of_total`, and `other_total` for rows cut by `limit` |
| `GET /analytics/merchants?type=&limit=` | same shape, grouped by canonical merchant (`merchant_normalized`); NULL merchants pooled as `(unknown merchant)`; default `limit=10` |
| `GET /analytics/accounts` | one row per account (and currency) with income/expense/net; idle accounts appear with zeros |
| `GET /analytics/budget-utilization?month=YYYY-MM` | every active budget for that month: `limit`, `spent`, `remaining`, `pct_used`, `status` |

`type` is `debit` (default) or `credit`.

Behaviors worth knowing:

- **Monthly gap-fill.** Months with no activity inside the series are returned as
  zeros, so "previous month" always means the previous *calendar* month. The
  series spans `date_from`..`date_to` if given, otherwise the currency's own
  first..last month of data.
- **`partial: true`** marks a first/last month that the requested range clips.
  Its totals cover only part of the month — don't read its change-vs-previous as
  a like-for-like comparison. (The *current* in-progress month is not flagged
  unless `date_to` clips it.)
- **% change is `null` when the previous value is 0** (undefined, not 0 and not
  infinity). The absolute change is still given.
- **Ties are ordered deterministically** (amount desc, then label).

### Budgets

A budget is `(category or overall, currency, monthly amount, alert threshold %)`.

- Create/list/patch/delete via `/budgets`. `category_id: null` = overall budget.
- At most **one budget per (user, category, currency)** — enforced in Postgres
  with `UNIQUE NULLS NOT DISTINCT`, so that includes "one overall budget per
  currency". Violations return 409 (also under concurrent requests).
- **Spent** = debits only, in the budget's currency, inside the calendar month,
  excluding flagged duplicates.
- A **category budget includes its whole subtree** (recursive CTE): a budget on
  `Food` counts spend on `Food › Takeaway › Pizza`. An **overall budget counts
  everything**, including uncategorized spend — so it is *not* the sum of the
  category budgets beside it.
- **Status:** `over` if `spent > limit`; else `near` if `spent ≥ threshold% × limit`;
  else `ok`. Spending exactly the limit is `near`, not `over`. The comparison uses
  exact values, not the rounded `pct_used` (79.996% displays as `80.00` but is
  still `ok` against an 80% threshold).
- Inactive budgets (`is_active=false`) are listed by `GET /budgets` but skipped
  by utilization.
- `PATCH /budgets/{id}` can change `amount`, `alert_threshold_pct`, `is_active`.
  Category and currency are immutable — delete and recreate.

### Categories (minimal)

- `POST /categories {name, parent_id?}` and `GET /categories` (system + your own).
- Ten **system categories** are seeded by migration 0004 (the spec's list: Food,
  Transportation, Shopping, Utilities, Entertainment, Healthcare, Travel, Rent,
  Salary, Business expenses). Nothing assigns them automatically yet — that is Phase 5.
- Names are unique per level case-insensitively and can't shadow a system category.
  Nesting is capped at 3 levels (an arbitrary guard).
- `PATCH /transactions/{id} {"category_id": <id>|null}` assigns/clears a category.
  Omitting the field is a no-op; explicit `null` clears it. Only system or your own
  categories are accepted.
- No rename, move or delete (see Known gaps).

---

## Phase 5: ML layer (design and exact behavior)

### Pipeline and ordering
`enrich_user()` runs, for one user: **duplicates → classification → recurring → anomalies.**
Duplicates first because flagged rows are excluded from everything after; categories before
anomalies because category baselines use them. It runs automatically (Celery
`enrich_user_transactions`, chained after `normalize_document`) and on demand (`POST /ml/run`).
Every step is idempotent, user-scoped, and serialized per user by a Postgres advisory lock
(without it, two concurrent runs duplicated recurring series — tested).

### Classification
- Label set = the ten system categories from migration 0004. A debit can never be `Salary` (hard mask, applies to rules, ML and the LLM parser).
- **Policy.** `rule` or `hybrid` (rule and ML agree) predictions → auto-applied (`category_source` = rule/hybrid). `ml`-only → suggestion only (`suggested_category_*`), because the measured ML-only precision on unseen merchants is ~30% and its confidence is not calibrated. The auto threshold for ML-only lives in the model metadata (`ml_only_auto_apply_threshold`); it is currently `null` = never. Below 0.5 → no prediction.
- A confident ML disagreement (≥0.95) overrides a rule; otherwise the rule wins.
- **Provenance rules.** `category_source='user'` is final (PATCH, accepting a suggestion). A category with no recorded source is treated as the user's. Rejecting a suggestion or clearing a category sets `suggestion_dismissed`, which even `force_reclassify` respects; `POST /transactions/{id}/suggestion/undismiss` clears only that flag so suggestions may resume (a user-set category stays final). `force_reclassify` re-evaluates only earlier machine decisions and clears ones the current model no longer backs.
- **Model lifecycle.** `python -m app.ml.train` → synthetic data → `models/classifier.joblib` + `.meta.json` (sha256, sklearn version, metrics). If the file is missing, corrupt, or from a different scikit-learn version, the system degrades to **rules-only** and says so in `GET /ml/status` instead of failing. Pickle caveat: trusted-write directory only.
- **Training data is synthetic** (`ml/synthetic.py`, ~240 merchants, Indian-bank-style narrations). Evaluation holds out whole merchants.

### Phase 5 evaluation results
- **Synthetic holdout** (merchant-grouped CV): rules 82%, ML-only 42%, hybrid 86% accuracy (abstentions count as wrong).
- **Public OOD** (`docs/ml_eval/public_ood.json`, 12,144 mapped of 20,000 requested): 60.7% of requested rows mapped; among mapped rows, 48.9% answer coverage, 48.6% precision on answered, 23.8% accuracy counting abstentions as wrong. The label map is lossy; treat this as a warning signal, not a benchmark.
- **LLM** (`docs/ml_eval/llm_synthetic.json`, Gemini 3.5 Flash-Lite, n=300, 25 per request): 94.3% accuracy vs 91.3% for hybrid on the same synthetic holdout, 0 abstentions (fixed `LLM_CONFIDENCE=0.80`, not calibration). This is a separate single-holdout protocol, not the 5-fold CV above. Synthetic merchants flatter every method; this does not establish real-statement accuracy.

### Duplicates
Compared only within the same account, currency, direction and exact amount, within 3 days.
`score = 0.45·date + 0.35·narration similarity + 0.20·cross-document`, ×0.25 if both narrations carry
bank reference numbers that differ, ×0.5 for same-document "habit" repeats (≥4 in a week). ≥0.95 →
`duplicate_of_id` set (analytics exclude the later row); 0.70–0.95 → `pending` for review; below → nothing.
The later-uploaded document's row is the duplicate. `confirm` / `dismiss` are final and survive re-runs;
the detector withdraws its own stale flags (e.g. if the original was deleted).

### Recurring
Per (account, currency, direction, merchant): distinct dates → intervals → snap median to
weekly / biweekly / monthly (30.44 ± 4.5 d) / quarterly / yearly; ≥75% of intervals on cadence (a skipped period counts half);
min occurrences 4/4/3/3/2. Amount: MAD/median ≤5% = fixed price, ≤50% = variable bill, else rejected. If the merchant as a whole
fails, each ±5% amount cluster (needing one extra occurrence — see the chance-match fix below) is tried alone. `as_of` is the user's latest transaction date.
`/analytics/recurring` totals = Σ typical amount × (52/12, 26/12, 1, 1/3, 1/12) per currency, active series only by default.

### Anomalies
Modified z = 0.6745·(ln x − median)/max(MAD, 0.15) against the merchant (≥8 txns), else category (≥15), else user-wide (≥30),
per currency+direction; flag at z ≥ 3.5, upward only. No sufficient baseline → `anomaly_score` null (unknown, not normal).
The 0.15 floor means a flat baseline needs a ≥2.2× jump to flag.

### Things the evaluation caught (kept here because they changed the code or the claims)
1. ML on unseen merchants: 42% accuracy, confidence anti-calibrated → ML-only never auto-applies.
2. Recurring: "quarterly" false positives for busy merchants (Uber, 5/20 users) from lucky 3-point amount clusters → cluster path now requires one more occurrence; 0 false positives afterwards.
3. Anomaly ground truth: my first injected anomalies (×6–15) were often only ~2σ for high-variance merchants — the data, not the detector, was at fault. Now two severities are reported separately; the detector's real weakness (recall 0.13 on moderate) is stated, not tuned away.
4. Deleting a user with 100k transactions took >15 min: unindexed self-referencing FKs (`duplicate_of_id`, new `duplicate_candidate_of_id`). Partial indexes added in 0005.

### Phase 5 tests
91 new tests (87 Phase 5 + 4 pre-Phase 6 hardening): `tests/test_ml_units.py` (pure algorithms: rule ordering, Salary-credit constraint, hybrid override, persistence failure modes,
cadences, price rise, skipped month, chance clusters, duplicate thresholds/refs/habits/triplicates, anomaly floors/fallbacks/currency separation, LLM parser abuse cases, Gemini batching/structured output/factory),
`tests/test_ml_service_api.py` (real Postgres + HTTP: auto vs suggest, user-final, reject-sticks, force semantics, duplicates through analytics, human decisions surviving re-runs,
exact recurring totals, concurrent runs, cross-user isolation, 401s, the Celery task body) and the 0005 backfill/constraint/round-trip test. Verified separately (not in the suite):
a real Celery worker on a real Redis broker running normalize → enrich; and the 100k-row timing run.
The LLM unit tests use stand-in clients for *batching/parsing plumbing*. The real API evidence is the committed Gemini eval result (`docs/ml_eval/llm_synthetic.json`); the Anthropic path still has none.

---

## Phase 6: forecasting (summary; full detail in `app/forecast/README.md`)

`GET /forecast/cashflow` computes, per currency and on every request, a forecast of income, expense and net for the rest of the
current month plus 1–12 full months, split into **recurring** payments (Phase 5's detector re-run on data up to the forecast origin,
projected onto calendar dates at their recent typical amount) and **variable** flow (everything else, one monthly series for expense
and one for income). Each variable series is forecast by whichever of nine methods wins a rolling-origin backtest on that user's own
history; intervals are empirical quantiles of the winner's own backtest errors. If every account in the currency has a user-supplied
balance (`PUT /accounts/{id}/balance`), period-end balances and a `covered` / `at_risk` / `shortfall` / `unknown` verdict are projected.

Rules worth knowing:
- **Origin** = the last transaction on or before `as_of`, per currency. The partial origin month is excluded from the history.
- **A month with no transactions inside the data span is treated as a missing statement, not zero spending.**
- **Fewer than 7 usable months → no backtest, no interval** (last-3-month average); fewer than 3 → no variable forecast.
- **No stored forecasts.** Nothing is written; cost is one backtest per series per request (≈1 ms at 12 months, ≈390 ms at 48 months).
- Statistics (MAE, MASE, interval level) are floats; **all money is Decimal** and serialized as strings.

Evaluation on synthetic series (`docs/forecast_eval/report.md`; `python -m app.forecast.eval`): the selector clearly beats naive baselines
but **ties "always fit level-ETS"**; an eval-only pooled GBM does not beat it; single-series 80 % intervals covered 79.5–83.0 % by step.
All synthetic and same-author. The combined net/balance intervals are not validated.

### Things Phase 6 testing and evaluation caught (they changed code, tests or claims)
1. My first seed data ended each month on the 20th, so the engine (correctly, by design) treated the last month as partial and shifted every period. That exposed a real consequence — a user whose last transaction isn't on a month's final day loses that month — now a documented gap.
2. A salaried user's income history is all-zero variable income; the engine reported that as a *warning* on every request. It is now reported only in the model summary.
3. Running the real Phase 3 → 5 → 6 pipeline showed a once-a-month variable-amount purchase is (correctly) detected as a recurring bill — my test had called it variable spend. Its projected *day* drifts to the 28th (month-end clamping), always in the right month.
4. The 2 % tie-break I suspected was hurting selection turned out not to matter (auto MASE 1.0476 / 1.0465 / 1.0462 for 0 / 2 / 5 %).
5. I predicted selection optimism would make intervals too narrow; on synthetic data coverage was close to nominal. I corrected the docstring that claimed otherwise.
6. I never compared the selector with "always ETS" until late; the result (a tie) is now stated instead of implying selection adds accuracy.

### Phase 6 tests
`tests/test_forecast_units.py` (pure: method values by hand, eligibility, shared origins, a perfectly linear series selects drift with zero error, tolerance band, conformal quantiles and borrowing, schedule stepping/clamping/overdue rules, history cleaning rules, engine recurring-exact/variable-statistical split, balance chain and as-of-date semantics, verdicts, stub proration, plus a 40-seed random-history fuzz of numeric invariants), `tests/test_forecast_api.py`
(real Postgres + HTTP: auth, balance validation and the Numeric(14,2) boundary, DB both-or-neither CHECK, isolation, end-to-end hand-derived numbers, currency separation, duplicates ignored, `as_of`, account filter and balance completeness, short-history degradation, 12-month horizon, and a seam test where the statement goes through the **real** normalizer and enrichment pipeline), `tests/test_forecast_eval.py` (the harness stays runnable and deterministic), and a 0007 migration round-trip test.
Celery is not involved in Phase 6 (forecasts are computed on request).

---

## Known gaps and limitations (Phase 4)

Deliberate scope cuts and unfixed weaknesses, stated plainly. The rolled-up
list across all phases is in `PROGRESS_TRACKER.md` §5.

**Correctness caveats a user could be misled by**
- **Transfers are counted as spending/income.** Paying a credit-card bill from
  your checking account shows as an expense on checking *and* the purchases show
  again on the card; moving money between your own accounts inflates both income
  and expense. There is no transfer detection (needs Phase 5 classification).
- **Refunds are not netted.** A refund is a credit, so it raises income and does
  *not* reduce category spend or budget utilization. Category/merchant/budget
  "spent" is gross debits.
- **Only as good as Phase 3's debit/credit call.** Single-amount-column statements
  with no sign default to `debit` (confidence 0.5); analytics sums them as real
  expenses. Credit-card statements, where "credit" can mean a payment *or* a
  refund, have not been validated against real-world layouts.
- **Category breakdown is direct-only; budgets roll up.** `/analytics/categories`
  reports the category each transaction is assigned to (no parent roll-up), while a
  budget on a parent counts its descendants. Both are documented, but they will not
  visually reconcile for nested categories.
- ~~No "recurring expense totals" (spec §8)~~ **Delivered in Phase 5** as `GET /analytics/recurring`;
  it is only as good as the detector (see Phase 5).

**Scope cuts**
- No currency conversion; no combined "total across currencies" (decision).
- Budgets are calendar-monthly only: no weekly/yearly/custom periods, rollover,
  proration, or forecast-based "will you overspend" (Phase 6 built the forecast; projecting budgets with it is not done — Phase 9).
- Budget status is computed on request. Nothing *delivers* an alert (Phase 9).
- Categories can't be renamed, moved or deleted via the API; assignment is one
  transaction at a time (no bulk). Deleting a category in the DB cascades to its
  budgets and children.
- Month bucketing is UTC, and "current month" for `budget-utilization` defaults to
  the current UTC month, so for a user in IST the month rolls over at 05:30 local.

**Operational**
- Analytics are recomputed per request; no caching or materialized views.
  Measured on the sandbox (Postgres 16, one user with 104k transactions among
  204k rows): all-time summary ≈ 46 ms, one-month ≈ 5 ms, and the planner uses
  `ix_transactions_user_date`. Not benchmarked on PG18, under concurrency, or at
  larger scale.
- Breakdown/merchant endpoints return all matching groups unless `limit` is given.

**Fixed pre-Phase 6** — `GET /transactions?date_to=` now uses the same half-open
upper bound as analytics (`< date_to + 1 day`), so the whole calendar day is
included even for rows that carry a time. Other gaps are listed in the root README.

---

## Running things

```bash
# whole stack
cp ../.env.example ../.env       # then fill in secrets
docker compose up --build        # from the repo root
docker compose exec backend alembic upgrade head
```

Interactive API docs: <http://localhost:8000/docs>.

### Testing

The suite runs against **real Postgres** through the **real HTTP stack**
(FastAPI `TestClient`), with schema built by the **real Alembic migrations**.
No mocks. It needs:

- a Postgres 15+ server with the `pgvector` extension available (15+ because
  migration 0004 uses `NULLS NOT DISTINCT`);
- a database whose name ends in `_test` — the suite **drops and recreates the
  `public` schema**, and refuses to run otherwise;
- optionally a second DB `finsight_migration_test` for the migration round-trip.

```bash
pip install -r requirements-dev.txt
export TEST_DATABASE_URL=postgresql+psycopg://finsight:finsight_dev_password@localhost:5432/finsight_test
pytest
```

The production image does not include pytest, and `localhost` is the wrong DB
host inside Compose. To run the same suite in the running stack:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+psycopg://finsight:finsight_dev_password@db:5432/finsight_test \
  backend sh -c "pip install -q -r requirements-dev.txt && pytest"
```

What's covered (Phase 4 portion, 60 of 264 tests; Phase 5 and Phase 6 coverage are described above): exact-decimal sums (1000 × 0.10 = 100.00); currency
separation; inclusive date boundaries, month/year/leap-day edges; gap-filled
monthly series and partial flags; zero-denominator percentages; duplicate
exclusion; category/merchant/account breakdowns incl. ties and `limit`; budget
status boundaries (79.999%, exactly threshold, exactly limit, 1 cent over);
category-subtree roll-up; per-currency budgets; cross-user isolation and 401 on
every endpoint; input validation (NaN, 3-decimal amounts, bad months);
concurrent duplicate category/budget creation (one 201, rest 409, no 500s);
migration upgrade → downgrade → upgrade with the constraints checked in raw SQL;
and a seam test where transactions come from the real Phase 3 normalizer.

**Not covered:** Celery/Valkey/SeaweedFS/OCR (untouched this phase — Phases 1–3
were verified against them earlier; they were not re-run end-to-end here),
Postgres 18 specifically (sandbox runs 16), and anything frontend.

On Postgres < 18 the harness creates a `uuidv7()` polyfill backed by
`gen_random_uuid()` **inside the test database only** (`tests/conftest.py`).
Shipped migrations and models always use the native `uuidv7()`.
