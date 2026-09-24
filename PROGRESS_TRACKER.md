# FinSight — Progress Tracker

> Paste this whole file at the start of every new session so context carries
> forward. Update it at the end of each session before ending the chat.

---

## 1. Project Identity

**FinSight** — a personal portfolio project: an agentic financial
intelligence platform. Modular monolith.

**Stack:**
- Backend: FastAPI + Celery
- Frontend: Next.js (App Router, TypeScript)
- DB: PostgreSQL 18 + pgvector
- Cache/broker: Valkey 8 (RESP-compatible Redis successor)
- Object storage: SeaweedFS (S3 gateway)
- AI: Anthropic Claude (Messages API), Voyage AI embeddings (`voyage-context-4`)
- Auth: `pwdlib[argon2]` + `PyJWT`

**Repo layout:**
```
finsight/
  docker-compose.yml
  .env.example
  README.md
  seaweedfs/s3-config.json
  backend/
    Dockerfile, requirements.txt, alembic.ini
    alembic/ (env.py, versions/)
    app/
      main.py
      core/ (config.py, security.py, storage.py, celery_app.py)
      db/ (base.py, models.py)
      schemas/ (auth.py, document.py, account.py, transaction.py)
      api/ (auth.py, documents.py, accounts.py, transactions.py, deps.py)
      pipeline/
        tasks.py
        extractors/ (common.py, ocr.py, pdf.py, image.py, spreadsheet.py)
        normalize/ (dates.py, amounts.py, merchants.py, columns.py, engine.py)
  frontend/
    package.json, tsconfig.json, next.config.mjs, Dockerfile
    app/ (layout.tsx, page.tsx)
```

---

## 2. Build Principles (established conventions — don't relitigate these)

1. **Build order follows dependencies, not the spec document's section
   order.** The master spec (`finsight.md`) describes functional taxonomy;
   actual build sequence is foundation-first (see Phase Roadmap below).
2. **Nothing ships on "looks right."** Every phase gets validated against
   real infrastructure before being called done — real Postgres, real
   running service binaries/containers, real HTTP requests via TestClient,
   not just syntax checks or assumed correctness. If sandbox limitations
   force a substitution (e.g., PG16 instead of PG18 for local testing),
   the substitution is made, tested, then explicitly reverted, and the
   restored file is re-verified.
3. **Never trust training-data knowledge on library/tool currency — search
   first.** This project has already caught two stale defaults this way:
   `passlib` (unmaintained, broken on bcrypt≥5.0) → `pwdlib`; MinIO
   (Docker images discontinued Oct 2025, archived Apr 2026) → SeaweedFS.
   Also `python-jose` → `PyJWT` (staleness, not brokenness).
4. **Edge cases are produced after every phase**, grounded in web search
   where currency/accuracy matters, not just recalled from memory.
5. **Architecture/pipeline explanations are given only when load-bearing**
   for a decision — not by default, not as filler.
6. **Every infra choice with real trade-offs (Valkey vs Redis, SeaweedFS
   vs Garage vs local disk) is surfaced to Dhruv with the actual trade-offs
   and decided by him, not silently defaulted.**
7. **Deliverables are packaged as a zip of the real working repo** (not
   pasted code blocks) after each meaningful chunk of work, via
   `present_files`.

---

## 3. Phase Roadmap

Dependency-ordered build sequence (not spec §-order). ✅ = done and
verified. 🔶 = in progress. ⬜ = not started.

- **Phase 0 — Foundations** ✅
  - ✅ Repo scaffold (FastAPI, Next.js, Celery, Docker Compose)
  - ✅ Postgres 18 + pgvector, Valkey 8 containers
  - ✅ Config/secrets management (`pydantic-settings`)
  - ✅ SQLAlchemy models: `User`, `Account`, `Category`, `Document`, `Transaction`
  - ✅ First Alembic migration (tested: upgrade + downgrade, real ORM round-trip)
  - ✅ Auth: signup/login, Argon2id hashing, JWT issuance, `get_current_user`
- **Phase 1 — Ingestion** ✅
  - ✅ Object storage decision: SeaweedFS (MinIO ruled out — discontinued;
       Garage ruled out — AGPL + no versioning/lifecycle policies, built
       for geo-distribution not single-node use)
  - ✅ Upload endpoint (`POST /documents/upload`) with MIME/size validation
  - ✅ `Document` record + storage key scheme (`{user_id}/{document_id}/{filename}`)
  - ✅ Celery pipeline skeleton (`process_document` stub task — flips
       `uploaded → processing → processed`, no real extraction yet)
  - ✅ Download endpoints (list, get, presigned URL, delete)
