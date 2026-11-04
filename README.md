# FinSight

An agentic financial intelligence platform. Uploaded bank/credit-card
statements, receipts, and spreadsheets go through document extraction →
data normalization → (eventually) analytics, RAG, and agentic
natural-language Q&A, with every answer traceable back to a source
document and page.

**Status: Phases 0–6 of 13 complete.** This README describes what's
actually built and running today, not the end-state design — for the
full 13-phase target architecture and design rationale, see
[`personal_finance_llm.md`](./docs/personal_finance_llm.md). For the
phase-by-phase build history, decisions, and open gaps in full detail,
see [`PROGRESS_TRACKER.md`](./docs/PROGRESS_TRACKER.md) — this README is a
snapshot; that file is the source of truth.

---

## What's built so far

| Phase | Status | What it does |
|---|---|---|
| 0 — Infra scaffold | ✅ | Docker Compose stack, health check across all services |
| 1 — Auth + document upload | ✅ | Signup/login (JWT), document upload to object storage |
| 2 — Document intelligence | ✅ | OCR, table extraction, per-page provenance |
| 3 — Data normalization | ✅ | Dates/amounts/currency → structured `Transaction` rows, merchant canonicalization |
| 4 — Deterministic analytics | ✅ | Income/expense/net cash flow, monthly trends, category/merchant/account summaries, monthly budgets + utilization — all SQL/`Decimal`, per currency |
| 5 — ML layer | ✅ | Rule + ML transaction classification (suggest-first, never overwrites you), duplicate detection with a review queue, recurring-payment detection (+ recurring totals), robust-statistics anomaly flags. Evaluated on synthetic holdout, a public out-of-distribution dataset, and a real Gemini run — **read the Phase 5 caveats below.** |
| 6 — Forecasting | ✅ | Per-currency income / expense / net forecast over 1–12 months: recurring payments projected on their dates + a backtest-selected statistical forecast of everything else, with intervals, assumptions and warnings. Projected cash balance and a covered / at-risk / shortfall verdict **if you set a starting balance**. Evaluated on synthetic data only — **read the Phase 6 section below.** |
| 7–13 | ⬜ | RAG, agentic Q&A, product features, evaluation, security hardening, frontend, deployment |

A document today flows: **upload → object storage → OCR/table
extraction (Celery) → date/amount/merchant normalization (Celery,
auto-chained) → queryable `Transaction` rows → deterministic analytics and
budget utilization via API → (Celery, auto-chained) duplicate / category /
recurring / anomaly enrichment.** Forecasts are computed on demand from those
transactions (nothing is stored). There is no LLM call
in the running system (an LLM classifier exists but is not wired into the
pipeline; it was run only for evaluation — see Phase 5 caveats). Categories are assigned by
rules/ML when confident, suggested when not, and always overridable by hand.

---

## Architecture

```
Frontend (Next.js)
      │
      ▼
Backend API (FastAPI)
      │
      ├──► Analytics layer (app/analytics — plain SQL + Decimal, no HTTP knowledge)
      │       cash flow · monthly trends · category/merchant/account breakdowns ·
      │       budget utilization
      │
      ├──► ML layer (app/ml — pure Python/sklearn, DB only via ml/service.py)   # Phase 5
      │       rules + TF-IDF/LogReg classifier · duplicates · recurring · anomalies
      │
      ├──► Forecast layer (app/forecast — statistics + Decimal, no HTTP knowledge)   # Phase 6
      │       recurring schedule · variable-flow models (naive … ETS) chosen by rolling-origin
      │       backtest · intervals · balance projection · verdict
      │
      ├──► Postgres 18 + pgvector  (users, accounts, documents, document_pages,
      │                             transactions, merchant_aliases, categories, budgets,
      │                             recurring_series)
      ├──► SeaweedFS (S3-compatible object storage — original documents)
      └──► Valkey  ──► Celery workers
                          │
                          ├─ process_document     (Phase 2: OCR / table extraction)
                          ├─ normalize_document    (Phase 3: dates/amounts/merchants
                          │                          → Transaction rows)
                          │    auto-chained after process_document succeeds
                          └─ enrich_user_transactions (Phase 5: duplicates → categories →
                                                       recurring → anomalies, whole-user)
                             auto-chained after normalize_document succeeds
```

