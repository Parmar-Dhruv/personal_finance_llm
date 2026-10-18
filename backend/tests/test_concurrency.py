"""Uniqueness must hold under races (DB-enforced), and surface as 409 — never a 500."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app


def _race(user, path, payload, n=8):
    def call(_):
        # separate client per thread; TestClient isn't built for shared use across threads
        return TestClient(app).post(path, json=payload, headers=user.headers).status_code

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(call, range(n)))


def test_concurrent_duplicate_category_creates(alice):
    codes = _race(alice, "/categories", {"name": "Racey"})
    assert sorted(codes).count(201) == 1 and set(codes) <= {201, 409}, codes


def test_concurrent_duplicate_overall_budget_creates(alice):
    codes = _race(alice, "/budgets", {"currency": "INR", "amount": "100"})
    assert sorted(codes).count(201) == 1 and set(codes) <= {201, 409}, codes
