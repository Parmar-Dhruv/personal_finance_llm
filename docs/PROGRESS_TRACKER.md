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
      schemas/ (auth.py, document.py, account.py, transaction.py, category.py, budget.py, analytics.py, ml.py)
      api/ (auth.py, documents.py, accounts.py, transactions.py, categories.py, budgets.py, analytics.py, ml.py, deps.py)
      analytics/ (common.py, cashflow.py, breakdowns.py, budgets.py, recurring.py)   # Phase 4/5, no FastAPI imports
      ml/ (taxonomy, rules, classifier, duplicates, recurring, anomalies, service, synthetic, eval, train, llm_classifier, eval_llm, eval_public)   # Phase 5
      pipeline/
        tasks.py
        extractors/ (common.py, ocr.py, pdf.py, image.py, spreadsheet.py)
        normalize/ (dates.py, amounts.py, merchants.py, columns.py, engine.py)
    tests/ (conftest.py + 10 test modules, 151 tests, real Postgres)      # Phase 4: 60, Phase 5: +91
    docs/ml_eval/ (report.md/json, public_ood.json, llm_synthetic.json)  # Phase 5 evals
    README.md, pytest.ini, requirements-dev.txt
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
- **Phase 4 — Deterministic Analytics** ✅
  - ✅ Income/expense/cash-flow calculations (per currency, summary + monthly with MoM)
  - ✅ Category/vendor/account summaries
  - ✅ Budget utilization math (monthly budgets, category-subtree roll-up)
  - ✅ Minimal categories API + manual category assignment (gap patch, see Session 4)
  - ✅ "Recurring expense totals" (spec §8) — delivered in Phase 5 as GET /analytics/recurring
- **Phase 5 — ML Layer** ✅ (Anthropic path still unverified, see Known Gaps)
  - ✅ Transaction classification: rules baseline, TF-IDF+LogReg, hybrid policy (suggest-first), measured on synthetic data with merchant-grouped CV
  - ✅ LLM leg: Anthropic + Gemini adapters; real Gemini run n=300 → 94.3% vs hybrid 91.3% on synthetic holdout (`docs/ml_eval/llm_synthetic.json`)
  - ✅ Duplicate detection with auto/pending/confirmed/dismissed review workflow
  - ✅ Recurring payment detection + /analytics/recurring totals
  - ✅ Anomaly detection (robust z hierarchy; IQR + Isolation Forest as benchmarks)
  - ✅ Public-dataset out-of-distribution check: 12,144 mapped rows, coverage 48.9%, precision-on-answered 48.6% (`docs/ml_eval/public_ood.json`); lossy label map, signal only
