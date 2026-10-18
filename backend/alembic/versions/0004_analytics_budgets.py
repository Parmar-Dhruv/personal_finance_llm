"""budgets + category hardening + system categories (Phase 4 — analytics)

Revision ID: 0004_analytics_budgets
Revises: 0003_normalization
Create Date: 2026-10-18

Requires PostgreSQL 15+ (UNIQUE ... NULLS NOT DISTINCT). The project
targets PG18, so this is not a new floor in practice.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_analytics_budgets"
down_revision = "0003_normalization"
branch_labels = None
depends_on = None

# The category list from the spec (personal_finance_llm.md §7.1). Seeded as
# system categories (user_id NULL, is_system true) so every user can assign
# them today and the Phase 5 classifier has a fixed label set to predict.
_SYSTEM_CATEGORIES = [
    "Food",
    "Transportation",
    "Shopping",
    "Utilities",
    "Entertainment",
    "Healthcare",
    "Travel",
    "Rent",
    "Salary",
    "Business expenses",
]


def upgrade() -> None:
    # Replace the Phase 1 UNIQUE(user_id, name, parent_id): with NULLs
    # distinct it never enforced anything for system or top-level rows.
    op.drop_constraint("uq_category_user_name_parent", "categories", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_category_scope_name "
        "ON categories (user_id, parent_id, lower(name)) NULLS NOT DISTINCT"
    )

    categories = sa.table(
        "categories",
        sa.column("name", sa.String),
        sa.column("is_system", sa.Boolean),
    )
    op.bulk_insert(categories, [{"name": n, "is_system": True} for n in _SYSTEM_CATEGORIES])

    op.create_table(
        "budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("alert_threshold_pct", sa.Numeric(5, 2), nullable=False, server_default="80.00"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_budget_amount_positive"),
        sa.CheckConstraint(
            "alert_threshold_pct > 0 AND alert_threshold_pct <= 100",
            name="ck_budget_threshold_range",
        ),
    )
    op.create_index("ix_budgets_user_id", "budgets", ["user_id"])
    op.execute(
        "ALTER TABLE budgets ADD CONSTRAINT uq_budget_user_category_currency "
        "UNIQUE NULLS NOT DISTINCT (user_id, category_id, currency)"
    )

    # Serves the analytics "group by category" queries and the recursive
    # category-subtree lookups used by budget utilization.
    op.create_index("ix_transactions_user_category", "transactions", ["user_id", "category_id"])
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_categories_parent_id", table_name="categories")
    op.drop_index("ix_transactions_user_category", table_name="transactions")
    op.drop_table("budgets")

    # Only the seeded rows: system categories with no user and no parent.
    # Transactions pointing at them fall back to uncategorized (FK is
    # ON DELETE SET NULL).
    op.execute("DELETE FROM categories WHERE is_system AND user_id IS NULL")
    op.execute("DROP INDEX uq_category_scope_name")
    op.create_unique_constraint(
        "uq_category_user_name_parent", "categories", ["user_id", "name", "parent_id"]
    )
