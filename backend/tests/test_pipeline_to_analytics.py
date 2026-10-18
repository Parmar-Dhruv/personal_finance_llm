"""
Phase 3 -> Phase 4 seam: transactions produced by the REAL normalization
engine (not hand-inserted rows) flow correctly into the analytics API.
"""

from app.db.models import Document, DocumentPage, DocumentStatus, ExtractionMethod
from app.pipeline.normalize.engine import normalize_document


def _statement(db, user, account_id, table):
    doc = Document(user_id=user.id, account_id=account_id, filename="stmt.csv", storage_path="x/y/stmt.csv",
                   mime_type="text/csv", status=DocumentStatus.processed, page_count=1)
    db.add(doc)
    db.flush()
    db.add(DocumentPage(document_id=doc.id, page_number=1, extraction_method=ExtractionMethod.tabular,
                        raw_text="", char_count=0, tables=[table], warnings=[]))
    db.commit()
    db.refresh(doc)
    return doc


def test_normalized_statement_feeds_analytics(alice, db):
    acct = alice.account("HDFC", "INR")
    table = [
        ["Date", "Description", "Debit", "Credit"],
        ["01/08/2026", "SALARY ACME CORP", "", "75,000.00"],
        ["03/08/2026", "AMZN MKTPLACE", "1,250.50", ""],
        ["15/08/2026", "AMAZON.COM PURCHASE", "749.50", ""],   # 15/08: DD/MM unambiguous
        ["02/09/2026", "SWIGGY ORDER 123", "400.00", ""],
    ]
    doc = _statement(db, alice, acct, table)
    assert normalize_document(db, doc) == 4
    db.commit()  # normalize_document leaves committing to its caller (the Celery task)

    (s,) = alice.get("/analytics/summary").json()
    assert (s["income"], s["expense"], s["net"]) == ("75000.00", "2400.00", "72600.00")

    aug = alice.get("/analytics/summary", params={"date_from": "2026-08-01", "date_to": "2026-08-31"}).json()[0]
    assert aug["expense"] == "2000.00"  # the 02/09 Swiggy row belongs to September

    (merchants,) = alice.get("/analytics/merchants").json()
    top = merchants["rows"][0]
    assert top["label"] == "Amazon" and top["total"] == "2000.00" and top["transaction_count"] == 2

    months = alice.get("/analytics/monthly").json()[0]["months"]
    assert [m["month"] for m in months] == ["2026-08-01", "2026-09-01"]
    assert months[1]["expense_change_pct"] == "-80.00"  # 2000.00 -> 400.00


def test_renormalizing_does_not_double_count(alice, db):
    acct = alice.account("HDFC", "INR")
    doc = _statement(db, alice, acct, [["Date", "Description", "Debit", "Credit"],
                                       ["03/08/2026", "SWIGGY", "100.00", ""]])
    normalize_document(db, doc)
    db.commit()
    normalize_document(db, doc)   # Phase 3 is idempotent; analytics must see one row
    db.commit()
    assert alice.get("/analytics/summary").json()[0]["expense"] == "100.00"


def test_deleting_account_removes_its_spend_from_analytics(alice, db, add_txn):
    keep, drop = alice.account("Keep"), alice.account("Drop")
    add_txn(alice, keep, "2026-08-01", "10.00")
    add_txn(alice, drop, "2026-08-01", "90.00")
    from sqlalchemy import text
    db.execute(text("DELETE FROM accounts WHERE id = :i"), {"i": drop})
    db.commit()
    assert alice.get("/analytics/summary").json()[0]["expense"] == "10.00"
