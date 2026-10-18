"""
Test harness: REAL Postgres, REAL HTTP stack (FastAPI TestClient), real
Alembic migrations. No mocks.

Needs a running Postgres (15+) with the pgvector extension available and a
database whose name ends in `_test` — the schema is dropped and rebuilt, so
the suffix check below stops this from ever touching a dev database.

    TEST_DATABASE_URL=postgresql+psycopg://user:pw@localhost:5432/finsight_test pytest

The one test-only substitution: on Postgres < 18 there is no native
`uuidv7()` (production target is PG18), so a `gen_random_uuid()`-backed
polyfill is created in the *test database only*. It never touches the
shipped migrations.
"""

import os
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://finsight:finsight_dev_password@localhost:5432/finsight_test",
)
if not (make_url(TEST_DB_URL).database or "").endswith("_test"):
    raise RuntimeError("Refusing to run: test database name must end with '_test'")
os.environ["DATABASE_URL"] = TEST_DB_URL  # must be set before app.* is imported

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402
from app.db.models import Transaction, TransactionType  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent


def build_schema(url: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        has_native = conn.execute(text("SELECT count(*) FROM pg_proc WHERE proname = 'uuidv7'")).scalar()
        if not has_native:  # PG < 18: test-only polyfill, see module docstring
            conn.execute(text("CREATE FUNCTION uuidv7() RETURNS uuid LANGUAGE sql AS 'SELECT gen_random_uuid()'"))
    engine.dispose()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    build_schema(TEST_DB_URL)


@pytest.fixture(autouse=True)
def _clean_users():
    yield
    # Everything user-owned cascades from users. System categories
    # (user_id NULL) survive, as they do in production.
    with SessionLocal() as db:
        db.execute(text("DELETE FROM users"))
        db.commit()


@pytest.fixture
def client() -> TestClient:
    # Deliberately NOT used as a context manager: that would fire the
    # startup hook, which needs object storage (irrelevant to Phase 4).
    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


class User:
    def __init__(self, client: TestClient, email: str):
        pw = "correct-horse-battery"
        assert client.post("/auth/signup", json={"email": email, "password": pw}).status_code == 201
        r = client.post("/auth/login", data={"username": email, "password": pw})
        assert r.status_code == 200, r.text
        self.headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.client = client
        self.id = client.get("/auth/me", headers=self.headers).json()["id"]

    def get(self, url, **kw):
        return self.client.get(url, headers=self.headers, **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers=self.headers, **kw)

    def patch(self, url, **kw):
        return self.client.patch(url, headers=self.headers, **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self.headers, **kw)

    def account(self, name="Main", currency="INR", type_="checking") -> str:
        r = self.post("/accounts", json={"name": name, "account_type": type_, "currency": currency})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def category(self, name, parent_id=None) -> str:
        r = self.post("/categories", json={"name": name, "parent_id": parent_id})
        assert r.status_code == 201, r.text
        return r.json()["id"]


@pytest.fixture
def alice(client) -> User:
    return User(client, "alice@example.com")


@pytest.fixture
def bob(client) -> User:
    return User(client, "bob@example.com")


@pytest.fixture
def add_txn(db):
    """Insert a transaction directly (what the Phase 3 pipeline would have written)."""

    def _add(user: User, account_id: str, on: str, amount: str, kind: str = "debit", *,
             currency: str = "INR", merchant: str | None = None, category_id: str | None = None,
             duplicate_of=None) -> str:
        y, m, d = (int(x) for x in on.split("-"))
        txn = Transaction(
            user_id=user.id,
            account_id=account_id,
            category_id=category_id,
            transaction_date=datetime.combine(date(y, m, d), time.min, tzinfo=timezone.utc),
            description_raw=merchant or "test txn",
            merchant_normalized=merchant,
            amount=Decimal(amount),
            currency=currency,
            transaction_type=TransactionType(kind),
            duplicate_of_id=duplicate_of,
        )
        db.add(txn)
        db.commit()
        return str(txn.id)

    return _add