- **Phase 2 — Document Intelligence** ✅
  - ✅ Text/table extraction for native PDFs/CSV/XLSX
  - ✅ OCR for scanned docs (Tesseract 5.x baseline, via pypdfium2 rasterization)
  - ✅ Field identification + confidence scoring (page-level OCR confidence;
       column-level field ID deferred to Phase 3 normalization)
  - ✅ Provenance linking (doc → page; region/bbox-level deferred — see
       Known Gaps)
- **Phase 3 — Normalization** ✅
  - ✅ Date/amount/currency normalization (strict DD/MM/YYYY; INR/USD only)
  - ✅ Merchant canonicalization (alias table + rapidfuzz self-clustering)
  - ✅ Normalized transaction schema populated end-to-end (DB → Celery
       chain → API, verified via real Postgres + real Redis/Celery worker
       + real HTTP requests)
- **Phase 4 — Deterministic Analytics** ⬜
  - ⬜ Income/expense/cash-flow calculations
  - ⬜ Category/vendor/account summaries
  - ⬜ Budget utilization math
- **Phase 5 — ML Layer** ⬜
  - ⬜ Transaction classification (rule-based baseline → ML/LLM comparison)
  - ⬜ Duplicate detection (uses `Transaction.duplicate_of_id`, already in schema)
  - ⬜ Recurring payment detection
  - ⬜ Anomaly detection
- **Phase 6 — Forecasting** ⬜
  - ⬜ Baseline statistical forecast, then ML forecast benchmarked against it
- **Phase 7 — RAG** ⬜
  - ⬜ Voyage `voyage-context-4` embedding pipeline into pgvector
    (extension already enabled in Phase 0 migration, unused until now)
  - ⬜ Hybrid retrieval: SQL + semantic + reranking
- **Phase 8 — Agentic Layer** ⬜
  - ⬜ Tool wrappers around analytics/ML/retrieval functions
  - ⬜ Hand-rolled agent loop over Messages API
  - ⬜ Evidence assembly (uses `Transaction.source_document_id` provenance chain)
- **Phase 9 — Product Features** ⬜
  - ⬜ Query router (structured SQL vs RAG vs agent)
  - ⬜ Monthly report generation
  - ⬜ Budget alerts
- **Phase 10 — Evaluation & Observability** ⬜
  - ⬜ Per-component eval harness
  - ⬜ Logs/metrics/traces
- **Phase 11 — Security Hardening** ⬜
  - ⬜ Prompt-injection guards, SQL-injection protection, restricted tool access
  - ⬜ Encryption, audit logging, retention/deletion policy
  - ⬜ Rate limiting on `/auth/login` (flagged as a known gap since Phase 0)
  - ⬜ Postgres Row-Level Security policies (isolation currently
       application-code-only via `user_id` filters)
- **Phase 12 — Frontend** ⬜
  - ⬜ Upload UI, dashboards, chat interface, evidence viewer
- **Phase 13 — Deployment** ⬜
  - ⬜ Dockerize for a real target, pick cloud provider

---

