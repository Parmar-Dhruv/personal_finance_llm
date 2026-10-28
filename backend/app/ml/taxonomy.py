"""The fixed label set. Mirrors the system categories seeded by migration 0004."""

LABELS: tuple[str, ...] = (
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
)

# A debit can never be Salary. Enforced as a hard mask in the classifier
# (not learned), because a prediction that violates it is simply wrong.
CREDIT_ONLY: frozenset[str] = frozenset({"Salary"})
