"""GET /transactions date filtering (whole-day inclusive upper bound)."""

from sqlalchemy import text


def test_date_to_includes_the_whole_calendar_day(alice, add_txn, db):
    acct = alice.account()
    on_day = add_txn(alice, acct, "2026-03-05", "10.00")
    next_day = add_txn(alice, acct, "2026-03-06", "20.00")
    db.execute(
        text("UPDATE transactions SET transaction_date = '2026-03-05 23:59:59+00' WHERE id = :i"),
        {"i": on_day},
    )
    db.commit()

    r = alice.get("/transactions", params={"date_from": "2026-03-05", "date_to": "2026-03-05"})
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [on_day]

    r = alice.get("/transactions", params={"date_to": "2026-03-05"})
    ids = [x["id"] for x in r.json()]
    assert on_day in ids and next_day not in ids

    r = alice.get("/transactions", params={"date_from": "2026-03-06"})
    assert [x["id"] for x in r.json()] == [next_day]
