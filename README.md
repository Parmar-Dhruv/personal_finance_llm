# FinSight

An agentic financial intelligence platform. Uploaded bank/credit-card
statements, receipts, and spreadsheets go through document extraction →
data normalization → (eventually) analytics, RAG, and agentic
natural-language Q&A, with every answer traceable back to a source
document and page.

**Status: Phases 0–5 of 13 complete.** This README describes what's
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
| 6–13 | ⬜ | Forecasting, RAG, agentic Q&A, product features, evaluation, security hardening, frontend, deployment |

A document today flows: **upload → object storage → OCR/table
extraction (Celery) → date/amount/merchant normalization (Celery,
auto-chained) → queryable `Transaction` rows → deterministic analytics and
budget utilization via API → (Celery, auto-chained) duplicate / category /
recurring / anomaly enrichment.** There is no forecasting and no LLM call
in the running system (an LLM classifier exists, is off by default, and was
run only for evaluation; see Phase 5 caveats). Categories are assigned by
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
understanding (later phases). Phases 0–5 contain zero LLM calls in the running system.

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
│   ├── tests/                             # 151 real-Postgres tests (Phase 4: 60; Phase 5: 87; pre-Phase 6 hardening: 4)
│   ├── alembic/
│   │   └── versions/
│   │       ├── 0001_initial_schema.py     # users, accounts, categories, documents, transactions
│   │       ├── 0002_document_pages.py     # DocumentPage + provenance fields (Phase 2)
│   │       ├── 0003_normalization.py      # normalization_status fields, merchant_aliases + seed data (Phase 3)
│   │       ├── 0004_analytics_budgets.py  # budgets, category uniqueness fix, 10 system categories (Phase 4)
│   │       ├── 0005_ml_layer.py           # recurring_series, category/duplicate/anomaly provenance columns + indexes (Phase 5)
│   │       └── 0006_merchant_alias_uniqueness.py  # MerchantAlias NULLS NOT DISTINCT scope fix
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
│       │   └── ml.py                      # Phase 5
│       ├── api/                           # FastAPI routers
│       │   ├── auth.py                    # /auth/signup, /auth/login, /auth/me
│       │   ├── accounts.py                # /accounts (create, list)
│       │   ├── documents.py               # /documents (upload, list, get, patch, delete, pages, normalize)
│       │   ├── transactions.py            # /transactions (list, get, patch category; Phase 5: suggestion + duplicate review actions)
│       │   ├── categories.py              # /categories (create, list) — Phase 4
│       │   ├── budgets.py                 # /budgets (CRUD) — Phase 4
│       │   ├── analytics.py               # /analytics/* (read-only) — Phase 4 (+ /analytics/recurring, Phase 5)
│       │   ├── ml.py                      # /ml/* run, status, suggestions, duplicates, recurring, anomalies — Phase 5
│       │   └── deps.py                    # get_current_user, get_db, ownership helpers
│       ├── analytics/                     # Phase 4 — deterministic analytics (no FastAPI imports)
│       │   ├── common.py                  # Scope, shared filters, money/percent/month helpers
│       │   ├── cashflow.py                # summary(), monthly()
│       │   ├── breakdowns.py              # by_category(), by_merchant(), by_account()
│       │   ├── budgets.py                 # utilization(), category subtree roll-up
│       │   └── recurring.py               # recurring monthly-equivalent totals (Phase 5)
│       ├── ml/                            # Phase 5 — see "Phase 5: ML layer" below
│       │   ├── taxonomy.py                # the 10 labels + credit-only constraint
│       │   ├── rules.py                   # ordered regex rule classifier (baseline)
│       │   ├── classifier.py              # TF-IDF + LogReg, hybrid policy, model persistence
│       │   ├── duplicates.py  recurring.py  anomalies.py   # pure detectors, no DB
│       │   ├── service.py                 # the only DB-touching module; per-user advisory lock
│       │   ├── synthetic.py               # synthetic labeled data + user histories
│       │   ├── eval.py  train.py          # evaluation harness; model training CLI
│       │   ├── llm_classifier.py          # UNVERIFIED interface (no API key was available)
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

