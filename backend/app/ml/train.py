"""
Train and persist the classifier:   python -m app.ml.train [--n 12000] [--seed 1]

Training data is the synthetic generator (no real labeled data exists). The
saved metadata records exactly that, plus the out-of-fold metrics measured on
UNSEEN merchants, so nobody mistakes the model for something it isn't.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ml.classifier import MLClassifier, make_text, save_model
from app.ml.eval import choose_ml_auto_threshold, eval_classification
from app.ml.synthetic import generate_labeled


def train(directory: Path, n: int = 12000, seed: int = 1, label_noise: float = 0.02, run_eval: bool = True) -> dict:
    data = generate_labeled(n, seed=seed, label_noise=label_noise)
    texts = [make_text(d.description_raw, d.merchant_normalized, d.transaction_type, d.amount) for d in data]
    model = MLClassifier.fit(texts, [d.label for d in data])
    meta: dict = {
        "training_data": "synthetic (app.ml.synthetic); NO real labeled data",
        "n_train": n, "seed": seed, "train_label_noise": label_noise,
    }
    if run_eval:
        ev = eval_classification(seed=seed + 1000)
        meta["ml_only_auto_apply_threshold"] = choose_ml_auto_threshold(ev)
        meta["eval_unseen_merchants"] = {k: ev[k] for k in ("rules", "ml", "hybrid", "by_source_unseen")}
        meta["eval_seen_merchants"] = ev["seen_merchants"]
    else:
        meta["ml_only_auto_apply_threshold"] = None  # unmeasured => never auto-apply ML-only
    save_model(model, directory, meta)
    return meta


if __name__ == "__main__":
    from app.ml.service import model_dir

    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    out = a.out or model_dir()
    print(json.dumps(train(out, a.n, a.seed), indent=1, default=str))
    print(f"saved to {out}")