- **Pre-Phase 6 — maintenance** ✅
  - ✅ Git baseline against the existing remote, docs tracked, pushed to `main`
  - ✅ Full Docker build + PG18.6 stack, migrations 0001→0006, model training, 151-test suite
  - ✅ UTF-8 production lockfile; Dockerfile/dev requirements install it
  - ✅ MerchantAlias uniqueness, inclusive `date_to`, suggestion undismiss
  - ✅ `eval_llm` / `eval_public` both run with user-supplied credentials; artifacts committed
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
| Multi-currency analytics (Phase 4) | Per-currency results, never convert | Convert to a base currency via an `fx_rates` table / external API | Dhruv's call (recommended option). No FX data source, no historical-rate-date semantics, no "missing rate" failure mode in a phase meant to be purely deterministic. Cost: no single combined total for a user with both INR and USD accounts |
| Category plumbing (Phase 4) | Minimal `POST/GET /categories` + `PATCH /transactions/{id}` category assignment | Analytics-only, categories insertable only via DB | Dhruv's call (recommended). Same minimal-patch precedent as the Phase 3 Accounts gap; makes category summaries/budgets testable end-to-end through the API. Phase 5 classifier will write the same `category_id` column |
| Budget scope (Phase 4) | Monthly only; per-category (subtree) or overall; currency on the budget | Flexible weekly/monthly/yearly periods | Dhruv's call (recommended). Spec only shows monthly examples; flexible periods add week-start/partial-period edge cases for no current need |
| Uniqueness with NULL columns | `UNIQUE ... NULLS NOT DISTINCT` (PG15+) for budgets and for categories (`user_id, parent_id, lower(name)`) | Plain `UNIQUE` (NULLs distinct) / application-only checks | Plain UNIQUE silently never constrained system or top-level categories (Phase 1 caveat) and would allow unlimited "overall" budgets. NULLS NOT DISTINCT is DB-enforced and race-free (verified with concurrent requests). Raises the Postgres floor to 15 — already below the PG18 target |
| Budget → category FK on delete | `ON DELETE CASCADE` | `SET NULL` | SET NULL would silently turn a deleted category's budget into an *overall* budget |
| "Spent" definition for budgets | Gross debits in the budget's currency in the calendar month, excluding flagged duplicates; refunds not netted | Net of refunds | Simplest unambiguous definition; refunds need Phase 5 context to attribute to the right category. Logged as a gap |
| Month bucketing | UTC calendar months | User-timezone months | Phase 3 stores dates as midnight-UTC calendar dates, so UTC is exactly right for stored data; a user timezone would only matter for the "current month" default |
| Money in API JSON | `Decimal` → string | float | Same reasoning as `Numeric` storage; clients can't lose cents |
| Phase 5 labeled data | Own seeded synthetic generator for training + merchant-grouped CV; separate OOD check on the public HF dataset | Public HF dataset (mitulshah/transaction-categorization) as the training source | Dhruv's call ("both, separately"). HF dataset is MIT-labelled but mixes synthetic and unnamed external sources, and its categories don't match ours. The OOD check could not run (HF blocked in sandbox) → script only. **Update (Session 6):** run with an HF token on 12,144 mapped rows; signal only, not a benchmark |
| Phase 5 LLM classifier | Interface + eval script, off by default, real eval deferred | Run it now; defer to Phase 8 | Dhruv's call (recommended). No API key in sandbox; BUILD_LOOP forbids counting unverified work as done. **Update (Session 6):** Gemini adapter added and run; Anthropic still unverified |
| Phase 5 auto-apply policy | Suggest-first: rule/hybrid auto-apply, ML-only suggestions; never overwrite user categories; duplicates auto only at ≥0.95 | Always write category_id; never auto-apply anything | Dhruv's call (recommended). Evaluation then showed why it matters: ML-only precision on unseen merchants is ~30% with anti-calibrated confidence, so the ML-only auto threshold is `null` (never) |
| Phase 5 scope | All four components in one phase | Split into 5a/5b | Dhruv's call |
| Anomaly method | Robust z-score (median/MAD, log amount), hierarchical baseline | Isolation Forest; IQR | **My call, not surfaced** (judged low-stakes): PR-AUC on injected synthetic anomalies robust-z 0.63 ≈ IQR 0.64 ≫ IF 0.36, and z-scores are explainable (`anomaly_detail`). IQR is equally good here; z chosen for the conventional 3.5 cutoff |
| Recurring / duplicate methods | Deterministic interval/amount rules; hand-weighted duplicate score | Learned models | **My call**: no labeled real data to learn from; weights are uncalibrated and documented as such |
| ML libraries | scikit-learn 1.9.1 (BSD-3), joblib, numpy | LightGBM / transformers | Currency confirmed on PyPI via pip index; license-clean. Gradient boosting/transformers not tried — scope call, not a finding |
| Status columns | Plain strings + CHECK constraints (`category_source`, `duplicate_review`) | PG enums | Avoids the ALTER TYPE ADD VALUE transaction restriction noted in Session 1 |
| Per-user ML serialization | `pg_advisory_xact_lock` per user in every service step | Row locks / unique constraints | Concurrent runs duplicated recurring series in testing; delete+insert of derived data needs a mutex, not a constraint |
| Self-FK indexes | Partial indexes on `duplicate_of_id`, `duplicate_candidate_of_id` | None | Measured: deleting 100k transactions >15 min without them |
| Test tooling | `pytest` + `httpx` (dev-only `requirements-dev.txt`), suite committed in `backend/tests/` | Continue with throwaway scripts | Phase 4 is the first phase with enough logic to need a regression suite. Not a trade-off needing Dhruv's input; pytest 9.x confirmed current (already installed at 9.1.1 in the sandbox venv; the web search for it returned only stale docs, so currency rests on that, not on a source) |
| Version control (pre-Phase 6) | Init against the existing GitHub remote, fetch `origin/main` (Phase 4), commit the local Phase 5 tree on top, track `docs/`, push to `main` | Fresh orphan history / keep docs ignored | Preserves the real remote history; BUILD_LOOP's `git diff` revert checks need a repo; the spec/tracker are load-bearing files, not junk |
| Dependency pinning (pre-Phase 6) | Freeze production deps inside the Linux image → UTF-8 `requirements.lock.txt`; Dockerfile and `requirements-dev.txt` install the lock | Dockerfile stays on unpinned `requirements.txt`; regenerate a Windows freeze | Reproducible image; a Windows freeze would leak platform-only packages. Dev installs the same production pins |
| Local env/DB (pre-Phase 6) | Reuse the existing `finsight_dev_password` volume (empty), generate only a random `SECRET_KEY`; create `finsight_test` + `finsight_migration_test` in the same PG18 container | Reset volumes with a new password / separate test container | Volumes already existed and held no data; the test suite and compose defaults already use that password |
| Pre-Phase 6 hardening | Migration 0006 for `MerchantAlias` `UNIQUE NULLS NOT DISTINCT`; `GET /transactions?date_to=` half-open; `suggestion/undismiss` endpoint | Carry them into Phase 6 as known gaps | All three were small, isolated, and easier to verify before Phase 6 adds another migration |
| Phase 5 eval execution | User runs `eval_llm` with their key; `eval_public` needs an authenticated HF account because the dataset is gated | Run them in this session without a key/token | Network works from the container, but no Anthropic key is present and HF requires accepted terms + token. **Update (Session 6):** user supplied Gemini + HF credentials; both evals run and recorded |

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
- ~~`MerchantAlias(user_id, pattern)` uniqueness isn't actually enforced across
  system rows~~ **Fixed pre-Phase 6** in migration `0006_merchant_alias_uniqueness`:
  the constraint is now `UNIQUE NULLS NOT DISTINCT (user_id, pattern)`, matching
  the Category/Budget fix pattern. Covered by `test_migrations.py`.
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