Analytics read the `Transaction` table directly and never write to it.
They are **per-currency** (INR and USD totals are never combined or
converted) and live in a layer with no FastAPI imports, so Phase 8's agent
can call the same functions as tools. Exact definitions of every number —
what counts as income, spent, "near budget" — are in
[`backend/README.md`](./backend/README.md).

Every document keeps its original file in object storage as the source
of truth. Extraction writes per-page `DocumentPage` rows (raw text,
tables, OCR confidence, warnings) without mutating the original.
Normalization reads those pages and writes `Transaction` rows, each
carrying `source_document_id` and a `raw_data` JSONB blob back-pointing
to which page and how it was parsed — the evidence chain the later RAG
phase is meant to build on.

**Core design principle carried through every phase:** deterministic
code for what must be correct (parsing, arithmetic), ML for what must
be predicted (later phases), LLMs for what needs flexible language
understanding (later phases). Phases 0–6 contain zero LLM calls in the running system.

---

## Folder structure

```
personal_finance_llm/
├── docs/
│   ├── personal_finance_llm.md   # Full 13-phase project spec / design doc
│   ├── BUILD_LOOP.md              # The research→implement→test→track→deliver loop this project follows
│   ├── PROGRESS_TRACKER.md        # Full decision log, known gaps, session-by-session history
│   └── master_prompt.md
├── docker-compose.yml         # db (Postgres+pgvector), cache (Valkey), seaweedfs, backend, worker, frontend
├── .env.example
│
├── backend/
│   ├── README.md                          # backend deep-dive: analytics definitions, testing, Phase 4 gaps
│   ├── Dockerfile
│   ├── requirements.txt                   # human-edited input
│   ├── requirements.lock.txt              # pinned prod freeze; Docker installs this
│   ├── requirements-dev.txt               # lock + pytest + httpx
│   ├── pytest.ini
│   ├── docs/ml_eval/                      # Phase 5 reports: synthetic CV, public OOD, real Gemini run
│   ├── docs/forecast_eval/                # Phase 6 report: synthetic backtest, GBM benchmark, interval coverage
│   ├── tests/                             # 264 real-Postgres tests (Phase 4: 60; Phase 5: 87; pre-Phase 6: 4; Phase 6: 112 + 1 migration)
│   ├── alembic/
│   │   └── versions/
│   │       ├── 0001_initial_schema.py     # users, accounts, categories, documents, transactions
│   │       ├── 0002_document_pages.py     # DocumentPage + provenance fields (Phase 2)
│   │       ├── 0003_normalization.py      # normalization_status fields, merchant_aliases + seed data (Phase 3)
│   │       ├── 0004_analytics_budgets.py  # budgets, category uniqueness fix, 10 system categories (Phase 4)
│   │       ├── 0005_ml_layer.py           # recurring_series, category/duplicate/anomaly provenance columns + indexes (Phase 5)
│   │       ├── 0006_merchant_alias_uniqueness.py  # MerchantAlias NULLS NOT DISTINCT scope fix
│   │       └── 0007_account_balance.py    # accounts.opening_balance + balance_as_of, both-or-neither CHECK (Phase 6)
│   └── app/
│       ├── main.py                        # FastAPI app, router registration, /health
│       ├── core/
│       │   ├── config.py                  # Settings (env-driven)
│       │   ├── security.py                # Password hashing (Argon2id), JWT
│       │   ├── storage.py                 # SeaweedFS S3 client
│       │   └── celery_app.py
│       ├── db/
│       │   ├── models.py                  # SQLAlchemy models — all tables
│       │   └── base.py                    # Session/engine setup
│       ├── schemas/                       # Pydantic request/response models
│       │   ├── auth.py
│       │   ├── account.py
│       │   ├── document.py
│       │   ├── transaction.py
│       │   ├── category.py                # Phase 4
│       │   ├── budget.py                  # Phase 4
│       │   ├── analytics.py               # Phase 4
│       │   ├── ml.py                      # Phase 5
│       │   └── forecast.py                # Phase 6
│       ├── api/                           # FastAPI routers
│       │   ├── auth.py                    # /auth/signup, /auth/login, /auth/me
│       │   ├── accounts.py                # /accounts (create, list; Phase 6: PUT/DELETE /{id}/balance)
│       │   ├── documents.py               # /documents (upload, list, get, patch, delete, pages, normalize)
│       │   ├── transactions.py            # /transactions (list, get, patch category; Phase 5: suggestion + duplicate review actions)
│       │   ├── categories.py              # /categories (create, list) — Phase 4
│       │   ├── budgets.py                 # /budgets (CRUD) — Phase 4
│       │   ├── analytics.py               # /analytics/* (read-only) — Phase 4 (+ /analytics/recurring, Phase 5)
│       │   ├── ml.py                      # /ml/* run, status, suggestions, duplicates, recurring, anomalies — Phase 5
│       │   ├── forecast.py                # GET /forecast/cashflow — Phase 6
│       │   └── deps.py                    # get_current_user, get_db, ownership helpers
│       ├── analytics/                     # Phase 4 — deterministic analytics (no FastAPI imports)
│       │   ├── common.py                  # Scope, shared filters, money/percent/month helpers
│       │   ├── cashflow.py                # summary(), monthly()
│       │   ├── breakdowns.py              # by_category(), by_merchant(), by_account()
│       │   ├── budgets.py                 # utilization(), category subtree roll-up
│       │   └── recurring.py               # recurring monthly-equivalent totals (Phase 5)
│       ├── forecast/                      # Phase 6 — see "Phase 6: Forecasting" below and forecast/README.md
│       │   ├── methods.py                 # 9 point-forecast methods for one short monthly series
│       │   ├── backtest.py                # rolling-origin backtest, selection, conformal-style intervals
│       │   ├── schedule.py                # projects recurring payments onto dates
│       │   ├── history.py                 # loads transactions, builds the cleaned monthly series
│       │   ├── engine.py                  # per-currency forecast; balance projection; verdict
│       │   ├── eval.py                    # synthetic evaluation + eval-only GBM benchmark (CLI)
│       │   └── README.md                  # design, exact definitions, results, known gaps
│       ├── ml/                            # Phase 5 — see "Phase 5: ML layer" below
│       │   ├── taxonomy.py                # the 10 labels + credit-only constraint
│       │   ├── rules.py                   # ordered regex rule classifier (baseline)
│       │   ├── classifier.py              # TF-IDF + LogReg, hybrid policy, model persistence
│       │   ├── duplicates.py  recurring.py  anomalies.py   # pure detectors, no DB
│       │   ├── service.py                 # the only DB-touching module; per-user advisory lock
│       │   ├── synthetic.py               # synthetic labeled data + user histories
│       │   ├── eval.py  train.py          # evaluation harness; model training CLI
│       │   ├── llm_classifier.py          # Anthropic + Gemini adapters (opt-in)
│       │   └── eval_llm.py  eval_public.py  # scripts for YOU to run (need a key / HF access)
│       └── pipeline/
│           ├── tasks.py                   # Celery tasks: process_document, normalize_document, enrich_user_transactions
│           ├── extractors/                # Phase 2 — document intelligence
│           │   ├── pdf.py                 # pdfplumber + pypdfium2
│           │   ├── image.py
│           │   ├── spreadsheet.py         # pandas + openpyxl
│           │   ├── ocr.py                 # Tesseract
│           │   └── common.py
│           └── normalize/                 # Phase 3 — data normalization
│               ├── engine.py              # orchestrates a document's normalization run
│               ├── columns.py             # header/positional column detection
│               ├── dates.py               # strict DD/MM/YYYY parsing
│               ├── amounts.py             # currency/amount parsing → Decimal
│               └── merchants.py           # cleaning + alias/fuzzy canonicalization
│
└── frontend/
    ├── Dockerfile
    └── app/                                # Next.js — currently just the Phase 0 health-check page
```