## 4. Decisions Log

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| Cache/broker | Valkey 8 | Redis | Open-source successor, RESP-compatible, `redis-py` works unmodified |
| Object storage | SeaweedFS | MinIO, Garage, local disk | MinIO: Docker images discontinued Oct 2025, project archived Apr 2026. Garage: AGPL, built for geo-distribution (irrelevant here), no bucket versioning/lifecycle policies. SeaweedFS: Apache 2.0, mature, active, better S3 API coverage |
| Password hashing | `pwdlib[argon2]` | `passlib` | `passlib` unmaintained since 2020, broken on Python 3.13+, broke again vs `bcrypt≥5.0` (Oct 2025). `pwdlib` is FastAPI's current official recommendation |
| JWT library | `PyJWT` | `python-jose` | `python-jose` release is years stale; `PyJWT` actively maintained, sufficient (no JWKS/multi-IdP need) |
| Primary keys | `uuidv7()` (PG18-native) | `gen_random_uuid()` (v4) | Time-ordered UUIDs keep B-tree index pages sequential on high-throughput insert tables (`transactions`); v4 fragments indexes |
| Money storage | `Numeric(14,2)` | `Float` | Binary floats can't represent decimal currency exactly; errors compound across aggregation |
| Password policy | Length-only (≥8 chars) | Composition rules (symbol/number required) | NIST SP 800-63B: composition rules push users toward predictable patterns; length is the stronger predictor |
| PDF text/table extraction | pdfplumber | PyMuPDF (fitz) | PyMuPDF is AGPL-3.0 (or paid Artifex commercial license); pdfplumber is MIT. Same shape of decision as Garage's AGPL rejection. pdfplumber's char/bbox-level model also fits the doc→page→region provenance requirement better, not just the safer license. Trade-off: ~10x slower on plain text, but volume isn't the constraint here |
| Scanned-page rasterization (for OCR) | pypdfium2 | pdfplumber's own `.to_image()` (Wand/ImageMagick), pdf2image (poppler) | Both alternatives pull in Ghostscript for PDF rendering, which is *also* AGPL — same problem one level down. pypdfium2 wraps Google's PDFium (Apache-2.0/BSD-3-Clause), zero copyleft anywhere in the pipeline. OCRmyPDF made the same switch as its preferred rasterizer |
| OCR engine | Tesseract 5.x + pytesseract | Cloud OCR (AWS Textract, Google Document AI, Azure Doc Intelligence) | Confirmed still-current free baseline (Apache 2.0). Known weakness on noisy/handwritten scans is an accepted gap for now — deferred to an eval, not decided by assumption, per the tracker's original framing |
| CSV/XLSX parsing | pandas + openpyxl | — | No real trade-off; settled, current, no currency concerns |
| Date-ambiguity policy | Strict DD/MM/YYYY only, no locale detection | Per-account locale field; per-document heuristic detection | Dhruv's explicit call: scope cut, not solved generally. Simpler and more predictable than heuristics that can silently guess wrong; MM/DD-convention statements are an accepted gap (see Known Gaps) rather than a half-solved auto-detector |
| Date parsing library | `python-dateutil` (`dayfirst=True`, explicit `strptime` formats tried first) | `dateparser` | `dateparser` has a cleaner ambiguity API and more recent release cadence, but pulls in `regex`/`pytz`/`tzlocal` for free-text/multi-language parsing this project doesn't need (statement dates are structured, not conversational). `python-dateutil` is already a transitive dep via pandas, permissively licensed, stable |
| Currency scope | INR + USD only | Locale-aware multi-currency (Babel) | Dhruv's explicit call. Both share the same decimal-point/comma-grouping convention, so one parser handles both without per-currency branching; a EUR-style comma-decimal currency needs real rework, not just a config flag (see Known Gaps) |
| Merchant fuzzy-matching | `rapidfuzz` | `fuzzywuzzy` / `thefuzz` | MIT vs GPL — same license-hygiene call already made for PyMuPDF/Garage. Confirmed still actively maintained (v3.14.x) |

---

## 5. Known Gaps (rolled up, not yet fixed)

- No rate limiting on `/auth/login` — brute-forceable
- No token revocation/logout — stolen token valid until 30-min expiry
- No refresh tokens, no password reset, no email verification
- No Postgres Row-Level Security — isolation is app-code-only (`user_id` filters)
- No retry backoff policy on Celery tasks (just `max_retries=3`, no exponential delay)
- MIME type validation trusts client-supplied `Content-Type` header — no
  magic-byte content sniffing yet (real fix belongs in Phase 2)
- Orphaned-object risk: if DB commit fails after a successful S3 upload,
  the object isn't cleaned up
- `pgvector/pgvector:pg18` and `valkey/valkey:8` and `chrislusf/seaweedfs:4.31`
  image tags — first two are `[VERIFY]`-flagged in compose comments;
  SeaweedFS tag confirmed against the real binary during Session 1
- Region/bbox-level provenance not yet stored — `DocumentPage.tables` holds
  extracted rows but not their coordinates on the page. Doc→page
  provenance exists; page→region is deferred until something downstream
  (evidence viewer, Phase 12) actually needs to highlight a specific
  region rather than just cite a page
- OCR quality is Tesseract's out-of-the-box accuracy — no image
  preprocessing (deskew, denoise, binarize, contrast) before OCR. Real
  scanned bank statements (skewed, low-contrast, phone-photographed) will
  likely need this; deferred until real test documents show whether it's
  actually necessary rather than guessed at up front
