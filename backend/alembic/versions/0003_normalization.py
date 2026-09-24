"""normalization (Phase 3 — data normalization)

Revision ID: 0003_normalization
Revises: 0002_document_pages
Create Date: 2026-09-22

"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_normalization"
down_revision = "0002_document_pages"
branch_labels = None
depends_on = None

# A small hand-written seed list, not an external merchant-data source
# (avoids a licensing/currency research detour for what's a portfolio
# project). Patterns are regexes anchored with ^ so they match the start
# of the cleaned merchant text without over-matching substrings
# elsewhere in a longer description. Mix of US and Indian merchants,
# matching the INR/USD scope decided for Phase 3.
_SEED_ALIASES = [
    (r"^amzn|^amazon", "Amazon"),
    (r"^wal-?mart|^wmt", "Walmart"),
    (r"^target", "Target"),
    (r"^starbucks|^sbux", "Starbucks"),
    (r"^uber(?!\s?eats)", "Uber"),
    (r"^uber\s?eats", "Uber Eats"),
    (r"^netflix", "Netflix"),
    (r"^spotify", "Spotify"),
    (r"^costco", "Costco"),
    (r"^mcdonald", "McDonald's"),
    (r"^apple\.com|^apple\s?store", "Apple"),
    (r"^google\s?(?:play|storage|youtube)?", "Google"),
    (r"^swiggy", "Swiggy"),
    (r"^zomato", "Zomato"),
    (r"^flipkart", "Flipkart"),
    (r"^myntra", "Myntra"),
    (r"^irctc", "IRCTC"),
    (r"^bigbasket", "BigBasket"),
    (r"^ola\b", "Ola"),
    (r"^reliance\s?(?:jio|digital|fresh|retail)?", "Reliance"),
    (r"^dmart|^avenue\s?supermart", "DMart"),
]


def upgrade() -> None:
    normalization_status = postgresql.ENUM(
        "pending", "normalizing", "normalized", "failed", "skipped", name="normalization_status"
    )
    normalization_status.create(op.get_bind())

    op.add_column(
        "documents",
        sa.Column(
            "normalization_status",
            normalization_status,
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("documents", sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("normalization_error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("transaction_count", sa.Integer(), nullable=True))

    op.create_table(
        "merchant_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("pattern", sa.String(255), nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "pattern", name="uq_merchant_alias_user_pattern"),
    )
    op.create_index("ix_merchant_aliases_user_id", "merchant_aliases", ["user_id"])

    merchant_aliases_table = sa.table(
        "merchant_aliases",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("pattern", sa.String),
        sa.column("canonical_name", sa.String),
        sa.column("is_system", sa.Boolean),
    )
    op.bulk_insert(
        merchant_aliases_table,
        [
            {
                "id": uuid.uuid4(),
                "user_id": None,
                "pattern": pattern,
                "canonical_name": canonical_name,
                "is_system": True,
            }
            for pattern, canonical_name in _SEED_ALIASES
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_merchant_aliases_user_id", table_name="merchant_aliases")
    op.drop_table("merchant_aliases")
    op.drop_column("documents", "transaction_count")
    op.drop_column("documents", "normalization_error")
    op.drop_column("documents", "normalized_at")
    op.drop_column("documents", "normalization_status")
    op.execute("DROP TYPE IF EXISTS normalization_status")
