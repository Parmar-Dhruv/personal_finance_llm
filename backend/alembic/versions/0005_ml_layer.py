"""ML layer: category/duplicate/anomaly/recurring provenance (Phase 5)

Revision ID: 0005_ml_layer
Revises: 0004_analytics_budgets
Create Date: 2026-10-26

Everything here is additive. No existing column changes meaning, except
that `category_source` is backfilled to 'user' for rows that already have a
category (the only way a category could be set before Phase 5 was a human
calling PATCH /transactions/{id}), and rows that already carry a
`duplicate_of_id` are backfilled to duplicate_review='confirmed' (set by
hand before any detector existed).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_ml_layer"
down_revision = "0004_analytics_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recurring_series",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("merchant", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        # Reuses the existing PG enum created in 0001.
        sa.Column(
            "transaction_type",
            postgresql.ENUM("debit", "credit", name="transaction_type", create_type=False),
            nullable=False,
        ),
        sa.Column("cadence", sa.String(20), nullable=False),
        sa.Column("interval_days", sa.Float, nullable=False),
        sa.Column("typical_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("amount_variable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("occurrence_count", sa.Integer, nullable=False),
        sa.Column("first_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_expected_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("occurrence_count >= 2", name="ck_recurring_occurrences"),
    )
    op.create_index("ix_recurring_series_user_active", "recurring_series", ["user_id", "is_active"])

    op.add_column("transactions", sa.Column("category_source", sa.String(20), nullable=True))
    op.add_column("transactions", sa.Column("category_confidence", sa.Float, nullable=True))
    op.add_column(
        "transactions",
        sa.Column("suggested_category_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("transactions", sa.Column("suggested_category_confidence", sa.Float, nullable=True))
    op.add_column("transactions", sa.Column("suggested_category_source", sa.String(20), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("suggestion_dismissed", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column("transactions", sa.Column("duplicate_score", sa.Float, nullable=True))
    op.add_column(
        "transactions",
        sa.Column("duplicate_candidate_of_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("transactions", sa.Column("duplicate_review", sa.String(20), nullable=True))
    op.add_column("transactions", sa.Column("anomaly_score", sa.Float, nullable=True))
    op.add_column("transactions", sa.Column("anomaly_detail", postgresql.JSONB, nullable=True))
    op.add_column(
        "transactions",
        sa.Column("recurring_series_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("recurring_series.id", ondelete="SET NULL"), nullable=True),
    )

    op.create_check_constraint(
        "ck_transaction_category_source", "transactions",
        "category_source IS NULL OR category_source IN ('user','rule','ml','hybrid','llm')",
    )
    op.create_check_constraint(
        "ck_transaction_duplicate_review", "transactions",
        "duplicate_review IS NULL OR duplicate_review IN ('auto','pending','confirmed','dismissed')",
    )

    op.execute("UPDATE transactions SET category_source = 'user' WHERE category_id IS NOT NULL")
    op.execute(
        "UPDATE transactions SET duplicate_review = 'confirmed', duplicate_candidate_of_id = duplicate_of_id "
        "WHERE duplicate_of_id IS NOT NULL"
    )

    # Partial indexes: the review queues are tiny relative to the table.
    op.execute(
        "CREATE INDEX ix_transactions_dup_pending ON transactions (user_id) "
        "WHERE duplicate_review = 'pending'"
    )
    op.execute(
        "CREATE INDEX ix_transactions_suggestions ON transactions (user_id) "
        "WHERE suggested_category_id IS NOT NULL"
    )
    # Self-referencing FKs (ON DELETE SET NULL) need an index on the referencing
    # column or every deleted transaction triggers a full-table scan: measured,
    # deleting one user's 100k transactions took >15 min without these. Partial,
    # because almost every row is NULL here.
    op.execute("CREATE INDEX ix_transactions_duplicate_of ON transactions (duplicate_of_id) WHERE duplicate_of_id IS NOT NULL")
    op.execute(
        "CREATE INDEX ix_transactions_duplicate_candidate_of ON transactions (duplicate_candidate_of_id) "
        "WHERE duplicate_candidate_of_id IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_transactions_anomalies ON transactions (user_id) WHERE is_anomaly")
    op.create_index("ix_transactions_recurring_series", "transactions", ["recurring_series_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_recurring_series", table_name="transactions")
    op.execute("DROP INDEX ix_transactions_duplicate_candidate_of")
    op.execute("DROP INDEX ix_transactions_duplicate_of")
    op.execute("DROP INDEX ix_transactions_anomalies")
    op.execute("DROP INDEX ix_transactions_suggestions")
    op.execute("DROP INDEX ix_transactions_dup_pending")
    op.drop_constraint("ck_transaction_duplicate_review", "transactions", type_="check")
    op.drop_constraint("ck_transaction_category_source", "transactions", type_="check")
    for col in (
        "recurring_series_id", "anomaly_detail", "anomaly_score", "duplicate_review",
        "duplicate_candidate_of_id", "duplicate_score", "suggestion_dismissed",
        "suggested_category_source", "suggested_category_confidence", "suggested_category_id",
        "category_confidence", "category_source",
    ):
        op.drop_column("transactions", col)
    op.drop_index("ix_recurring_series_user_active", table_name="recurring_series")
    op.drop_table("recurring_series")
