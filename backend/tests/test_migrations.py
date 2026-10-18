"""
Migration round-trip against a real, separate database (so it can't disturb
the shared test schema): base -> head, head -> 0003 -> head, with the
Phase 4 constraints checked at the SQL level, not through the API.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from tests.conftest import BACKEND_DIR, TEST_DB_URL

MIG_URL = str(make_url(TEST_DB_URL).set(database="finsight_migration_test").render_as_string(hide_password=False))


def alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": MIG_URL}
    out = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


@pytest.fixture(scope="module")
def engine():
    admin = create_engine(MIG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
        if not c.execute(text("SELECT count(*) FROM pg_proc WHERE proname='uuidv7'")).scalar():
            c.execute(text("CREATE FUNCTION uuidv7() RETURNS uuid LANGUAGE sql AS 'SELECT gen_random_uuid()'"))
    yield admin
    admin.dispose()


def _scalar(engine, sql):
    with engine.connect() as c:
        return c.execute(text(sql)).scalar()


def test_full_chain_and_roundtrip(engine):
    alembic("upgrade", "head")
    assert _scalar(engine, "SELECT version_num FROM alembic_version") == "0004_analytics_budgets"
    assert _scalar(engine, "SELECT count(*) FROM categories WHERE is_system AND user_id IS NULL") == 10

    # Phase 4 constraints, exercised in raw SQL
    with engine.begin() as c:
        c.execute(text("INSERT INTO users (email, hashed_password) VALUES ('m@x.com', 'h')"))
    uid = _scalar(engine, "SELECT id FROM users WHERE email='m@x.com'")
    ins = "INSERT INTO budgets (user_id, category_id, currency, amount) VALUES ('{u}', {c}, 'INR', {a})"
    with engine.begin() as c:
        c.execute(text(ins.format(u=uid, c="NULL", a="10")))
    for sql in (
        ins.format(u=uid, c="NULL", a="20"),                                   # 2nd overall budget (NULLS NOT DISTINCT)
        ins.format(u=uid, c="NULL", a="0"),                                    # amount must be > 0
        "INSERT INTO categories (name, is_system) VALUES ('FOOD', true)",      # lower(name) dup of a system category
    ):
        with pytest.raises(IntegrityError):
            with engine.begin() as c:
                c.execute(text(sql))

    alembic("downgrade", "0003_normalization")
    assert _scalar(engine, "SELECT to_regclass('public.budgets')") is None
    assert _scalar(engine, "SELECT count(*) FROM categories") == 0
    assert _scalar(engine, "SELECT count(*) FROM pg_constraint WHERE conname='uq_category_user_name_parent'") == 1
    assert _scalar(engine, "SELECT count(*) FROM pg_indexes WHERE indexname='uq_category_scope_name'") == 0

    alembic("upgrade", "head")
    assert _scalar(engine, "SELECT count(*) FROM categories WHERE is_system") == 10
    assert _scalar(engine, "SELECT to_regclass('public.budgets')") is not None
