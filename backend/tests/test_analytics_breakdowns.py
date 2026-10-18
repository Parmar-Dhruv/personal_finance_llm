def test_category_breakdown_with_uncategorized(alice, add_txn):
    acct = alice.account()
    food, travel = alice.category("Groceries"), alice.category("Trips")
    add_txn(alice, acct, "2026-08-01", "600.00", category_id=food)
    add_txn(alice, acct, "2026-08-02", "200.00", category_id=food)
    add_txn(alice, acct, "2026-08-03", "150.00", category_id=travel)
    add_txn(alice, acct, "2026-08-04", "50.00")  # uncategorized
    add_txn(alice, acct, "2026-08-05", "9999.00", "credit", category_id=food)  # credits excluded by default
    (cur,) = alice.get("/analytics/categories").json()
    assert cur["total"] == "1000.00" and cur["transaction_type"] == "debit"
    labels = [(r["label"], r["total"], r["pct_of_total"], r["transaction_count"]) for r in cur["rows"]]
    assert labels == [
        ("Groceries", "800.00", "80.00", 2),
        ("Trips", "150.00", "15.00", 1),
        ("Uncategorized", "50.00", "5.00", 1),
    ]
    assert [r["key_id"] for r in cur["rows"]][2] is None
    assert cur["other_total"] == "0.00"


def test_category_breakdown_credit_type_and_limit(alice, add_txn):
    acct = alice.account()
    cats = [alice.category(n) for n in ("A", "B", "C")]
    for c, amt in zip(cats, ("300.00", "200.00", "100.00")):
        add_txn(alice, acct, "2026-08-01", amt, "credit", category_id=c)
    (cur,) = alice.get("/analytics/categories", params={"type": "credit", "limit": 2}).json()
    assert cur["total"] == "600.00"  # total covers all rows, not just the shown ones
    assert [r["label"] for r in cur["rows"]] == ["A", "B"]
    assert cur["other_total"] == "100.00" and cur["other_count"] == 1


def test_breakdown_ties_are_deterministic(alice, add_txn):
    acct = alice.account()
    for name in ("Zed", "Alpha", "Mid"):
        add_txn(alice, acct, "2026-08-01", "10.00", merchant=name)
    (cur,) = alice.get("/analytics/merchants").json()
    assert [r["label"] for r in cur["rows"]] == ["Alpha", "Mid", "Zed"]


def test_merchant_breakdown_top_n_and_unknown(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-08-01", "100.00", merchant="Amazon")
    add_txn(alice, acct, "2026-08-02", "50.00", merchant="Amazon")
    add_txn(alice, acct, "2026-08-03", "70.00", merchant="Swiggy")
    add_txn(alice, acct, "2026-08-04", "5.00")  # NULL merchant
    (cur,) = alice.get("/analytics/merchants", params={"limit": 2}).json()
    assert [(r["label"], r["total"]) for r in cur["rows"]] == [("Amazon", "150.00"), ("Swiggy", "70.00")]
    assert cur["other_total"] == "5.00" and cur["total"] == "225.00"
    (full,) = alice.get("/analytics/merchants").json()
    assert "(unknown merchant)" in [r["label"] for r in full["rows"]]


def test_breakdown_currencies_separate(alice, add_txn):
    inr, usd = alice.account("i", "INR"), alice.account("u", "USD")
    add_txn(alice, inr, "2026-08-01", "100.00", merchant="Amazon", currency="INR")
    add_txn(alice, usd, "2026-08-01", "7.00", merchant="Amazon", currency="USD")
    res = {c["currency"]: c for c in alice.get("/analytics/merchants").json()}
    assert res["INR"]["total"] == "100.00" and res["USD"]["total"] == "7.00"


def test_breakdown_respects_date_range(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-07-31", "999.00", merchant="Old")
    add_txn(alice, acct, "2026-08-01", "1.00", merchant="New")
    (cur,) = alice.get("/analytics/merchants", params={"date_from": "2026-08-01"}).json()
    assert [r["label"] for r in cur["rows"]] == ["New"]


def test_breakdown_limit_validation(alice):
    assert alice.get("/analytics/merchants", params={"limit": 0}).status_code == 422
    assert alice.get("/analytics/categories", params={"limit": 100000}).status_code == 422
    assert alice.get("/analytics/categories", params={"type": "refund"}).status_code == 422


def test_account_summaries_include_idle_account(alice, bob, add_txn):
    busy, idle = alice.account("Busy"), alice.account("Idle")
    add_txn(alice, busy, "2026-08-01", "100.00", "credit")
    add_txn(alice, busy, "2026-08-02", "40.00", "debit")
    bob.account("Bobs")
    rows = {r["account_name"]: r for r in alice.get("/analytics/accounts").json()}
    assert set(rows) == {"Busy", "Idle"}  # bob's account never appears
    assert rows["Busy"]["net"] == "60.00" and rows["Busy"]["income_count"] == 1
    assert rows["Idle"]["income"] == "0.00" and rows["Idle"]["expense_count"] == 0
    assert rows["Idle"]["account_id"] == idle


def test_account_summaries_date_filter_keeps_account_listed(alice, add_txn):
    acct = alice.account("A")
    add_txn(alice, acct, "2026-01-01", "10.00")
    (row,) = alice.get("/analytics/accounts", params={"date_from": "2026-06-01"}).json()
    assert row["expense"] == "0.00"
