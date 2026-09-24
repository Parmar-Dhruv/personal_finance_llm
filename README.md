# FinSight

An agentic financial intelligence platform. Uploaded bank/credit-card
statements, receipts, and spreadsheets go through document extraction →
data normalization → (eventually) analytics, RAG, and agentic
natural-language Q&A, with every answer traceable back to a source
document and page.

**Status: Phases 0–3 of 13 complete.** This README describes what's
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
| 4 — Financial analytics | ⬜ next | Deterministic income/expense/cash-flow calculations |
| 5–13 | ⬜ | ML classification, anomaly detection, forecasting, RAG, agentic Q&A, reporting, evaluation, deployment |

A document today flows: **upload → object storage → OCR/table
extraction (Celery) → date/amount/merchant normalization (Celery,
auto-chained) → queryable `Transaction` rows via API.** Nothing past
that point exists yet — no categorization, no analytics, no LLM calls
anywhere in the pipeline (by design; see `personal_finance_llm.md` §17
on the deterministic/ML/LLM separation principle).

---

## Architecture

```
Frontend (Next.js)
      │
      ▼
Backend API (FastAPI)
      │
      ├──► Postgres 18 + pgvector  (users, accounts, documents, document_pages,
      │                             transactions, merchant_aliases, categories)
      ├──► SeaweedFS (S3-compatible object storage — original documents)
      └──► Valkey  ──► Celery workers
                          │
                          ├─ process_document     (Phase 2: OCR / table extraction)
                          └─ normalize_document    (Phase 3: dates/amounts/merchants
                                                     → Transaction rows)
                             auto-chained after process_document succeeds
```

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
understanding (later phases). Phases 0–3 contain zero LLM calls.

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
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/
│   │   └── versions/
│   │       ├── 0001_initial_schema.py     # users, accounts, categories, documents, transactions
│   │       ├── 0002_document_pages.py     # DocumentPage + provenance fields (Phase 2)
│   │       └── 0003_normalization.py      # normalization_status fields, merchant_aliases + seed data (Phase 3)
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
│       │   └── transaction.py
│       ├── api/                           # FastAPI routers
│       │   ├── auth.py                    # /auth/signup, /auth/login, /auth/me
│       │   ├── accounts.py                # /accounts (create, list)
│       │   ├── documents.py               # /documents (upload, list, get, patch, delete, pages, normalize)
│       │   ├── transactions.py            # /transactions (list, get)
│       │   └── deps.py                    # get_current_user, get_db
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

## Data model (as of Phase 3)

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
- **Category** — exists in the schema (Phase 1), not yet populated by
  anything — classification is Phase 5

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

GET    /health                         real Postgres + Valkey connectivity check
```

All document/account/transaction endpoints enforce per-user isolation
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

A typical end-to-end flow once running:

```
POST /auth/signup → POST /auth/login
POST /accounts                                    # create an INR or USD account
POST /documents/upload?account_id=<id>             # upload a statement
                                                     # → extraction runs, then normalization
                                                     #   auto-chains right after it
GET  /transactions?account_id=<id>                  # see the normalized result
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
- No transaction categorization yet (`Category` is unused) — that's
  Phase 5.

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
never mocks. Where the sandbox used for development lacks a service
(e.g. Postgres 18 or Docker itself), a close real substitute is used
(Postgres 16, `uuidv7()` polyfilled locally) and explicitly never
touches shipped migration files — verified via `git diff` before every
delivery. Full test narrative per phase, including two real bugs caught
this way (an empty-`str(exception)` edge case in Phase 2, a
substring-matching bug that misclassified table columns in Phase 3), is
in `PROGRESS_TRACKER.md`.

---

## Next up

**Phase 4 — deterministic financial analytics**: income/expense/net
cash-flow calculations, category and vendor spending summaries, monthly
comparisons, budget utilization — all as deterministic SQL/Python over
the now-populated `Transaction` table, no ML or LLM involved (that
separation is the point — see `personal_finance_llm.md` §8 and §17).
