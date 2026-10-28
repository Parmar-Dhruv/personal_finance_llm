"""
Out-of-distribution check on a PUBLIC dataset -- NOT RUN in the build sandbox
(huggingface.co is not reachable from it). Run locally:

    pip install datasets
    python -m app.ml.eval_public --limit 20000

Dataset: huggingface.co/datasets/mitulshah/transaction-categorization
(labelled MIT; the card says it mixes synthetic records with data from
unnamed external sources, so the MIT label does not by itself settle
provenance -- review before redistributing anything derived from it).

Its 10 categories don't match ours, so labels are MAPPED, lossily, and rows
whose category has no counterpart are dropped (see MAP). Treat the result as a
rough out-of-distribution signal on generic US/UK/IN narrations, not a
benchmark. The column names below are assumptions from the dataset card; if the
schema differs the script fails loudly rather than guessing.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from app.ml.classifier import HybridClassifier
from app.ml.service import get_classifier

# public category -> our category (None = no counterpart, row dropped)
MAP: dict[str, str | None] = {
    "Food & Dining": "Food",
    "Transportation": "Transportation",
    "Shopping & Retail": "Shopping",
    "Entertainment & Recreation": "Entertainment",
    "Healthcare & Medical": "Healthcare",
    "Utilities & Services": "Utilities",
    "Financial Services": None,
    "Income": None,  # could be Salary, but also interest/refunds: too lossy to assume
    "Government & Legal": None,
    "Charity & Donations": None,
}
TEXT_COLS = ("transaction_description", "description", "text")
LABEL_COLS = ("category", "label")


def main(limit: int) -> dict:
    from datasets import load_dataset  # not a project dependency; installed ad hoc

    ds = load_dataset("mitulshah/transaction-categorization", split=f"train[:{limit}]")
    cols = ds.column_names
    tcol = next((c for c in TEXT_COLS if c in cols), None)
    lcol = next((c for c in LABEL_COLS if c in cols), None)
    if tcol is None or lcol is None:
        raise SystemExit(f"Unexpected schema {cols}; edit TEXT_COLS/LABEL_COLS after reading the dataset card")
    rows = [(r[tcol], MAP.get(r[lcol])) for r in ds if MAP.get(r[lcol])]
    bundle = get_classifier()
    preds = bundle.classifier.predict([(d, None, "debit", 100.0) for d, _ in rows])
    y = [lab for _, lab in rows]
    answered = [(p.label, t) for p, t in zip(preds, y) if p]
    return {
        "mode": "rules+ml" if bundle.ml_available else "rules-only", "rows_mapped": len(rows),
        "coverage": round(len(answered) / len(rows), 4),
        "accuracy_abstain_wrong": round(float(np.mean([(p.label if p else None) == t for p, t in zip(preds, y)])), 4),
        "precision_on_answered": round(float(np.mean([a == b for a, b in answered])), 4) if answered else None,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20000)
    print(json.dumps(main(ap.parse_args().limit), indent=1))
