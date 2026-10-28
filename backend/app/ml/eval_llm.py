"""
Head-to-head on UNSEEN merchants: rules vs ML vs hybrid vs the LLM classifier.

    ANTHROPIC_API_KEY=... python -m app.ml.eval_llm [--n 300]

Needs a real key and spends real money (n/25 requests). Not run in the build
sandbox -- see llm_classifier.py. Uses the held-out 'test' merchants only, and
trains the ML model on the 'train' merchants only, so no method has seen a
test merchant.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from app.ml.classifier import HybridClassifier, MLClassifier, make_text
from app.ml.llm_classifier import LLMClassifier
from app.ml.synthetic import generate_labeled


def main(n: int) -> dict:
    train = generate_labeled(8000, seed=11, split="train", label_noise=0.02)
    test = generate_labeled(n, seed=12, split="test")
    ml = MLClassifier.fit([make_text(d.description_raw, d.merchant_normalized, d.transaction_type, d.amount) for d in train],
                          [d.label for d in train])
    items = [(d.description_raw, d.merchant_normalized, d.transaction_type, d.amount) for d in test]
    y = [d.label for d in test]
    hyb = HybridClassifier(ml, min_confidence=0.0).predict(items)
    llm = LLMClassifier().classify(items)
    acc = lambda preds: round(float(np.mean([(p.label if p else None) == t for p, t in zip(preds, y)])), 4)
    return {"n": n, "hybrid_accuracy": acc(hyb), "llm_accuracy": acc(llm),
            "llm_abstained": sum(p is None for p in llm)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    print(json.dumps(main(ap.parse_args().n), indent=1))