### Added in Phase 4

- **Transfers are counted as income/expense** — credit-card bill payments and
  own-account transfers aren't detected, so they inflate both income and
  expense (and double-count card purchases). Needs Phase 5 classification
- **Refunds are not netted** against category/merchant spend or budget
  utilization (a refund is a credit → counted as income only)
- Analytics ignore `confidence_score`: low-confidence rows (e.g. unsigned
  single-amount defaulted to `debit`) are summed like any other
- Credit-card statement debit/credit semantics not validated against real-world
  layouts (Phase 3 behavior, now feeding numbers users will read)
- `/analytics/categories` reports directly-assigned categories only, while
  budgets roll up descendants — documented, but nested categories won't
  visually reconcile between the two
- No "recurring expense totals" (spec §8); `is_recurring` is always false until Phase 5
- Budgets: monthly only; no weekly/yearly/rollover/proration; status is computed
  on request, nothing delivers an alert (Phase 9); no forecast-based projection (Phase 6)
- Categories API is create + list only: no rename/move/delete, no bulk assignment;
  max nesting depth 3 is an arbitrary guard. A category deleted directly in the DB
  cascades to its children and budgets
- Budget category/currency are immutable (delete + recreate to change)
- Month rollover and the `budget-utilization` default month are UTC (IST users see
  rollover at 05:30 local)
- No caching/materialized views. Sandbox measurement only: one user with 104k rows
  among 204k, all-time summary ≈46 ms, one month ≈5 ms, planner uses
  `ix_transactions_user_date`; Postgres 16, no concurrency, not PG18
- ~~`GET /transactions?date_to=` compares timestamp `<=` date, excluding later-in-the-day
  rows~~ **Fixed pre-Phase 6**: it now uses the analytics half-open bound
  (`< date_to + 1 day`), so the whole calendar day is included. Covered by
  `test_transactions_filters.py`.
