"""
Head-to-head on UNSEEN merchants: rules vs ML vs hybrid vs the LLM classifier.

    LLM_PROVIDER=gemini GEMINI_API_KEY=... python -m app.ml.eval_llm [--n 300]
    ANTHROPIC_API_KEY=... LLM_PROVIDER=anthropic python -m app.ml.eval_llm [--n 300]

Needs a real key and spends real money (n/25 requests). Uses the held-out
'test' merchants only, and trains the ML model on the 'train' merchants only,
so no method has seen a test merchant.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from app.core.config import settings
from app.ml.classifier import HybridClassifier, MLClassifier, make_text
from app.ml.llm_classifier import get_llm_classifier
from app.ml.synthetic import generate_labeled


def main(n: int, provider: str | None = None, model: str | None = None) -> dict:
    train = generate_labeled(8000, seed=11, split="train", label_noise=0.02)
    test = generate_labeled(n, seed=12, split="test")
    ml = MLClassifier.fit([make_text(d.description_raw, d.merchant_normalized, d.transaction_type, d.amount) for d in train],
                          [d.label for d in train])
    items = [(d.description_raw, d.merchant_normalized, d.transaction_type, d.amount) for d in test]
    y = [d.label for d in test]
    hyb = HybridClassifier(ml, min_confidence=0.0).predict(items)
    chosen = (provider or settings.llm_provider or "anthropic").lower()
    chosen_model = model or (settings.llm_gemini_model if chosen == "gemini" else settings.llm_classifier_model)
    llm = get_llm_classifier(provider=chosen, model=chosen_model).classify(items)
    acc = lambda preds: round(float(np.mean([(p.label if p else None) == t for p, t in zip(preds, y)])), 4)
    return {"n": n, "provider": chosen, "model": chosen_model, "hybrid_accuracy": acc(hyb),
            "llm_accuracy": acc(llm), "llm_abstained": sum(p is None for p in llm)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--provider", choices=["anthropic", "gemini"], default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    print(json.dumps(main(args.n, args.provider, args.model), indent=1))
