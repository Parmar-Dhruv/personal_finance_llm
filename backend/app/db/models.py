import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Float,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# PG18+ uuidv7() is time-ordered, which keeps B-tree index pages sequential
# on insert (unlike random v4 UUIDs, which fragment indexes badly on
# high-throughput tables like transactions). Requires the pg18 image —
# on <18 this default would need to fall back to gen_random_uuid().
PK_DEFAULT = text("uuidv7()")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AccountType(str, enum.Enum):
    checking = "checking"
    savings = "savings"
    credit_card = "credit_card"
    investment = "investment"
    loan = "loan"
    other = "other"


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    processed = "processed"
    failed = "failed"


class TransactionType(str, enum.Enum):
    debit = "debit"
    credit = "credit"


class NormalizationStatus(str, enum.Enum):
    pending = "pending"
    normalizing = "normalizing"
    normalized = "normalized"
    failed = "failed"
    # Extraction succeeded but normalization can't run yet — document has
    # no account attached, or the account's currency isn't one Phase 3
    # supports (INR/USD only). Distinct from "failed" because it's an
    # expected, recoverable state (assign an account / fix currency and
    # re-trigger via POST /documents/{id}/normalize), not an error.
    skipped = "skipped"


class ExtractionMethod(str, enum.Enum):
    # Text came straight out of the PDF's text layer.
    native_text = "native_text"
    # Page had no usable text layer (scanned/photographed) — rasterized
    # via pypdfium2 and run through Tesseract.
    ocr = "ocr"
    # CSV/XLSX — parsed directly as rows/columns, no OCR or text-layer
    # concept applies.
    tabular = "tabular"