- `MerchantAlias(user_id, pattern)` still has the NULL-distinct uniqueness caveat
  (Category's was fixed in 0004; MerchantAlias was left alone as out of scope)
- Phase 4 tests ran on Postgres 16 with a test-DB-only `uuidv7()` polyfill; the
  Celery/Valkey/SeaweedFS/OCR chain was not re-run end-to-end this session
  (normalization engine was exercised in-process, not via a worker)
- FastAPI `@app.on_event("startup")` deprecation warning (pre-existing, untouched)

### Added in Phase 5

- **Anthropic LLM path still unverified; Gemini verified.** `gemini-3.5-flash-lite` completed n=300 against the real API (94.3% vs hybrid 91.3%, synthetic holdout; 0 abstentions). The Anthropic model id (`claude-haiku-5-5`) remains a guess. Both adapters are off by default; `LLM_PROVIDER` selects one. Reproduce: `docker compose run --rm --no-deps backend python -m app.ml.eval_llm --n 300`.
- **Gemini free tier limits the eval.** 20 requests/model/day; n=300 uses 12. `gemini-2.5-flash` is closed to new keys; 3.8/3.5 Flash returned 503s, so Flash-Lite was used. The adapter retries 429/5xx four times with backoff; 60 s request timeout.
- **Public OOD check run, but not a benchmark.** 12,144 of 20,000 rows mapped (48.9% coverage), 48.6% precision on answered, 23.8% accuracy counting abstentions as wrong (`docs/ml_eval/public_ood.json`). The dataset's categories do not match this project's ten; the map is lossy and its MIT label does not settle provenance.
- **All ML numbers are synthetic and same-author.** Rules were written by the person who wrote the evaluation merchants; expect worse on real statements
- **ML classifier ≈ merchant lookup.** Unseen merchants: 42% (ML alone), ML-only precision ~30%, confidence anti-calibrated. No feedback loop retrains on user corrections — highest-value next step
- Model is a pickle in `backend/models/` (git-ignored): trusted-write-only; sha256 detects corruption not tampering; tied to the exact scikit-learn version; **not** baked into the Docker image. The Docker build is now exercised (pre-Phase 6), and the bind mount lets backend/worker share `python -m app.ml.train` output
- Duplicate score weights hand-set/uncalibrated; synthetic duplicates are exact copies (real re-exports differ in narration); transfers between own accounts and card-bill payments still not detected
- Recurring: monthly bills whose date drifts >±4.5 days between months are missed (4/140 synthetic streams); no daily cadence; ≥2 yearly occurrences only gives confidence ≤0.55; series ids unstable across runs (derived, recreated)
- Anomalies: upward only; needs history (8/15/30); recall 0.13 on moderate, 0.55 on severe injections; MAD floor 0.15 means a flat baseline needs ≥2.2× to flag
- `POST /ml/run` synchronous (100k rows: ~2 min total; classify 77 s, anomalies 41 s, 0.8 GB RSS); no incremental processing — Celery job re-evaluates the whole user each upload
- ~~Explicit "clear category" sets `suggestion_dismissed` with no un-dismiss endpoint~~
  **Fixed pre-Phase 6**: `POST /transactions/{id}/suggestion/undismiss` clears only
  the dismissal flag (a user-assigned category stays final). Covered in
  `test_ml_service_api.py`.
- ~~`requirements.lock.txt` is UTF-16/CRLF and lacks scikit-learn~~ **Fixed pre-Phase 6**: regenerated as UTF-8/LF inside the Linux image; includes scikit-learn/joblib; Dockerfile and `requirements-dev.txt` install it
- Phase 3 merchant cleaning leaves IFSC-style codes in NEFT merchants ("Hdfc0001234-Infosys Ltd-Salary")
- Celery chain verified with a real worker + real Redis (not Valkey, not SeaweedFS/OCR in that run — documents were simulated as in Phase 3)
- ~~Postgres 16 again (not 18)~~ **Also verified on PG18 pre-Phase 6**: 147 tests + migrations 0001→0006 on the real PG18.6 container, native `uuidv7()` (polyfill remains test-only for older DBs)

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

### Session 4 — 2026-10-18

**Scope covered:** Phase 4 (full) — deterministic analytics.

**Research → decisions (⏸ surfaced, decided by Dhruv, all three took the
recommended option):** (1) mixed-currency handling → per-currency, no
conversion; (2) categories were empty with no API → minimal category API +
manual assignment; (3) budget scope → monthly only, per-category + overall.
No new runtime library was needed (SQL + `Decimal`). `pytest` added as a
dev dependency — its currency was **not** verified from a source (search
returned only stale pages); it's installed at 9.1.1 in the sandbox venv.
Honest note: this thin on "search first" for the one new dependency.

**What was built:**

- Migration `0004_analytics_budgets`: `budgets` table (amount > 0 and 0 < threshold ≤ 100
  CHECKs; `UNIQUE NULLS NOT DISTINCT (user_id, category_id, currency)`); replaced the
  Phase 1 category UNIQUE with `UNIQUE (user_id, parent_id, lower(name)) NULLS NOT
  DISTINCT` (fixes the NULL-distinct hole and makes names case-insensitive); seeded the
  spec's 10 system categories; indexes `ix_transactions_user_category`, `ix_categories_parent_id`.
- `app/analytics/` (no FastAPI imports so Phase 8 can wrap it as tools): `Scope` +
  shared filter (user, duplicates excluded, inclusive dates via half-open bound),
  `summary`, `monthly` (gap-filled, MoM absolute/%, `partial` flag), `by_category`,
  `by_merchant`, `by_account`, `budgets.utilization` (recursive-CTE subtree roll-up).
- API: `/analytics/{summary,monthly,categories,merchants,accounts,budget-utilization}`,
  `/budgets` CRUD, `/categories` create/list, `PATCH /transactions/{id}` (assign/clear category).
- Docs: root README rewritten for Phase 4 and a new `backend/README.md` (layering, exact
  analytics definitions, Phase 4 gaps, how to run the suite).

**Tested for real:** committed pytest suite, **60 tests, all passing**, against real
Postgres 16 + real Alembic migrations + real HTTP (TestClient), no mocks. Covers: exact
decimals (1000×0.10 = 100.00); currency separation; inclusive date edges; month/year/
leap-day boundaries; gap-fill, `partial`, zero-denominator %; duplicate exclusion;
breakdowns incl. ties/limit/`Uncategorized`; budget status boundaries (79.999%, exactly
threshold, exactly limit, +1 cent); subtree roll-up; per-currency budgets; cross-user
isolation + 401 on every endpoint; validation (NaN/Infinity, 3-dp amounts, bad months,
inverted ranges); concurrent duplicate category/budget creation (exactly one 201, rest 409);
migration base→head→0003→head with constraints exercised in raw SQL; and a Phase 3→4 seam
test using transactions produced by the real normalization engine (incl. re-normalize
idempotency). Scale check: 204k rows / 104k for one user — see Known Gaps for numbers.

**Test-premise/expectation errors found and corrected (not retrofitted):**
1. A float-drift sanity check failed because Python ≥3.12 `sum()` uses compensated
   summation and does *not* drift; the premise was wrong, so the check now uses naive
   accumulation (and a comment records the trap).
2. The seam test assumed `normalize_document` commits. It doesn't (the Celery task
   owns the commit) — the function's docstring wrongly said it did. Fixed the
   **docstring**, not behavior; the test now commits like the task does.
