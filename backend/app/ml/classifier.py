"""
Transaction classifier: TF-IDF (char n-grams + words) -> multinomial
logistic regression, plus the rule+ML hybrid and persistence.

Why this model and not something bigger: the input is a short noisy string
with ~10 labels; character n-grams handle truncation/typos/unseen-but-
similar merchants ("MEDPLUS" ~ "MEDLIFE"), logistic regression gives usable
probabilities for thresholding, and it trains in seconds and is explainable.
Gradient boosting / transformers were not tried -- that is a deliberate
scope call, not a finding.

Hybrid policy (see `HybridClassifier.predict`): rules fire first (high
precision, narrow recall); ML fills the gaps; a confident ML disagreement
overrides a rule; below `min_confidence` we return nothing rather than guess.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.ml.rules import RULE_CONFIDENCE, classify_rules
from app.ml.taxonomy import CREDIT_ONLY, LABELS
from app.pipeline.normalize.merchants import clean_merchant_text

_DIGITS_RE = re.compile(r"\d")


def make_text(description_raw: str, merchant_normalized: str | None, transaction_type: str, amount: float) -> str:
    """
    The single string the model sees. Digits are collapsed to '0' so
    reference numbers don't create unique-per-row tokens; direction and a
    coarse amount magnitude ride along as pseudo-words.
    """
    cleaned = clean_merchant_text(description_raw)
    parts = [cleaned]
    if merchant_normalized and merchant_normalized.lower() != cleaned.lower():
        parts.append(merchant_normalized)
    text = " | ".join(parts)
    text = _DIGITS_RE.sub("0", text)
    mag = int(math.log10(max(float(amount), 1.0)))  # 0..6: coarse on purpose
    return f"{text} | dir_{transaction_type} mag_{mag}"


def _frame(texts: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"text": texts})


def build_pipeline(C: float = 10.0) -> Pipeline:
    feats = ColumnTransformer(
        [
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True, lowercase=True), "text"),
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True, lowercase=True), "text"),
        ]
    )
    # class_weight=balanced: Rent/Salary are ~3% of rows each.
    clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced")
    return Pipeline([("feats", feats), ("clf", clf)])


def _mask_probs(probs: np.ndarray, classes: list[str], types: list[str]) -> np.ndarray:
    """Zero out impossible labels (debit Salary) and renormalize."""
    probs = probs.copy()
    for j, c in enumerate(classes):
        if c in CREDIT_ONLY:
            for i, t in enumerate(types):
                if t != "credit":
                    probs[i, j] = 0.0
    s = probs.sum(axis=1, keepdims=True)
    s[s == 0] = 1.0
    return probs / s


class MLClassifier:
    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline

    @property
    def classes(self) -> list[str]:
        return list(self.pipeline.named_steps["clf"].classes_)

    @classmethod
    def fit(cls, texts: list[str], labels: list[str], C: float = 10.0) -> "MLClassifier":
        pipe = build_pipeline(C)
        pipe.fit(_frame(texts), labels)
        return cls(pipe)

    def predict_proba(self, texts: list[str], types: list[str]) -> tuple[np.ndarray, list[str]]:
        probs = self.pipeline.predict_proba(_frame(texts))
        return _mask_probs(probs, self.classes, types), self.classes


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float
    source: str  # rule | ml | hybrid


class HybridClassifier:
    """Rules + ML combined. `source` records which one produced the label."""

    def __init__(self, ml: MLClassifier | None, rule_override_p: float = 0.95, min_confidence: float = 0.5):
        self.ml = ml
        self.rule_override_p = rule_override_p
        self.min_confidence = min_confidence

    def predict(self, items: list[tuple[str, str | None, str, float]]) -> list[Prediction | None]:
        """items: (description_raw, merchant_normalized, transaction_type, amount)."""
        if not items:
            return []
        texts = [make_text(d, m, t, a) for d, m, t, a in items]
        types = [t for _, _, t, _ in items]
        # Rules look at lower-cased, digit-preserving cleaned text + canonical merchant.
        rule_hits = [
            classify_rules(f"{clean_merchant_text(d)} {m or ''}", t) for d, m, t, _ in items
        ]
        if self.ml is not None:
            probs, classes = self.ml.predict_proba(texts, types)
        else:
            probs, classes = None, []

        out: list[Prediction | None] = []
        for i, rule in enumerate(rule_hits):
            ml_label = ml_p = None
            if probs is not None:
                j = int(np.argmax(probs[i]))
                ml_label, ml_p = classes[j], float(probs[i][j])
            pred: Prediction | None
            if rule and ml_label is None:
                pred = Prediction(rule[0], RULE_CONFIDENCE, "rule")
            elif rule and ml_label == rule[0]:
                pred = Prediction(rule[0], max(RULE_CONFIDENCE, ml_p), "hybrid")  # agreement
            elif rule and ml_p is not None and ml_p >= self.rule_override_p:
                pred = Prediction(ml_label, ml_p, "ml")  # confident ML disagreement wins
            elif rule:
                pred = Prediction(rule[0], RULE_CONFIDENCE, "rule")
            elif ml_label is not None:
                pred = Prediction(ml_label, ml_p, "ml")
            else:
                pred = None
            if pred is not None and pred.confidence < self.min_confidence:
                pred = None
            out.append(pred)
        return out


# --------------------------------------------------------------------------
# Persistence. joblib == pickle: loading executes code, so only ever load a
# file this application wrote itself. The sha256 in the sidecar catches
# accidental corruption/partial writes; it does NOT stop a hostile actor
# who can write both files (they could write the sidecar too). Treat the
# model directory as trusted-write-only. (Known Gap.)
# --------------------------------------------------------------------------
MODEL_FILE = "classifier.joblib"
META_FILE = "classifier.meta.json"


def save_model(ml: MLClassifier, directory: Path, meta: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / (MODEL_FILE + ".tmp")
    joblib.dump(ml.pipeline, tmp)
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    tmp.replace(directory / MODEL_FILE)
    meta = {
        **meta,
        "sha256": digest,
        "sklearn_version": sklearn.__version__,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "labels": ml.classes,
    }
    (directory / META_FILE).write_text(json.dumps(meta, indent=2, default=str))


class ModelUnavailable(Exception):
    pass


def load_model(directory: Path) -> tuple[MLClassifier, dict]:
    """Raises ModelUnavailable (with a reason) instead of crashing the caller."""
    model_path, meta_path = directory / MODEL_FILE, directory / META_FILE
    if not model_path.exists() or not meta_path.exists():
        raise ModelUnavailable(f"no trained model in {directory} (run `python -m app.ml.train`)")
    meta = json.loads(meta_path.read_text())
    if hashlib.sha256(model_path.read_bytes()).hexdigest() != meta.get("sha256"):
        raise ModelUnavailable("model file does not match its recorded sha256 (corrupt or partial write)")
    if meta.get("sklearn_version") != sklearn.__version__:
        # Pickles are not portable across sklearn versions; fail loudly.
        raise ModelUnavailable(
            f"model trained with scikit-learn {meta.get('sklearn_version')}, running {sklearn.__version__}; retrain"
        )
    return MLClassifier(joblib.load(model_path)), meta