# Phase 5 provenance vocabularies. Plain strings + CHECK constraints (not PG
# enums) so adding a value later is a one-line migration, not the
# ALTER TYPE ... ADD VALUE transaction restriction noted in Session 1.
CATEGORY_SOURCES = ("user", "rule", "ml", "hybrid", "llm")
DUPLICATE_REVIEWS = ("auto", "pending", "confirmed", "dismissed")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=PK_DEFAULT
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    accounts: Mapped[list["Account"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    categories: Mapped[list["Category"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=PK_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, name="account_type"), nullable=False
    )
    # ISO 4217 code (USD, EUR, INR...). Every amount in this account is
    # assumed to be in this currency — cross-currency handling happens at
    # the analytics layer, not here.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship(back_populates="accounts")
    documents: Mapped[list["Document"]] = relationship(back_populates="account")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    # Phase 4: replaces the Phase 1 UNIQUE(user_id, name, parent_id), which
    # never actually constrained anything for system rows or top-level
    # categories (Postgres treats NULLs as distinct in a plain UNIQUE).
    # NULLS NOT DISTINCT (PG15+) closes that hole, and lower(name) makes
    # "Food" and "food" the same category.
    __table_args__ = (
        Index(
            "uq_category_scope_name",
            "user_id",
            "parent_id",
            func.lower(text("name")),
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=PK_DEFAULT
    )
    # NULL user_id = system-provided default category, visible to everyone.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User | None"] = relationship(back_populates="categories")
    parent: Mapped["Category | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="category", foreign_keys="Transaction.category_id"
    )


class Budget(TimestampMixin, Base):
    """
    Phase 4 monthly budget. One row = one spending limit for one currency,
    scoped either to a category subtree or (category_id NULL) to all of the
    user's spending in that currency.

    Currency is part of the budget on purpose: analytics never converts
    between currencies (see Decisions Log, Phase 4), so a limit of "10000"
    is meaningless without saying which currency it's 10000 of.
    """

    __tablename__ = "budgets"
    __table_args__ = (
        # NULLS NOT DISTINCT so there can only be ONE overall budget per
        # (user, currency) — a plain UNIQUE would allow unlimited NULL-category
        # duplicates, the same trap Category/MerchantAlias fell into earlier.
        UniqueConstraint(
            "user_id",
            "category_id",
            "currency",
            name="uq_budget_user_category_currency",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("amount > 0", name="ck_budget_amount_positive"),
        CheckConstraint(
            "alert_threshold_pct > 0 AND alert_threshold_pct <= 100",
            name="ck_budget_threshold_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=PK_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL = overall budget. CASCADE (not SET NULL) on purpose: if a
    # category disappears, silently turning its budget into an "overall"
    # budget would be a nasty surprise.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Percent of the limit at which utilization flips from "ok" to "near".
    alert_threshold_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("80.00"), server_default="80.00"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship()
    category: Mapped["Category | None"] = relationship()


class MerchantAlias(TimestampMixin, Base):
    """
    Phase 3 merchant canonicalization. Same NULL-user_id-means-system
    pattern as Category: system-seeded aliases (is_system=True) are
    visible to every user, user-defined ones are private to their owner.

    `pattern` is a regex, matched case-insensitively against the start
    of the cleaned merchant text (see pipeline/normalize/merchants.py) —
    not a plain substring, so seed data can anchor with `^` to avoid
    over-matching (e.g. "^AMAZON" shouldn't also swallow an unrelated
    merchant that happens to contain "amazon" mid-string).
    """

    __tablename__ = "merchant_aliases"
    __table_args__ = (UniqueConstraint("user_id", "pattern", name="uq_merchant_alias_user_pattern"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=PK_DEFAULT
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User | None"] = relationship()


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=PK_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        nullable=False,
        default=DocumentStatus.uploaded,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Populated once Phase 2 extraction runs. NULL until then. For
    # spreadsheets this counts sheets, not physical pages.
    page_count: Mapped[int | None] = mapped_column(nullable=True)

    # Phase 3 — normalization pipeline status, separate from `status`
    # above (which only tracks extraction). A document can be
    # `processed` (extraction done) while `normalization_status` is
    # still `pending`/`skipped`.
    normalization_status: Mapped[NormalizationStatus] = mapped_column(
        Enum(NormalizationStatus, name="normalization_status"),
        nullable=False,
        default=NormalizationStatus.pending,
    )
    normalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    normalization_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_count: Mapped[int | None] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship(back_populates="documents")
    account: Mapped["Account | None"] = relationship(back_populates="documents")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="source_document")
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentPage.page_number",
    )


class DocumentPage(TimestampMixin, Base):
    """
    One row per extracted page (PDF page, image, or spreadsheet sheet).
    This is the provenance unit the spec calls for: every downstream
    Transaction row should be traceable back to a specific DocumentPage,
    not just a Document. Region-level (bbox) provenance within a page is
    deferred — `tables` stores extracted rows, not yet their coordinates.
    """

    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_document_page_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=PK_DEFAULT
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 1-indexed. For CSV (single implicit sheet) this is always 1; for
    # XLSX it's the sheet's position in the workbook.
    page_number: Mapped[int] = mapped_column(nullable=False)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        Enum(ExtractionMethod, name="extraction_method"), nullable=False
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_count: Mapped[int] = mapped_column(nullable=False, default=0)
    # Mean Tesseract word-confidence (0-100). NULL for native_text/tabular
    # pages, since there's no OCR confidence to report.
    ocr_confidence: Mapped[float | None] = mapped_column(nullable=True)
    # List of tables; each table is a list of rows; each row a list of
    # cell strings. Header row (if any) is just row 0 — not distinguished
    # at this layer, since that's a normalization-phase concern.
    tables: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # e.g. "low_ocr_confidence", "empty_page", "truncated_rows",
    # "decoded_as_latin-1" — surfaced to the user, not silently swallowed.
    warnings: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="pages")


class RecurringSeries(TimestampMixin, Base):
    """
    Phase 5: one detected recurring payment stream (subscription, rent, a
    utility, salary...). Fully derived data -- every detection run deletes
    and recreates a user's series, so ids are NOT stable across runs and
    nothing should store them long-term.
    """

    __tablename__ = "recurring_series"
    __table_args__ = (
        Index("ix_recurring_series_user_active", "user_id", "is_active"),
        CheckConstraint("occurrence_count >= 2", name="ck_recurring_occurrences"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=PK_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type", create_type=False), nullable=False
    )
    # weekly | biweekly | monthly | quarterly | yearly
    cadence: Mapped[str] = mapped_column(String(20), nullable=False)
    interval_days: Mapped[float] = mapped_column(Float, nullable=False)
    typical_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # True for bills whose amount drifts (utilities) rather than a fixed
    # subscription price.
    amount_variable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(nullable=False)
    first_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_expected_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # False once the stream has gone quiet for > 1.5 intervals as of the
    # user's latest transaction (cancelled subscription, moved flat).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_user_category", "user_id", "category_id"),
        CheckConstraint(
            "category_source IS NULL OR category_source IN ('user','rule','ml','hybrid','llm')",
            name="ck_transaction_category_source",
        ),
        CheckConstraint(
            "duplicate_review IS NULL OR duplicate_review IN ('auto','pending','confirmed','dismissed')",
            name="ck_transaction_duplicate_review",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=PK_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    # Provenance: which uploaded document this row was extracted from.
    # NULL means manually entered / not tied to a source document.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    # Self-reference for duplicate detection (Phase 5) — points at the
    # transaction this row is believed to duplicate.
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )

    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    merchant_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # NEVER use Float for money — binary floating point cannot represent
    # most decimal currency values exactly, and rounding errors compound
    # across aggregation. Numeric(precision, scale) is exact.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type"), nullable=False
    )

    confidence_score: Mapped[float | None] = mapped_column(nullable=True)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Phase 5: ML-layer provenance --------------------------------
    # Who set category_id: 'user' (never overwritten by any ML job) or the
    # classifier that auto-applied it ('rule'|'ml'|'hybrid'|'llm'). NULL iff
    # category_id is NULL.
    category_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    category_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # A below-auto-threshold prediction waiting for a human. Never read by
    # analytics -- only category_id is.
    suggested_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    suggested_category_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_category_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # User rejected the suggestion: classification runs skip this row.
    suggestion_dismissed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    # Duplicate detection. duplicate_of_id (above) is what analytics honors;
    # these record why, and what a human decided.
    duplicate_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    duplicate_candidate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    duplicate_review: Mapped[str | None] = mapped_column(String(20), nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Baseline used for the score (level, n, median, mad...) so a flag is
    # explainable without re-running the detector.
    anomaly_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recurring_series_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recurring_series.id", ondelete="SET NULL"), nullable=True
    )

    # Unstructured extraction payload (raw OCR/parser output) kept for
    # audit/debugging without polluting the typed schema above.
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped["User"] = relationship(back_populates="transactions")
    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category | None"] = relationship(
        back_populates="transactions", foreign_keys=[category_id]
    )
    source_document: Mapped["Document | None"] = relationship(back_populates="transactions")
    duplicate_of: Mapped["Transaction | None"] = relationship(
        remote_side=[id], foreign_keys=[duplicate_of_id]
    )
