# FinSight

An agentic financial intelligence platform. Uploaded bank/credit-card
statements, receipts, and spreadsheets go through document extraction →
data normalization → (eventually) analytics, RAG, and agentic
natural-language Q&A, with every answer traceable back to a source
document and page.

**Status: Phases 0–4 of 13 complete.** This README describes what's
actually built and running today, not the end-state design — for the
full 13-phase target architecture and design rationale, see
[`personal_finance_llm.md`](./personal_finance_llm.md). For the
phase-by-phase build history, decisions, and open gaps in full detail,
see [`PROGRESS_TRACKER.md`](./PROGRESS_TRACKER.md) — this README is a
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
| 5 — ML layer | ⬜ next | Transaction classification, duplicate / recurring / anomaly detection |
| 6–13 | ⬜ | Forecasting, RAG, agentic Q&A, product features, evaluation, security hardening, frontend, deployment |

A document today flows: **upload → object storage → OCR/table
extraction (Celery) → date/amount/merchant normalization (Celery,
auto-chained) → queryable `Transaction` rows → deterministic analytics and
budget utilization via API.** There is no automatic categorization (Phase 5),
no forecasting, and no LLM calls anywhere (by design; see
`personal_finance_llm.md` §17 on the deterministic/ML/LLM separation
principle). Categories can currently only be assigned by hand.

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
      ├──► Postgres 18 + pgvector  (users, accounts, documents, document_pages,
      │                             transactions, merchant_aliases, categories, budgets)
      ├──► SeaweedFS (S3-compatible object storage — original documents)
      └──► Valkey  ──► Celery workers
                          │
                          ├─ process_document     (Phase 2: OCR / table extraction)
                          └─ normalize_document    (Phase 3: dates/amounts/merchants
                                                     → Transaction rows)
                             auto-chained after process_document succeeds
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
understanding (later phases). Phases 0–4 contain zero LLM calls.

---

## Folder structure

```
personal_finance_llm/
├── personal_finance_llm.md   # Full 13-phase project spec / design doc
├── BUILD_LOOP.md              # The research→implement→test→track→deliver loop this project follows
├── PROGRESS_TRACKER.md        # Full decision log, known gaps, session-by-session history
├── docker-compose.yml         # db (Postgres+pgvector), cache (Valkey), seaweedfs, backend, worker, frontend
├── .env.example
│
├── backend/
│   ├── README.md                          # backend deep-dive: analytics definitions, testing, Phase 4 gaps
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements-dev.txt               # pytest + httpx
│   ├── pytest.ini
│   ├── tests/                             # 60 real-Postgres tests (analytics, budgets, categories, migrations, pipeline seam)
│   ├── alembic/
│   │   └── versions/
│   │       ├── 0001_initial_schema.py     # users, accounts, categories, documents, transactions
│   │       ├── 0002_document_pages.py     # DocumentPage + provenance fields (Phase 2)
│   │       ├── 0003_normalization.py      # normalization_status fields, merchant_aliases + seed data (Phase 3)
│   │       └── 0004_analytics_budgets.py  # budgets, category uniqueness fix, 10 system categories (Phase 4)
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
│       │   └── analytics.py               # Phase 4
│       ├── api/                           # FastAPI routers
│       │   ├── auth.py                    # /auth/signup, /auth/login, /auth/me
│       │   ├── accounts.py                # /accounts (create, list)
│       │   ├── documents.py               # /documents (upload, list, get, patch, delete, pages, normalize)
│       │   ├── transactions.py            # /transactions (list, get, patch category)
│       │   ├── categories.py              # /categories (create, list) — Phase 4
│       │   ├── budgets.py                 # /budgets (CRUD) — Phase 4
│       │   ├── analytics.py               # /analytics/* (read-only) — Phase 4
│       │   └── deps.py                    # get_current_user, get_db, ownership helpers
│       ├── analytics/                     # Phase 4 — deterministic analytics (no FastAPI imports)
│       │   ├── common.py                  # Scope, shared filters, money/percent/month helpers
│       │   ├── cashflow.py                # summary(), monthly()
│       │   ├── breakdowns.py              # by_category(), by_merchant(), by_account()
│       │   └── budgets.py                 # utilization(), category subtree roll-up
│       └── pipeline/
│           ├── tasks.py                   # Celery tasks: process_document, normalize_document
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

## Data model (as of Phase 4)

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
  deep. `Transaction.category_id` is set manually via the API today;
  Phase 5's classifier will write the same column
- **Budget** (Phase 4) — a monthly limit for one `(category | overall,
  currency)`: `amount`, `alert_threshold_pct`, `is_active`. At most one
  per `(user, category, currency)`, enforced by the database

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

GET    /transactions                   ?account_id&date_from&date_to&limit&offset
GET    /transactions/{id}
PATCH  /transactions/{id}              {category_id | null}  — assign / clear category

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
PATCH /transactions/{id} {"category_id": ...}       # categorize by hand (Phase 5 will automate)
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
- No automatic transaction categorization — Phase 5. Until then category
  summaries are mostly "Uncategorized" unless you assign categories by hand.

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
- No "recurring expense totals" yet — depends on Phase 5 recurring detection.
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

## Testing approach

Every phase is tested against real infrastructure — real Postgres, real
SeaweedFS, a real Celery worker on a real broker, real HTTP requests —
never mocks. From Phase 4 on, the Postgres-backed tests are a committed
pytest suite (`backend/tests/`, 60 tests; run instructions in
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

**Phase 5 — ML layer**: transaction classification (rule-based baseline →
classical ML → LLM/hybrid, compared on accuracy/cost/latency), duplicate
detection (writes `Transaction.duplicate_of_id`, which analytics already
exclude), recurring-payment detection (unlocks the missing "recurring
totals"), and anomaly detection. It needs labeled data to evaluate
against, which the project doesn't have yet — expect that to be the first
real decision of the phase.
