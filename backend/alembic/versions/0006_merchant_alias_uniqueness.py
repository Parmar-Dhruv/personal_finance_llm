"""MerchantAlias scope uniqueness (pre-Phase-6 hardening)

Revision ID: 0006_merchant_alias_uniqueness
Revises: 0005_ml_layer
Create Date: 2026-10-28

Plain UNIQUE(user_id, pattern) never constrained system aliases: with
user_id NULL, Postgres treats every row as distinct. Recreate it with
NULLS NOT DISTINCT (PG15+; project targets PG18) so a seeded pattern
cannot be duplicated at the system level, matching the Category fix in
0004 and the Budget constraint.
"""
from alembic import op

revision = "0006_merchant_alias_uniqueness"
down_revision = "0005_ml_layer"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_merchant_alias_user_pattern"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "merchant_aliases", type_="unique")
    op.execute(
        f"ALTER TABLE merchant_aliases ADD CONSTRAINT {_CONSTRAINT} "
        "UNIQUE NULLS NOT DISTINCT (user_id, pattern)"
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "merchant_aliases", type_="unique")
    op.create_unique_constraint(_CONSTRAINT, "merchant_aliases", ["user_id", "pattern"])
