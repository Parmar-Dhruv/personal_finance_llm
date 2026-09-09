# FinSight — Phase 0 Scaffold

This is the foundation layer only: infra, auth stub not yet included, and a
health-check wire-up proving frontend → backend → Postgres(+pgvector) →
Valkey all talk to each other. No document processing, no ML, no agent yet —
that's Phases 1+.

## Before first run — verify these

Marked `[VERIFY]` in the compose file because they were not checked against
Docker Hub at generation time:

- `pgvector/pgvector:pg18` — confirm this tag exists; pgvector's images are
  tagged per Postgres major version, and pg18 support may lag behind the
  Postgres 18 release. Fall back to `pg17` and downgrade `POSTGRES_DB` init
  if not yet published.
  `[VERIFIED]`
- `valkey/valkey:8` — confirm current stable tag.
  `[VERIFIED]`
- Frontend `package.json` versions (`next@^15`, etc.) — run `npm install`
  and let npm resolve actual latest; don't treat these as pinned facts.

## Run it

```bash
cp .env.example .env
# fill in POSTGRES_PASSWORD, SECRET_KEY, ANTHROPIC_API_KEY, VOYAGE_API_KEY

docker compose up --build
```

Then:
- Frontend: http://localhost:3000 — should show DB/cache status as `ok`
- Backend health: http://localhost:8000/health
- Backend root: http://localhost:8000/

## Apply the schema

After `docker compose up`, run the migration inside the backend container:

```bash
docker compose exec backend alembic upgrade head
```

This creates `users`, `accounts`, `categories`, `documents`, `transactions`,
and enables the `vector` extension (unused until the RAG phase, enabled now
so later migrations don't need to add it).

## Auth

Endpoints now live at:
- `POST /auth/signup` — `{email, password, full_name?}` → 201 + user object. Password must be ≥8 chars (length over composition rules, per NIST SP 800-63B).
- `POST /auth/login` — OAuth2 password form (`username`=email, `password`) → `{access_token, token_type}`. Token expires in `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30).
- `GET /auth/me` — requires `Authorization: Bearer <token>` → current user.

Passwords are hashed with Argon2id via `pwdlib` (not `passlib` — see the
comment in `requirements.txt`). JWTs are signed with `SECRET_KEY`/HS256 via
`PyJWT`. Set a real, random `SECRET_KEY` in `.env` before deploying anywhere
— the default in `.env.example` is a placeholder.

Not yet implemented: refresh tokens, logout/token revocation, password
reset, email verification, and **rate limiting on `/login`** — the endpoint
has no lockout or throttling, so it's currently brute-forceable. Don't
expose this outside a trusted network until that's added. Access tokens
are short-lived (30 min) as a partial mitigation for having no revocation
mechanism yet.

## Documents (upload / object storage)

Endpoints:
- `POST /documents/upload` — multipart file upload, optional `account_id`
  query param. Validates MIME type (`ALLOWED_UPLOAD_MIME_TYPES`) and size
  (`MAX_UPLOAD_SIZE_MB`, default 25MB) before touching object storage.
  Creates the `Document` row, uploads to SeaweedFS, then queues
  `process_document` on Celery.
- `GET /documents` — current user's documents, newest first.
- `GET /documents/{id}` — single document (404, not 403, if it belongs to
  someone else — no existence leak).
- `GET /documents/{id}/download-url` — presigned S3 URL, 5 min expiry.
- `DELETE /documents/{id}` — removes both the object and the DB row.

Object storage is SeaweedFS's S3 gateway (`chrislusf/seaweedfs:4.31`),
not MinIO — MinIO's Docker images were discontinued in Oct 2025 and the
project entered maintenance mode in Dec 2025. Bucket creation is handled
by the app itself on startup (`ensure_bucket_exists()`), not the
container — SeaweedFS doesn't auto-create buckets any more than real S3
does.

**Verified for real, not assumed:** every S3 operation (bucket create,
put, list, get, presigned URL, delete) was tested against the actual
SeaweedFS 4.31 binary before this code was written, and the full upload
flow was re-verified end-to-end afterward — signup → login → upload →
Celery processing → status transition → presigned download → byte-for-
byte content match → cross-user access blocked (404) → delete. All via
real Postgres, a real running SeaweedFS S3 gateway, and real Celery task
execution (eager mode locally; broker-backed in Docker).

The Celery task (`process_document`) is a **stub** — it flips
`uploaded → processing → processed` with no real work in between. Actual
OCR/extraction lands in Phase 2.

## What's deliberately not here yet

- Upload endpoint + object storage for documents
- Refresh tokens / logout / password reset
- Row-Level Security policies at the DB level (isolation is currently
  enforced only in application code via `user_id` filters — audit every
  query site before this goes anywhere near production data)
- Actual document extraction (OCR, table parsing) — Phase 2
- Retry/backoff policy for failed Celery tasks beyond `max_retries=3`
  (no exponential backoff configured yet)

## Next component

1. Phase 2: document text/table extraction, OCR for scanned docs.