3. One expected total in my own test was arithmetic I got wrong (2400.50 vs 2400.00);
   the code was right.
No production bug was found in Phase 4 code by the suite.

**Sandbox substitutions & revert check:** PG16 instead of PG18; `uuidv7()` polyfill
exists only in `tests/conftest.py` and only against `*_test` DBs (the harness refuses
other names). Verified: `git diff` on migrations 0001–0003 is empty, 0004 and models use
native `uuidv7()`, and `grep gen_random_uuid` outside `tests/` finds only a pre-existing comment.

**Edge cases identified:** mixed currencies; transfers/card payments double-counting;
refunds; zero/negative/NaN/over-precision amounts; 79.996% rounding vs threshold;
spend exactly at limit; spend at month boundaries and leap day; partial first/last
months; empty months and zero-denominator % change; duplicate-flagged rows; shadowing
system categories; category cycles (impossible via API; CTE uses UNION as a backstop);
concurrent duplicate creation; budget outliving its category; `NULL` merchants; user in
IST seeing UTC month rollover. Details in `backend/README.md`.

**State at end of session:** Phase 4 complete and verified. Next up: **Phase 5 — ML
layer** (classification → duplicates → recurring → anomalies). Expect the first real
decision to be where labeled data comes from.

---

### Session 5 — 2026-10-26

