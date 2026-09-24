from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
import redis

from app.api.accounts import router as accounts_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.transactions import router as transactions_router
from app.core.config import settings
from app.core.storage import ensure_bucket_exists

app = FastAPI(title="FinSight API", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(documents_router)
app.include_router(transactions_router)


@app.on_event("startup")
def on_startup() -> None:
    ensure_bucket_exists()


@app.get("/health")
def health() -> dict:
    """
    Verifies the app can actually reach Postgres and Valkey, not just that
    the process is alive. A 200 here means Phase 0 infra is wired correctly.
    """
    status = {"api": "ok", "database": "unknown", "cache": "unknown"}

    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — surfacing raw error is intentional here
        status["database"] = f"error: {exc}"

    try:
        r = redis.Redis.from_url(settings.valkey_url)
        r.ping()
        status["cache"] = "ok"
    except Exception as exc:  # noqa: BLE001
        status["cache"] = f"error: {exc}"

    return status


@app.get("/")
def root() -> dict:
    return {"service": "finsight-api", "status": "running"}