## Data model (as of Phase 5)

- **User** — auth identity
- **Account** — a bank/card account a user owns; `currency` (ISO code),
  `account_type`. Every `Transaction` belongs to exactly one account
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
- Accounts API is intentionally minimal (create + list only, no
  update/delete) — this gap actually predates Phase 3 (the `Account`
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
| LLM (Gemini 3.5 Flash-Lite, n=300) | 94.3% accuracy vs 91.3% for hybrid on the same synthetic holdout; 0 abstentions. Synthetic data flatters all methods — see caveats |
| Public OOD (12,144 mapped rows) | 48.9% coverage, 48.6% precision on answered, 23.8% accuracy if abstentions count wrong. Lossy label map; not a benchmark |
| Cost at scale | 100k transactions for one user: duplicates 3 s, classify 77 s, recurring 3 s, anomalies 41 s; ~0.8 GB peak RSS (Postgres 16, no concurrency) |

**What the ML classifier actually tells you.** It is a lookup of merchant names it has
seen, with some tolerance for typos and truncation. On a merchant it never saw it is
mostly guessing. The honest fixes are real or user-corrected labels (not yet built) and/or
an LLM's world knowledge (the Gemini path is now verified against the real API; the
Anthropic path remains unverified because no Anthropic key was available).

**Not done / not verified (Phase 5)**
- **Anthropic path unverified.** The Gemini adapter (`gemini-3.5-flash-lite`) was run against the real API and completed n=300; the Anthropic model id in settings is still a guess because no Anthropic key was available. Both remain off by default (`LLM_CLASSIFIER_ENABLED=false`); enabling sends narrations to the selected provider.
- **Free-tier LLM quota is 20 requests per model per day.** n=300 uses 12 requests; `gemini-2.5-flash` is closed to new keys, and 3.5/3.8 Flash returned 503s during the eval (hence Flash-Lite).
- **Public OOD is a signal, not a benchmark.** The dataset's categories do not match this project's ten, so rows without a counterpart were dropped and the remaining label map is lossy. Its MIT label does not settle where the underlying rows came from.
- **No feedback loop.** Your corrections are stored (`category_source='user'`) but nothing retrains on them yet — this is the highest-value next step for the classifier.
- Rules were written by the same person as the test merchants — expect lower precision on real statements.
- Anomaly detection can only flag *unusually large* amounts, needs history (≥8 txns for the merchant, ≥15 for the category, or ≥30 user-wide, per currency and direction), and cannot see a charge ≤2.2× a perfectly flat baseline (e.g. rent 22,000 → 40,000 is not flagged).
- Recurring: daily cadence not modeled; a price change is absorbed into one series (typical amount = latest); a series is "inactive" once it is silent for 1.5 intervals *relative to your newest transaction*, not today's date.
- Duplicate score weights are hand-set, not learned; transfers between your own accounts and credit-card bill payments are still not detected (Phase 4 gap persists).
- Model file is a pickle (trusted-write-only directory; sha256 sidecar detects corruption, not tampering). Not baked into the Docker image — run `python -m app.ml.train`; Docker build was not exercised.
- `POST /ml/run` is synchronous (≈2 min at 100k rows). `requirements.lock.txt` is UTF-16 (pre-existing) and does not yet list scikit-learn; regenerate it with `pip freeze`.
- Phase 3 merchant cleaning leaves bank codes in some NEFT merchants (e.g. "Hdfc0001234-Infosys Ltd-Salary"); harmless to detection here but ugly.

---

## Testing approach

Every phase is tested against real infrastructure — real Postgres, real
SeaweedFS, a real Celery worker on a real broker, real HTTP requests —
never mocks. From Phase 4 on, the Postgres-backed tests are a committed
pytest suite (`backend/tests/`, 151 tests; run instructions in
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

**Phase 6 — Forecasting**: a baseline statistical cash-flow forecast first, then an ML forecast
benchmarked against it. It can use Phase 5's recurring series for the known obligations. Before it,
consider the Phase 5 follow-ups above (retraining on user corrections; running the LLM and
public-dataset checks with a key / network access).