**Scope covered:** Phase 5 (full) — ML layer: classification, duplicates, recurring, anomalies.

**Research → decisions (⏸ surfaced, decided by Dhruv):** labeled-data source (→ own synthetic + separate public-dataset OOD check), LLM leg (→ interface now, real eval later), auto-apply policy (→ suggest-first), scope (→ all four). Currency checks: scikit-learn 1.9.1 / numpy / joblib / lightgbm current via `pip index` (search results were thin; PyPI is the source). HF dataset card read: MIT-labelled, 4.5M rows, partly synthetic with unnamed external sources, categories don't match ours.

**What was built:** migration `0005_ml_layer` (recurring_series; provenance columns; CHECKs; backfill of `category_source='user'` and duplicate review; partial indexes); `app/ml/` (see layout); service layer with per-user advisory lock; Celery task `enrich_user_transactions` chained after `normalize_document`; `/ml/*` API, suggestion accept/reject, duplicate confirm/dismiss, `/analytics/recurring`, `is_anomaly`/`is_recurring` filters; PATCH now records `category_source='user'`; eval harness + report; train CLI; LLM interface; two scripts for the user to run.

**Tested for real:** 147 tests pass on real Postgres 16 + real migrations + real HTTP (60 old, 83 new). Real Celery worker on real Redis ran normalize → enrich and produced categories + recurring series. 100k-row timing run. Migration 0005 upgrade/backfill/CHECKs/downgrade/re-upgrade.

**Test-premise / expectation errors found and corrected (not retrofitted):**
1. Migration-head assertion hard-coded 0004 (expected after adding 0005); and my new migration test started at "0004" when the DB was already at head (no-op) → added explicit downgrade first.
2. Rent 22,000→40,000 expected to flag; it doesn't (MAD floor ⇒ needs ≥2.2×). Code left as designed, test and docs state the consequence.
3. Tests assuming a "Fortis Hospital" row is ML-only (the `hospital` rule fires); a never-seen merchant being "no baseline" (the user-wide baseline legitimately catches it); weekly stream ending in Feb being active (correctly inactive vs a June latest transaction).
4. First anomaly ground truth (×6–15) was undetectable for high-variance merchants → two severities; recall reported per severity instead of tuning.

**Real bugs/findings from evaluation and testing:** ML unseen-merchant collapse (→ ML-only never auto-applies); recurring chance-match false positives from the amount-cluster path (5/20 users had a fake "quarterly Uber") → fixed; concurrent runs duplicated recurring series → advisory lock; deleting 100k transactions took >15 min (unindexed self-FKs) → partial indexes in 0005; my shell `pkill -f` matched its own command line (sandbox mishap, no project impact).

**Sandbox substitutions & revert check:** PG16, `uuidv7()` polyfill only in tests/conftest.py (`*_test` DBs); Redis stood in for Valkey. Verified: `git diff` on migrations 0001–0004 empty; `gen_random_uuid` outside tests only in a pre-existing comment.

**Not done / unverified:** see "Added in Phase 5" above — chiefly the LLM leg, the public-dataset check, and real-data accuracy.

**Edge cases identified:** unseen merchants; Salary as a debit; employer names that look like shops (Flipkart Internet); refunds as credits; truncated/typo'd narrations; re-uploaded statements, ±1-day posting shifts, distinct bank refs, daily fares, triplicates; price rises, skipped months, interleaved subscriptions at one merchant, chance clusters, same-day rows; flat (zero-spread) baselines, tiny history, per-currency/direction baselines, duplicates polluting baselines; concurrent runs; user-set categories vs forced reclassification; dismissed suggestions; stale auto-flags after data changes; corrupt/old-version/missing model file; prompt-injected narrations (LLM path forced through an enum tool, output re-validated).

**State at end of session:** Phase 5 complete with the caveats above. Next up: **Phase 6 — Forecasting** (baseline statistical forecast, then ML benchmarked against it; can use recurring series for known obligations).

---

---

### Session 6 — 2026-10-28

**Scope covered:** pre-Phase 6 maintenance only — close the seven repo/Phase-5 loose ends; no Phase 6 feature work.