---

## Data model (as of Phase 6; Phase 6 adds only the two Account columns, no new tables)

- **User** — auth identity
- **Account** — a bank/card account a user owns; `currency` (ISO code),
  `account_type`; Phase 6 adds an optional user-supplied `opening_balance` (signed, negative =
  owed) with the `balance_as_of` date it was true at the end of. Every `Transaction` belongs to exactly one account
- **Document** — an uploaded file; tracks both extraction status
  (`status`) and normalization status (`normalization_status`) as two
  independent fields, since they can be in different states (e.g.
  extraction done, normalization skipped pending account assignment)
- **DocumentPage** — one row per page/sheet: `raw_text`, `tables`
  (JSONB), `extraction_method`, `ocr_confidence`, `warnings` (JSONB) —
  the provenance layer
- **Transaction** — the normalized output: `transaction_date`, `amount`
  (`Decimal`, never float), `currency`, `transaction_type`
  (debit/credit), `merchant_normalized`, `description_raw`,
  `confidence_score`, `source_document_id`, `raw_data` (JSONB — parse
  method, merchant match tier, etc., for audit)
- **MerchantAlias** — `pattern` (regex) → `canonical_name`, system-seeded
  (`is_system=True`, `user_id=NULL`) or user-defined
- **Category** — system categories (`user_id NULL`; ten seeded by
  migration 0004, from the spec) plus user-created ones, up to 3 levels
  deep. `Transaction.category_id` is written by you (`category_source='user'`,
  final) or auto-applied by rules/ML (`category_source` = rule/hybrid/ml/llm)
