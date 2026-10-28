"""
Out-of-distribution check on a PUBLIC dataset. Requires an HF account that has
accepted the gated dataset terms and an `HF_TOKEN`:

    docker compose run --rm --no-deps -e HF_HOME=/tmp/hf backend sh -c \
      "pip install --no-cache-dir -q datasets && python -m app.ml.eval_public --limit 20000"

Dataset: huggingface.co/datasets/mitulshah/transaction-categorization
(labelled MIT; the card says it mixes synthetic records with data from
unnamed external sources, so the MIT label does not by itself settle
provenance -- review before redistributing anything derived from it).

Latest run (2026-10-28): 12,144 of the first 20,000 rows mapped (60.7%); among
mapped rows, 48.9% answered, 48.6% precision on answered, 23.8% accuracy with
abstentions counted wrong. See `docs/ml_eval/public_ood.json`.

Caveats that limit interpretation: the split is a first-N slice, not a random
sample; every row is forced to debit/amount 100.0/merchant None because the
public schema has no equivalent fields here; and four categories (Financial
Services, Income, Government & Legal, Charity & Donations) have no counterpart
and are dropped (see MAP). Treat the result as a rough signal on generic
US/UK/IN narrations, not a benchmark. The column names below are assumptions
from the dataset card; if the schema differs the script fails loudly rather than
guessing.
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
