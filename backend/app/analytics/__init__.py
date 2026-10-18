"""
Phase 4 — deterministic financial analytics.

Everything here is plain SQL + Decimal arithmetic. No ML, no LLM, no
floats. The functions take a SQLAlchemy Session and a `Scope` and return
dataclasses, with no FastAPI imports, so Phase 8's agent can wrap them as
tools without going through HTTP.

Conventions every function in this package follows (also in the README):

- Per-currency results. Totals in different currencies are NEVER added
  together or converted; every result is keyed by currency.
- Transactions flagged `duplicate_of_id IS NOT NULL` are excluded.
- `Transaction.amount` is always a positive magnitude; direction is
  `transaction_type` (credit = income, debit = expense).
- Dates are calendar dates; the pipeline stores them as midnight UTC, so
  month bucketing is done in UTC.
"""