- **Budget** (Phase 4) — a monthly limit for one `(category | overall,
  currency)`: `amount`, `alert_threshold_pct`, `is_active`. At most one
  per `(user, category, currency)`, enforced by the database
- **Transaction, Phase 5 additions** — `category_source` / `category_confidence`;
  a pending `suggested_category_*` triple; `duplicate_score`,
  `duplicate_candidate_of_id`, `duplicate_review` (auto/pending/confirmed/dismissed)
  alongside the existing `duplicate_of_id` that analytics honor; `anomaly_score`
  + `anomaly_detail` (the baseline used) with `is_anomaly`; `recurring_series_id`
  with `is_recurring`
- **RecurringSeries** (Phase 5) — one detected stream: merchant, cadence,
  typical amount, fixed vs variable, confidence, active, next expected date.
  Fully derived: deleted and recreated every run, so its ids are not stable

---

## API reference (current)

```
POST   /auth/signup                    {email, password, full_name?}
POST   /auth/login                     OAuth2 password form → {access_token}
GET    /auth/me

POST   /accounts                       {name, account_type, currency}
GET    /accounts
PUT    /accounts/{id}/balance          {opening_balance, balance_as_of}  Phase 6 — the forecast's starting point (signed)
DELETE /accounts/{id}/balance          Phase 6 — forget it; forecasts become flow-only

POST   /documents/upload               multipart file (+ optional account_id)
GET    /documents
GET    /documents/{id}
PATCH  /documents/{id}                 {account_id}   — assign/reassign account
DELETE /documents/{id}
GET    /documents/{id}/pages           extracted pages (evidence view)
GET    /documents/{id}/download-url    presigned URL, 5 min expiry
POST   /documents/{id}/normalize       manually (re-)trigger Phase 3 normalization

GET    /transactions                   ?account_id&date_from&date_to&is_anomaly&is_recurring&limit&offset
GET    /transactions/{id}
PATCH  /transactions/{id}              {category_id | null}  — assign / clear (final: ML never overrides)
POST   /transactions/{id}/suggestion/accept | reject | undismiss   Phase 5 — act on a category suggestion
POST   /transactions/{id}/duplicate/confirm | dismiss    Phase 5 — act on a duplicate candidate

POST   /ml/run                         {force_reclassify?} duplicates→categories→recurring→anomalies (synchronous)
GET    /ml/status                      rules-only vs rules+ML, model metadata, thresholds
GET    /ml/suggestions                 pending category suggestions
GET    /ml/duplicates                  ?review=pending|auto|confirmed|dismissed
GET    /ml/recurring                   detected recurring series
GET    /ml/anomalies                   flagged transactions, most extreme first

POST   /categories                     {name, parent_id?}
GET    /categories                     system + your own

POST   /budgets                        {category_id?, currency, amount, alert_threshold_pct?}
GET    /budgets
PATCH  /budgets/{id}                   {amount?, alert_threshold_pct?, is_active?}
DELETE /budgets/{id}

# all analytics: read-only, per currency, filters ?date_from&date_to&account_id (dates inclusive)
GET    /analytics/summary              income / expense / net / savings rate
GET    /analytics/monthly              month-by-month series + change vs previous month
GET    /analytics/categories           ?type=debit|credit&limit
GET    /analytics/merchants            ?type=debit|credit&limit=10
GET    /analytics/accounts             per-account summary (idle accounts included)
GET    /analytics/budget-utilization   ?month=YYYY-MM  → limit/spent/remaining/pct/status per budget
GET    /analytics/recurring            monthly-equivalent recurring expense/income per currency (Phase 5)

# Phase 6: computed on demand, per currency, nothing stored
GET    /forecast/cashflow              ?horizon_months=1..12 (3)&interval_level=0.5..0.95 (0.8)&as_of&account_id

GET    /health                         real Postgres + Valkey connectivity check
```

