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
      schemas/ (auth.py, document.py)
      api/ (auth.py, documents.py, deps.py)
      pipeline/ (tasks.py)
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
- **Phase 2 — Document Intelligence** ⬜ *(next up)*
  - ⬜ Text/table extraction for native PDFs/CSV/XLSX
  - ⬜ OCR for scanned docs (Tesseract baseline; eval decides if cloud OCR needed)
  - ⬜ Field identification + confidence scoring
  - ⬜ Provenance linking (doc → page → region)
- **Phase 3 — Normalization** ⬜
  - ⬜ Date/amount/currency normalization
  - ⬜ Merchant canonicalization
  - ⬜ Normalized transaction schema populated end-to-end
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

<!-- Next session: append a new "### Session N — YYYY-MM-DD" block below,
     update the Phase Roadmap checkboxes, and add any new rows to the
     Decisions Log / Known Gaps as they come up. -->