- `MAX_PDF_PAGES = 300` silently truncates larger documents (flagged with
  a `truncated_document` warning on the last processed page, but nothing
  currently surfaces that warning to the end user in a UI — there isn't
  one yet)
- No malware/content scanning on uploaded files before they reach
  pdfplumber/Pillow/pandas parsers — a hostile PDF/image/spreadsheet
  exploiting a parser vulnerability is out of scope for now (real fix
  belongs in Phase 11 security hardening)
- CSV encoding fallback list (`utf-8`, `utf-8-sig`, `latin-1`) covers
  common cases but isn't exhaustive — a CSV in an encoding outside this
  list fails outright rather than being detected via a charset-sniffing
  library (not added, to avoid an extra dependency for a case real bank
  exports rarely hit)
- Tabular extraction stores every cell as a string (`dtype=str`) — no
  numeric/date typing happens at this layer by design (that's Phase 3's
  job), but it does mean `DocumentPage.tables` is not directly usable for
  arithmetic without that later step
- **Strict DD/MM/YYYY date policy (Phase 3, Dhruv's explicit call)** — a
  statement using MM/DD convention (common in raw US bank exports) will
  be silently misparsed unless its dates happen to be unambiguous (day
  >12, or a month name like "Aug"). No per-account/per-document locale
  detection exists to catch this
- **INR/USD currency scope only (Phase 3, Dhruv's explicit call)** — any
  other account currency causes normalization to be skipped entirely
  (`normalization_status=skipped`, clear error message, not a crash).
  `amounts.py` also hardcodes the shared INR/USD comma-thousands/
  dot-decimal convention; adding a comma-decimal currency (EUR-style)
  needs real parser rework, not a config change
- Single-column "Amount" layouts (no separate Debit/Credit columns, no
  Cr/Dr suffix, no explicit sign) default to `debit` with reduced
  confidence (0.5) rather than being left ambiguous — `Transaction.
  transaction_type` has no "unknown" value in the schema, so a decision
  has to be made; flagged via confidence_score, not silently certain
- Merchant text cleaning (`clean_merchant_text`) is a hand-written regex
  heuristic (strips known prefixes/suffixes) — there's no universal bank
  merchant-field format, so it will miss real-world variants not covered
  by the prefix/suffix patterns it knows about
- Column detection (header keywords → reuse-from-previous-page →
  positional inference) fails closed: a table it can't classify by any
  of the three tiers is skipped with a `column_detection_failed` warning,
  not guessed at further. Genuinely novel statement layouts will produce
  zero transactions from that table, silently-except-for-the-warning
- Raw-text (no ruled tables) fallback line regex requires the amount to
  have exactly 2 decimal digits and reasonably consistent spacing —
  looser/noisier OCR text will fail to match and those lines are simply
  skipped, no transactions produced from them
- `MerchantAlias(user_id, pattern)` uniqueness isn't actually enforced by
  Postgres across system rows — `UNIQUE` treats `NULL` `user_id` values
  as distinct from each other, same caveat `Category` already had. Relies
  on the hand-curated seed list not containing accidental duplicates,
  not on a DB constraint
- Confidence score (`Transaction.confidence_score`) is a hand-weighted
  average of five heuristic components (column-detection source, date-
  parse method, amount-sign certainty, merchant-match tier, OCR quality)
  — not calibrated against any labeled dataset. Directionally reasonable,
  not a validated probability
- Accounts API (`POST/GET /accounts`) is intentionally minimal —
  create + list only, no update/delete. This gap actually predates Phase
  3 (the `Account` model has existed since Phase 0/1 with zero API
  surface) but went unnoticed until Phase 3's account-assignment flow
  needed it; full account management is still unowned by any phase
- `POST /documents/{id}/normalize` runs synchronously in the request
  thread (via Celery's `.apply()`, not `.delay()`) rather than being
  queued — fine at current single-document scale, inconsistent with
  `process_document`'s async dispatch pattern if this ever needs to
  handle a bulk re-normalize operation

---

## 6. Session Log

### Session 1 — 2026-09-03

**Scope covered:** Phase 0 (full) and Phase 1 (full).

**What was built and verified:**

1. **Phase 0 — Foundations**
   - Full repo scaffold: Docker Compose wiring Postgres 18+pgvector,
     Valkey 8, FastAPI backend, Celery worker, Next.js frontend.
   - `/health` endpoint checks real DB and Valkey connectivity, not just
     process liveness. Verified live via screenshots (frontend showing
     API/DB/cache all `ok`, matching backend JSON output exactly).
   - SQLAlchemy models for `User`, `Account`, `Category`, `Document`,
     `Transaction` — designed with `uuidv7()` PKs, `Numeric(14,2)` for
     money, self-referential FK on `Transaction.duplicate_of_id` (for
     future dedup) and `Category.parent_id` (hierarchy), provenance FK
     `Transaction.source_document_id`, and a `raw_data JSONB` column for
     unstructured extractor output.
   - First Alembic migration, written by hand (no live PG18 in sandbox to
     autogenerate against). **Tested for real**: installed a local
     Postgres 16 (sandbox lacks PG18/pgvector), temporarily swapped
     `uuidv7()`→`gen_random_uuid()` and skipped the `vector` extension
     line, ran `alembic upgrade head`, inserted real rows through the
     ORM (confirmed `amount` deserializes as `Decimal`, not `float`),
     ran `alembic downgrade base` to confirm rollback, then restored the
     file to production form and re-verified syntax/no leftover test
     substitutions.
   - Auth: signup/login/`/auth/me`, Argon2id via `pwdlib`, JWT via
     `PyJWT`. Deviated from common tutorials on both libraries after
     search revealed they're stale/broken (see Decisions Log). Login
     includes a timing-attack mitigation (dummy Argon2 verify against a
     precomputed hash when the user doesn't exist) and generic error
     messages on both signup/login to prevent email enumeration.
     **Tested for real**: 9 assertions via FastAPI TestClient against the
     real local Postgres — signup, duplicate-email rejection (DB unique
     constraint), weak-password rejection, wrong password, nonexistent-
     user login, successful login, protected route with valid/missing/
     garbage tokens.

2. **Phase 1 — Ingestion**
   - Object storage decision process: started with MinIO as a suggested
     default, caught via search that MinIO's Docker images were
     discontinued (Oct 2025) and the project archived (Apr 2026) —
     stopped and flagged this rather than building on dead infra.
     Presented Garage vs SeaweedFS vs local-filesystem trade-offs;
     Dhruv chose SeaweedFS after independent research.
   - Downloaded the actual SeaweedFS 4.31 Linux binary into the sandbox
     and ran it as a live S3 gateway (no Docker available in sandbox) to
     validate the storage wrapper against a real server before writing
     it: bucket create, put, list, get, presigned URL, delete — all
     confirmed via `boto3` before `storage.py` was written.
   - Built `app/core/storage.py` (S3 wrapper), `app/api/documents.py`
     (upload/list/get/download-url/delete endpoints), `app/pipeline/tasks.py`
     (`process_document` Celery stub task — flips status, no real
     extraction yet), and wired bucket auto-creation into FastAPI's
     startup event.
   - docker-compose updated: SeaweedFS service (`chrislusf/seaweedfs:4.31`,
     `server -s3` command, mounted `s3-config.json` for identity/credentials),
     backend/worker now depend on it with a healthcheck gate.
   - **Tested for real, full stack**: real Postgres + real running
     SeaweedFS + real Celery task (eager mode) through actual HTTP
     requests via TestClient — signup → login → upload → Celery
     processing → status transition → presigned download → byte-for-byte
     content match → cross-user access blocked (404, not 403) → delete.
     One test-methodology correction made mid-session: the upload
     response correctly shows `status: uploaded` (not `processed`)
     because it reflects the in-memory object before the async task
     commits — this was surfaced and confirmed as correct async
     semantics, not a bug, rather than being asserted away.

**Deliverables shared this session:** `finsight-phase0-scaffold.zip` →
`finsight-models-migrations.zip` → `finsight-auth.zip` →
`finsight-documents.zip` (each supersedes the last; documents.zip is the
current full state of the repo as of end of session).

**Edge cases identified this session:** schema/migration edge cases
(enum `ADD VALUE` transaction restriction, category cycle prevention,
multi-currency drift, PG18-only `uuidv7()` portability risk); auth edge
cases (no rate limiting, no token revocation, timing side-channels,
signup race conditions, Argon2 vs bcrypt truncation); upload/storage edge
cases (MIME spoofing, orphaned objects on partial failure, no retry
backoff, no content-based file type verification). Full detail in this
session's conversation; summarized in §5 above.

**State at end of session:** Phase 0 and Phase 1 complete and verified.
Next up: **Phase 2 — document text/table extraction + OCR.**

---

### Session 2 — 2026-09-12

**Scope covered:** Phase 2 (full) — document intelligence.

**Research → decision (⏸ surfaced, decided by Dhruv):** PDF text/table
extraction library. PyMuPDF is faster but AGPL-3.0 (or paid Artifex
license); pdfplumber is MIT. Same shape as the Garage AGPL rejection in
Phase 1 — Dhruv chose pdfplumber + pypdfium2 (for OCR rasterization,
avoiding Ghostscript's AGPL too). Full trade-off table in Decisions Log.
Tesseract 5.x confirmed still current or free OCR; pandas/openpyxl
confirmed settled, no research needed.

**What was built:**

- `ExtractionMethod` enum (`native_text` / `ocr` / `tabular`) and new
  `DocumentPage` model: one row per PDF page / image / spreadsheet sheet,
  carrying `raw_text`, `char_count`, `ocr_confidence`, `tables` (JSONB —
  list of tables → rows → cells), `warnings` (JSONB list), and a
  `(document_id, page_number)` uniqueness constraint. This is the
  doc→page provenance unit the spec's explainability requirement (§14)
  calls for. `Document.page_count` added.
- Alembic migration `0002_document_pages`.
- `app/pipeline/extractors/` package:
  - `pdf.py` — pdfplumber for native text + tables; per-page fallback to
    pypdfium2 rasterization (300 DPI) + Tesseract OCR when native text is
    under a 20-char threshold (real bank-statement footers/headers clear
    this easily; a truly scanned page doesn't). `MAX_PDF_PAGES = 300` cap
    with a `truncated_document` warning on the last processed page.
  - `image.py` — standalone PNG/JPEG uploads, OCR-only.
  - `spreadsheet.py` — pandas/openpyxl for CSV (with a
    utf-8 → utf-8-sig → latin-1 encoding fallback chain, since real bank
    CSV exports are frequently not UTF-8) and XLSX (one DocumentPage per
    sheet). Everything stored as `dtype=str` deliberately — normalization
    is Phase 3's job, not this layer's.
  - `ocr.py` — shared Tesseract wrapper using `image_to_data` (not
    `image_to_string`) specifically to get per-word confidence back;
    computes a mean confidence and flags `low_ocr_confidence` below 60.
- `tasks.py` rewired: `process_document` now downloads the real file,
  dispatches to the right extractor by mime type, persists `DocumentPage`
  rows, and sets `page_count` — replacing the Phase 1 stub entirely.
- `storage.py`: added `download_file`.
- New endpoint `GET /documents/{id}/pages` — the evidence-layer read path.
- Dockerfile: added `tesseract-ocr` apt package (covers both `backend`
  and `worker` services, which share this image).

**Tested for real, full stack:** real Postgres (16 substitute — sandbox
still lacks PG18; `uuidv7()` polyfilled *only* in the local test DB via a
`gen_random_uuid()`-backed SQL function, never touching the shipped
migration files — confirmed via `git diff` after the fact) + real running
SeaweedFS 4.31 binary + real Celery task (eager mode) + real Tesseract
5.3.4, through actual HTTP requests via TestClient:

- Native-text PDF (built with reportlab) → `native_text`, correct content
- Image-only PDF (real scanned-look PNG embedded with no text layer) →
  correctly fell back to OCR, extracted the embedded text, reported a
  real confidence score (90.1)
- Standalone PNG and JPEG uploads → OCR'd correctly
- UTF-8 CSV → `tabular`, correct header/rows
- cp1252-encoded CSV (real Windows-export-style encoding, with a non-ASCII
  merchant name) → encoding fallback chain correctly caught it and
  recorded a `decoded_as_latin-1` warning
- Multi-sheet XLSX → 2 `DocumentPage` rows, correct `page_count`
- Encrypted PDF → correctly marked `failed`
- Corrupt/non-PDF bytes → correctly marked `failed`
- Cross-user access to `/documents/{id}/pages` → 404, not the data
- `MAX_PDF_PAGES` truncation, verified directly against a real 3-page PDF
  with the cap monkeypatched to 2 → stopped at 2, `truncated_document`
  warning present on the last page

**Test-methodology correction made mid-session** (same pattern as
Session 1's async-status correction): the first full run of the
encrypted/corrupt-file tests crashed the test harness itself, not the
task. Eager-mode Celery testing was configured with
`task_eager_propagates=True`, which makes `process_document`'s
intentional re-raise (needed so a *real* broker/worker's retry and
observability machinery sees task failures) bubble synchronously into
the HTTP request thread — something that can never happen with a real
broker, where `.delay()` returns immediately and the task runs in a
separate worker process. Fixed by leaving eager-mode propagation at its
default (off) rather than changing the task's own error handling, since
the task's behavior was correct and the test harness's config was not
representative of production.

**Real bug found and fixed via this testing** (not assumed away): the
encrypted-PDF test then surfaced that `document.error_message` was being
stored as an empty string. `str(exc)` on pdfplumber's
`PdfminerException(PDFPasswordIncorrect())` is genuinely `''` — the
wrapped exception carries no message, only its type. Fixed by falling
back to `repr(exc)` whenever `str(exc)` is empty, so a failed-document
row is never left with an uninformative blank `error_message`.

**Edge cases identified this session:** encrypted/password-protected
PDFs (now `failed` with a real error, not empty); corrupted/non-PDF bytes
uploaded with a PDF mime type; CSVs in non-UTF-8 encodings; multi-sheet
XLSX; pages with partial text (some ruled tables still detected on
otherwise image-only pages); adversarially large PDFs (capped, not
processed indefinitely); zero-page/empty workbooks (raises, marked
failed, not silently producing zero `DocumentPage` rows). Full detail in
this session's conversation; summarized in §5 above.

**State at end of session:** Phase 2 complete and verified. Next up:
**Phase 3 — financial data normalization** (dates, amounts/currency,
merchant canonicalization) reading from `DocumentPage.raw_text` /
`.tables` to populate actual `Transaction` rows.

---

### Session 3 — 2026-09-23

**Scope covered:** Phase 3 (full) — data normalization.

**Research → decisions (⏸ surfaced, decided by Dhruv):** Two genuine
trade-offs presented before writing code — (1) how to resolve date/
number-format ambiguity (explicit per-account locale field vs. pure
heuristic vs. hybrid), and (2) `python-dateutil` vs `dateparser`. Dhruv's
call, simpler than any option offered: **strict DD/MM/YYYY only, no
locale detection at all**, and **INR/USD currency scope only** — both
explicit scope cuts, not deferred half-measures, with the resulting
limitations to be stated plainly (done — see Known Gaps). This also
resolved the library choice: `python-dateutil` with `dayfirst=True`
forced, no need for `dateparser`'s ambiguity-handling machinery.
`rapidfuzz` (MIT) confirmed current and used for merchant fuzzy-matching
without a stop — same license-hygiene precedent as PyMuPDF/Garage,
not a new trade-off.

**What was built:**

- `NormalizationStatus` enum and new `Document` fields
  (`normalization_status`, `normalized_at`, `normalization_error`,
  `transaction_count`) — kept separate from the existing `status` field,
  which only ever tracked Phase 2 extraction.
- `MerchantAlias` model — same `user_id`-nullable-means-system-level
  pattern as `Category`. Seeded via the migration with ~20 hand-written
  patterns (Amazon, Walmart, Starbucks, Swiggy, Flipkart, IRCTC, etc. —
  a deliberately small hand-curated list, not an external merchant
  dataset, to avoid a licensing/currency research detour on a portfolio
  project).
- `app/pipeline/normalize/` package: `dates.py` (strict-format
  `strptime` attempts first, `dateutil` fallback with `dayfirst=True`
  forced, sanity-bounded year), `amounts.py` (currency-symbol/Cr-Dr-
  suffix/parens/comma stripping straight to `Decimal`, never `float`),
  `columns.py` (three-tier column detection: header keywords → reuse
  previous page's mapping → positional inference by sampling which
  column's values actually parse as dates/amounts), `merchants.py`
  (alias match → rapidfuzz self-clustering against the user's own
  already-resolved merchants → cleaned-text-as-its-own-canonical-name),
  `engine.py` (orchestrates all of the above per `DocumentPage`,
  idempotent re-run via delete-then-recreate, per-row confidence scoring
  from five weighted components).
- `normalize_document` Celery task, auto-chained after `process_document`
  succeeds (extraction failure is never reported as a normalization
  failure and vice versa — separate status fields, separate try/except
  blocks).
- Alembic migration `0003_normalization`.
- API surface: `PATCH /documents/{id}` (assign/reassign account),
  `POST /documents/{id}/normalize` (manual re-trigger), `GET
  /transactions` + `GET /transactions/{id}` (new router).
- **Gap discovered mid-session, patched**: there was no Accounts API at
  all — the `Account` model has existed since Phase 0/1 with zero CRUD
  endpoint. This predates Phase 3 but blocked it completely (Phase 3's
  account-assignment flow has nothing to assign *to* via the API).
  Added a minimal `POST/GET /accounts` (create + list only, deliberately
  not more — see Known Gaps) rather than working around it with
  DB-only testing.

**Real bug found and fixed via testing** (not assumed away, per the
project's standing methodology): the header-keyword column matcher used
naive substring containment (`keyword in lowered_cell`). The short
abbreviation keywords "cr"/"dr" (meant to catch bare "Cr"/"Dr" column
headers) matched *inside* unrelated words — `"cr" in "description"` is
`True` (**des-CR-iption**) — which silently misclassified a real
Description column as a bogus Credit column on any statement using that
exact header text, discarding the actual description and (in a
debit/credit-column layout) dropping a real credit transaction (a test
payroll-deposit row) entirely, since nothing was left pointing at the
true credit column. Fixed with word-boundary regex matching (`\bcr\b`)
instead of substring containment. Caught only because the test fixtures
used realistic header text ("Description") rather than avoiding it.

**Tested for real, full stack** (PG16 substitute again — sandbox still
lacks PG18; `uuidv7()` polyfilled only in the local test DB via
`gen_random_uuid()`, confirmed via `git diff` to never touch shipped
migration files; Redis as the sandbox's Valkey substitute, same
RESP-protocol reasoning already on record):

- Migration `0003_normalization`: upgrade → downgrade → re-upgrade
  round-trip, seed data (21 aliases) verified present after each
  upgrade.
- Direct engine tests (`normalize_document(db, document)` called
  in-process against real Postgres): Indian-style single-Amount+Cr/Dr
  multi-page statement with header-detection on page 1 and mapping-reuse
  on the unlabeled continuation page 2; US-style separate Debit/Credit
  columns with an OCR page (confidence correctly pulled down by
  `ocr_confidence`); raw-text-only fallback via line regex, including a
  parenthesized-negative amount; strict DD/MM/YYYY correctness on a
  genuinely ambiguous date (`15/09/2026` → Sept 15, confirmed not
  Sept 9); cross-page merchant canonicalization ("AMZN MKTPLACE" and
  "AMAZON.COM PURCHASE" both → "Amazon"); bad-date and empty-amount rows
  correctly skipped with page warnings recorded; `EUR` account correctly
  raised `UnsupportedCurrencyError`; re-running normalization on the same
  document produced identical output, not duplicates.
- Celery task tests via a **real Celery worker process connected to a
  real Redis broker** (not eager mode) — dispatched `normalize_document.
  delay()` for three documents in parallel, polled real `AsyncResult`s:
  normal success path, "skipped — no account assigned" path, "skipped —
  unsupported currency" path, all confirmed via actual queue round-trip.
- Full HTTP API tests via `TestClient` against real Postgres: signup →
  login → create account → (simulated Phase-2-extracted document,
  upload itself needs SeaweedFS which is out of this phase's scope) →
  normalize-before-account-assignment (correctly skipped) → `PATCH`
  assign account → normalize-after-assignment (correctly normalized,
  `transaction_count=1`) → `GET /transactions` (merchant correctly
  canonicalized to "Amazon" through the real API, correct amount/
  currency) → `GET /transactions/{id}` → cross-user isolation on all
  three new endpoints (404s and empty lists, not 403s, consistent with
  the existing documents-API pattern).

**Edge cases identified this session:** ambiguous single-amount-column
sign (documented default, not silently certain); genuinely novel table
layouts that fail all three column-detection tiers (skipped, not
guessed at); non-DD/MM and non-INR/USD statements (out of scope by
explicit decision, not a bug); merchant text variants the cleaning
regex doesn't recognize; `MerchantAlias` uniqueness not DB-enforced
across system rows (same caveat `Category` already carries). Full detail
in this session's conversation; summarized in §5 above.

**State at end of session:** Phase 3 complete and verified. Next up:
**Phase 4 — deterministic financial analytics** (income/expense/
cash-flow calculations, category/vendor/account summaries, budget
utilization math) over the now-populated `Transaction` table.

---

<!-- Next session: append a new "### Session N — YYYY-MM-DD" block below,
     update the Phase Roadmap checkboxes, and add any new rows to the
     Decisions Log / Known Gaps as they come up. -->