All document/account/transaction/category/budget/analytics endpoints enforce per-user isolation
(404, not 403, on someone else's resource — no existence leak).

---

## Running it

```bash
cp .env.example .env
# fill in POSTGRES_PASSWORD, SECRET_KEY, ANTHROPIC_API_KEY, VOYAGE_API_KEY

docker compose up --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.ml.train   # Phase 5: train the classifier (seconds). Without it the
                                                     # system runs rules-only and says so at GET /ml/status
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000 (docs at `/docs`)
- Health check: http://localhost:8000/health

Money in API responses is a JSON **string** (`"1250.50"`), never a float.

A typical end-to-end flow once running:

```
POST /auth/signup → POST /auth/login
POST /accounts                                    # create an INR or USD account
POST /documents/upload?account_id=<id>             # upload a statement
                                                     # → extraction runs, then normalization
                                                     #   auto-chains right after it
GET  /transactions?account_id=<id>                  # see the normalized result
GET  /analytics/summary                             # income / expense / net per currency
GET  /analytics/monthly                             # month-by-month trend
POST /ml/run                                        # (also auto-runs after each upload) categorize / dedupe / recurring / anomalies
GET  /ml/suggestions                                # review what the classifier wasn't sure about
PATCH /transactions/{id} {"category_id": ...}       # or categorize by hand — always final
POST /budgets {"currency":"INR","amount":"10000"}   # overall monthly budget
GET  /analytics/budget-utilization?month=2026-08
PUT  /accounts/{id}/balance {"opening_balance":"54000","balance_as_of":"2026-08-31"}   # optional: enables balance projection
GET  /forecast/cashflow?horizon_months=3            # expected income / expense / net (+ balance, verdict) per currency
```

If a document is uploaded without `account_id`, normalization is
skipped (not failed) until you `PATCH /documents/{id}` to assign one and
call `POST /documents/{id}/normalize`.

---

## Limitations and known gaps

Full detail with rationale for each lives in `PROGRESS_TRACKER.md` §
Known Gaps; the load-bearing ones:

**Scope decisions (deliberate, not oversights):**
- **Dates: strict DD/MM/YYYY only.** No locale detection. A statement
  using MM/DD convention (common in raw US exports) will be silently
  misparsed unless the date is otherwise unambiguous (day >12, or a
  month name).
- **Currencies: INR and USD only.** Any other account currency causes
  normalization to be skipped with a clear status/error, not a crash —
  but the amount parser also hardcodes the shared comma-thousands/
  dot-decimal convention both currencies use, so adding a comma-decimal
  currency (EUR-style) needs real parser rework, not a config flag.
- **Analytics never convert currency** (Phase 4 decision): every total is
  per currency, and there's no "everything combined" number for a user
  holding both INR and USD accounts.
- Budgets are calendar-monthly only (no weekly/yearly/rollover/forecast).

**Heuristic limitations (real, not yet hardened):**
- A single "Amount" column with no sign, no Cr/Dr suffix, and no
  separate Debit/Credit columns defaults to `debit` (flagged with lower
  confidence, not silently certain — `transaction_type` has no "unknown"
  value in the schema).
- Merchant text cleaning is hand-written regex covering common
  prefixes/suffixes (POS/ACH/UPI/NEFT tags, reference numbers) — will
  miss variants it doesn't recognize.
- Column detection (header keywords → reuse previous page's mapping →
  positional inference) fails closed: a table it can't classify by any
  tier is skipped with a warning, not guessed at further.
- `confidence_score` is a hand-weighted heuristic (column-detection
  source, date-parse method, amount-sign certainty, merchant-match tier,
  OCR quality) — not calibrated against any labeled dataset.

**Phase 4 analytics caveats** (full list with reasoning in
[`backend/README.md`](./backend/README.md)):
- **Transfers count as income/expense.** Credit-card bill payments and moves
  between your own accounts are not detected, so they inflate both sides.
- **Refunds aren't netted** against category spend or budgets.
- Analytics trust Phase 3's debit/credit call and ignore `confidence_score` —
  a low-confidence row is summed like any other.
- Category breakdown is direct-assignment only; budgets roll up descendants.
- Recurring expense totals now exist (`/analytics/recurring`) but are only as good as the detector (see Phase 5).
- Computed live per request, no caching. Measured ≈46 ms all-time summary for
  one user with 104k rows on Postgres 16 in the dev sandbox; not benchmarked
  on PG18 or under concurrent load.
- Categories can't be renamed/moved/deleted via the API.

**Infrastructure / pre-existing:**
- Object storage (SeaweedFS) still has no encryption-at-rest configured.
- No Row-Level Security at the DB level — isolation is enforced only in
  application code via `user_id` filters.
- No refresh tokens, logout/revocation, or rate limiting on `/login`.
- Accounts API is intentionally minimal (create + list, plus the Phase 6 balance set/clear; no
  rename/update/delete) — this gap actually predates Phase 3 (the `Account`
  model existed since Phase 0/1 with zero API surface) and was only
  patched enough to unblock Phase 3's account-assignment flow.
- `POST /documents/{id}/normalize` runs synchronously in the request
  thread rather than being queued via Celery — fine at current scale,
  inconsistent with `process_document`'s async pattern if this ever
  needs to handle bulk re-normalization.

---

## Phase 5: ML layer — what it does, and how far to trust it

**What each piece is**

| Component | Method | Learned? |
|---|---|---|
| Classification | Ordered regex rules → TF-IDF (char + word n-grams) + logistic regression → hybrid policy | rules no, ML yes (synthetic data only) |
| Duplicates | Hand-weighted score: date proximity, narration similarity, cross-document, bank reference numbers | no |
| Recurring | Interval/cadence regularity + amount-band test per merchant | no |
| Anomalies | Robust z-score (median/MAD) on log-amount, merchant → category → user-wide baseline | no |

**What it is allowed to change on its own.** Rule-backed (or rule+ML-agreeing)
categories are auto-applied. ML-only predictions are *never* auto-applied — they
become suggestions you accept or reject. A category you set is final: no ML job,
including a forced re-run, overwrites it. Duplicates are auto-applied only when
the same payment appears on the same date in two *different* documents with the same
bank reference (analytics then exclude the later row); everything weaker waits in a
review queue (`GET /ml/duplicates`). Nothing is ever deleted. Anomalies are flags
for you to look at, not fraud verdicts.

**Measured results** (full tables: [`backend/docs/ml_eval/report.md`](./backend/docs/ml_eval/report.md)).
All data is **synthetic and written by the same author as the models**, so treat the numbers as
a comparison between methods, not as a forecast of real-world accuracy.

| | Result |
|---|---|
| Classification, **unseen merchants** (5-fold CV grouped by merchant) | Rules 82% accuracy (abstaining counts as wrong; 99% precise when they answer, 83% coverage) · ML alone **42%** · Hybrid 86% |
| Classification, **seen merchants** | ML 99.7% — this mostly shows the model memorises its ~240 training merchants |
| ML-only predictions on unseen merchants | **30% precise**, and confidence is *anti*-calibrated (≥0.9 confidence → 17% precise). Hence: never auto-applied |
| Recurring | series precision 1.00 / recall 0.97 on 20 synthetic users; missed: monthly bills whose date wanders more than ±4.5 days month to month |
| Duplicates | P/R 1.00 on synthetic re-uploads (exact copies — real exports differ more); 0 flags on hard negatives (daily fare, two identical chais with different refs). Auto-apply recall only 0.59 by design |
| Anomalies | at threshold 3.5: precision 0.89, recall 0.36 overall — 0.55 on "severe" injections, 0.13 on "moderate" ones. PR-AUC: robust-z 0.63 ≈ IQR 0.64 ≫ Isolation Forest 0.36 |
| LLM (Gemini 3.5 Flash-Lite, n=300) | 94.3% accuracy vs 91.3% for hybrid on the same synthetic holdout; 0 abstentions (fixed confidence, not calibration). Separate protocol, not this 5-fold CV. Synthetic data flatters all methods — see caveats |
| Public OOD (12,144 mapped of 20,000 requested) | 60.7% of requested rows mapped; 48.9% answer coverage on mapped rows, 48.6% precision on answered, 23.8% accuracy if abstentions count wrong. Lossy label map; not a benchmark |
| Cost at scale | 100k transactions for one user: duplicates 3 s, classify 77 s, recurring 3 s, anomalies 41 s; ~0.8 GB peak RSS (Postgres 16, no concurrency) |

**What the ML classifier actually tells you.** It is a lookup of merchant names it has
seen, with some tolerance for typos and truncation. On a merchant it never saw it is
mostly guessing. The honest fixes are real or user-corrected labels (not yet built) and/or
an LLM's world knowledge (the Gemini path is now verified against the real API; the
Anthropic path remains unverified because no Anthropic key was available).

**Not done / not verified (Phase 5)**
- **Anthropic path unverified.** The Gemini adapter (`gemini-3.5-flash-lite`) was run against the real API and completed n=300; the Anthropic model id in settings is still a guess because no Anthropic key was available. Neither is wired into the pipeline; `LLM_CLASSIFIER_ENABLED` currently only controls the `/ml/status` report, and the eval script calls the provider directly.
- **Free-tier LLM quota is 20 requests per model per day.** n=300 uses 12 requests; `gemini-2.5-flash` is closed to new keys, and 3.5/3.8 Flash returned 503s during the eval (hence Flash-Lite).
- **Public OOD is a signal, not a benchmark.** The dataset's categories do not match this project's ten, so rows without a counterpart were dropped and the remaining label map is lossy. Its MIT label does not settle where the underlying rows came from.
- **No feedback loop.** Your corrections are stored (`category_source='user'`) but nothing retrains on them yet — this is the highest-value next step for the classifier.
- Rules were written by the same person as the test merchants — expect lower precision on real statements.
- Anomaly detection can only flag *unusually large* amounts, needs history (≥8 txns for the merchant, ≥15 for the category, or ≥30 user-wide, per currency and direction), and cannot see a charge ≤2.2× a perfectly flat baseline (e.g. rent 22,000 → 40,000 is not flagged).
- Recurring: daily cadence not modeled; a price change is absorbed into one series (typical amount = latest); a series is "inactive" once it is silent for 1.5 intervals *relative to your newest transaction*, not today's date.
- Duplicate score weights are hand-set, not learned; transfers between your own accounts and credit-card bill payments are still not detected (Phase 4 gap persists).
- Model file is a pickle (trusted-write-only directory; sha256 sidecar detects corruption, not tampering). Not baked into the Docker image — run `python -m app.ml.train` (the bind-mounted `backend/models/` is shared by backend and worker).
- `POST /ml/run` is synchronous (≈2 min at 100k rows).
- *(Fixed pre-Phase 6: the lockfile is now UTF-8, generated inside the Linux image, includes scikit-learn, and the Docker build has been exercised.)*
- Phase 3 merchant cleaning leaves bank codes in some NEFT merchants (e.g. "Hdfc0001234-Infosys Ltd-Salary"); harmless to detection here but ugly.

---

## Phase 6: Forecasting — what it does, and how far to trust it

Full design, exact definitions and the evaluation: [`backend/app/forecast/README.md`](./backend/app/forecast/README.md).

**What you get.** `GET /forecast/cashflow` returns, per currency, expected income, expense and net for the rest of the
current month and the next 1–12 months, each split into *recurring* (named payments on specific dates, from Phase 5's
detector) and *variable* (everything else, forecast statistically). If you gave every account in that currency a starting
balance (`PUT /accounts/{id}/balance`) it also projects the end-of-month balance with an interval and a verdict —
`covered`, `at_risk` (the interval's low end goes negative) or `shortfall` (the point forecast does) — and says `unknown`
instead of guessing when it can't support one. Every response lists its assumptions, warnings, and the backtest leaderboard of the
models it tried.

**How the variable part is chosen.** Nine simple methods (last month, 3/6-month averages, 12-month median, drift, same-month-last-year,
and three exponential-smoothing variants) compete in a rolling-origin backtest on *your own* history; the best — ties within 2 % go to the
simplest — is refit and used. With fewer than 7 usable months it falls back to the last-3-month average and gives **no interval**;
with fewer than 3 it makes no variable forecast at all.

**Measured results** (synthetic, same-author data; 600 series; [`backend/docs/forecast_eval/report.md`](./backend/docs/forecast_eval/report.md)):

| | Result |
|---|---|
| Selector vs naive baselines | Clearly better than "repeat last month" (−0.097 MASE, 95 % CI [−0.152, −0.041]) and than a 3-month average or 12-month median |
| Selector vs **always level-ETS** | **A tie** (+0.010, CI [−0.030, +0.052]; −0.048 [−0.102, +0.004] on a second corpus). The selection machinery protects against bad fixed choices; it does not beat the best single simple model here |
| ML benchmark | A pooled gradient-boosting model (**eval-only, never used for real users**) trained on other synthetic series did **not** beat the shipped pipeline (+0.029, CI [−0.023, +0.078]) even though it was favoured by in-distribution training. Per-user ML is not viable at 3–36 monthly points, and a pooled model would mean training on other people's financial data |
| Interval coverage (nominal 80 %) | 83.0 / 81.8 / 79.5 % at steps 1 / 2 / 3 on single-series intervals; 77.5 % at 48 months of history |
| Latency | ≈1 ms at 12 months of history, ≈120 ms at 24, ≈390 ms at 48, per series (two per currency), computed on every request |

**What to be careful about**
- **Everything is conditional on the data and the balance you typed.** Nothing checks your starting balance against a statement.
- **Transfers and card-bill payments are counted as income/expense** (Phase 4/5 gap), which can badly distort a forecast.
- **Only month-end balances exist**; a bill early in the month can overdraw an account that ends the month positive.
- **The combined net/balance intervals assume independent errors and are not validated.** Only single-series intervals were checked, on synthetic data.
- A user whose last transaction is not on the last day of its month loses that month from the history (it is treated as partial).
- Seasonality can't be learned from fewer than ~20 months (simple) or ~44 months (ETS); annual bills appear only if caught as a yearly recurring series.
- No scenario inputs, no budget projection (Phase 9), forecasts are not stored (so there is no record of how past forecasts fared).

---

## Testing approach

Every phase is tested against real infrastructure — real Postgres, real
SeaweedFS, a real Celery worker on a real broker, real HTTP requests —
never mocks. From Phase 4 on, the Postgres-backed tests are a committed
pytest suite (`backend/tests/`, 264 tests; run instructions in
`backend/README.md`) rather than throwaway scripts; earlier phases'
SeaweedFS / Celery / OCR checks were run ad hoc and are *not* part of that
suite. Where the sandbox used for development lacks a service
(e.g. Postgres 18 or Docker itself), a close real substitute is used
(Postgres 16, `uuidv7()` polyfilled locally — in the suite, only inside
`tests/conftest.py` against a `*_test` database) and explicitly never
touches shipped migration files — verified via `git diff` before every
delivery. Full test narrative per phase, including two real bugs caught
this way (an empty-`str(exception)` edge case in Phase 2, a
substring-matching bug that misclassified table columns in Phase 3), is
in `PROGRESS_TRACKER.md`.

---

## Next up

**Phase 7 — RAG**: Voyage embeddings into pgvector (the extension has been enabled since Phase 0 and is still unused),
then hybrid SQL + semantic retrieval. Worth doing first, because they make the next phases' numbers more trustworthy: (1) run the
forecast on real statements instead of synthetic series, (2) the Phase 5 follow-ups (retraining on user corrections; the Anthropic
LLM path), (3) transfer / card-payment detection, which currently distorts both analytics and forecasts.
