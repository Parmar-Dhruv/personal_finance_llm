"""Account opening balance (Phase 6, forecasting)

Revision ID: 0007_account_balance
Revises: 0006_merchant_alias_uniqueness
Create Date: 2026-10-31

The schema had no balance data at all: a forecast can say what the *flows*
will be, but "can I afford next month?" needs a starting point. The user
supplies one number and the date it was true on; every later balance is
derived from transactions (never stored, so it cannot go stale).

Signed on purpose: positive = money held, negative = money owed (a credit
card the user owes 5,000 on is -5000). Debits lower it, credits raise it,
which is the same rule for every account type.

opening_balance and balance_as_of are meaningless without each other, so a
CHECK forces both-or-neither instead of trusting the API layer alone.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_account_balance"
down_revision = "0006_merchant_alias_uniqueness"
branch_labels = None
depends_on = None

_CHECK = "ck_account_balance_pair"


def upgrade() -> None:
    op.add_column("accounts", sa.Column("opening_balance", sa.Numeric(14, 2), nullable=True))
    op.add_column("accounts", sa.Column("balance_as_of", sa.Date(), nullable=True))
    op.create_check_constraint(
        _CHECK, "accounts", "(opening_balance IS NULL) = (balance_as_of IS NULL)"
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK, "accounts", type_="check")
    op.drop_column("accounts", "balance_as_of")
    op.drop_column("accounts", "opening_balance")