**Decisions made by Dhruv before execution:** preserve the existing GitHub remote history and push to `main`; production lockfile installed by Docker; reuse the empty dev Postgres volume/password and generate only `SECRET_KEY`; run tests in the same PG18 container; run both Phase 5 evals; do all three small fixes; undismiss clears only `suggestion_dismissed`. When the supplied Gemini key failed on the Anthropic client, Dhruv chose to add Gemini as a second provider.

**What was done and verified for real:**
- `git init` against `origin/main` (remote was at Phase 4), fetched history, committed the local Phase 5 tree on top. `.gitignore` no longer ignores `docs/`, so spec + tracker + build loop are tracked. Baseline commit `21c1557`; final hardening commits pushed to `main`.
- Created `.env` from `.env.example` with the existing volume's dev password and a random 64-char `SECRET_KEY` (not printed, not committed). Provider keys stay out of git.
- Regenerated `backend/requirements.lock.txt` **inside the Linux image** (UTF-8, LF, 120 pins after adding google-genai 2.33.0, includes scikit-learn 1.9.1/joblib 1.6.0). `Dockerfile` and `requirements-dev.txt` now install the lock. Rebuilt the image successfully.
- Full `docker compose up -d --build`: backend, worker, frontend, SeaweedFS, Valkey, PG18.6 all healthy; `/health` = `api/database/cache: ok`; frontend HTTP 200.
- Real migrations `0001→0006` on PG18.6 (native `uuidv7()`), model trained (`classifier.joblib` + meta), then end-to-end smoke: signup → login → INR account → CSV upload → extraction → normalization → enrichment → 3 transactions → `/analytics/summary` (`income 90000.00`, `expense 1550.50`, `net 88449.50`) → `/documents/{id}/pages`.
- Full suite on PG18: **151 passed** (147 prior + 4 Gemini adapter/factory tests). Migration test covers 0006 both up and down.
- Fixes: migration `0006_merchant_alias_uniqueness` + model flag; `GET /transactions?date_to=` half-open upper bound; `POST /transactions/{id}/suggestion/undismiss` (409 when not dismissed, only clears the flag); README links/tree/API/test counts and backend README updated.
- Added `GeminiClassifier` + `get_llm_classifier()` and `--provider/--model` to `eval_llm`; Gemini uses the same validated JSON schema/parser as Anthropic, with bounded retries (429/5xx) and a 60 s timeout. `google-genai==2.33.0` pinned in the lock; `GEMINI_API_KEY`, `LLM_PROVIDER`, `LLM_GEMINI_MODEL` documented in `.env.example` (none committed).
- Ran both evals for real: public OOD 12,144 rows (coverage 0.4888, precision-on-answered 0.4862, abstain-as-wrong 0.2376); Gemini 3.5 Flash-Lite n=300 on synthetic holdout (hybrid 0.9133, LLM 0.9433, 0 abstentions). Artifacts: `backend/docs/ml_eval/public_ood.json`, `llm_synthetic.json`.

**Findings / corrections:**
- Host PowerShell could not reach `api.anthropic.com`/`huggingface.co` (timeouts), but the backend container could: Anthropic returned 401 (reachable, no key), HF returned 200. The earlier “network blocked” assumption was a host-only limitation, not a project one.
- The public HF dataset is now **gated**; the old “HF unreachable” gap is replaced by “needs HF_TOKEN + accepted terms”.
- Smoke initially showed uncategorized rows: the enrich task had not finished yet (it completed ~1s after normalization). Not a bug — the chain timing is expected; re-query showed `category_source='hybrid'` on all three.
- Four new tests explain 143 → 147 (0006 round-trip, date filter, undismiss, plus the undismiss endpoint added to the auth-isolation parameterization).

**Not done / still unverified:**
- Anthropic path (`claude-haiku-5-5`) has never been called; only Gemini is verified.
- Public OOD is a lossy-map signal, not an accuracy benchmark; real-statement accuracy remains unknown.
- Model is still not baked into the image; it is trained once into the bind-mounted `backend/models/`.

**State at end of session:** both evals are run and recorded, all 151 tests pass on PG18, and the tree is ready for Phase 6. Next: **Phase 6 — Forecasting**.

<!-- Next session: append a new "### Session N — YYYY-MM-DD" block below,
     update the Phase Roadmap checkboxes, and add any new rows to the
     Decisions Log / Known Gaps as they come up. -->
