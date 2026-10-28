"""
Evaluation harness for the Phase 5 ML layer. Run:

    python -m app.ml.eval            # prints a markdown report, writes docs/ml_eval/

Everything is measured on SYNTHETIC data (see synthetic.py for why and what
that means for how far to trust the numbers). Classification is scored with
5-fold cross-validation GROUPED BY MERCHANT: every test row's merchant was
absent from that fold's training set, so this measures generalization, not
memorization. Abstentions count as errors in "accuracy" and are shown
separately as coverage / precision-on-answered.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold, KFold

from app.ml.anomalies import ATxn, score_anomalies
from app.ml.classifier import HybridClassifier, MLClassifier, make_text
from app.ml.duplicates import AUTO_THRESHOLD, PENDING_THRESHOLD, DTxn, detect_duplicates
from app.ml.recurring import RTxn, detect_recurring
from app.ml.rules import classify_rules
from app.ml.synthetic import History, HistTxn, generate_history, generate_labeled
from app.ml.taxonomy import LABELS
from app.pipeline.normalize.merchants import clean_merchant_text

# ----------------------------------------------------------------------------
# Classification
# ----------------------------------------------------------------------------


def _prf(y_true: list[str], y_pred: list[str]) -> dict:
    return {
        "accuracy": round(float(np.mean([a == b for a, b in zip(y_true, y_pred)])), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=list(LABELS), average="macro", zero_division=0)), 4),
    }


def eval_classification(n: int = 9000, seed: int = 7, folds: int = 5, label_noise: float = 0.02) -> dict:
    data = generate_labeled(n, seed=seed)  # all merchants; labels clean
    groups = [d.merchant_key for d in data]
    y = [d.label for d in data]
    items = [(d.description_raw, d.merchant_normalized, d.transaction_type, d.amount) for d in data]
    texts = [make_text(*it) for it in items]
    types = [d.transaction_type for d in data]

    rules_pred: list[str | None] = [
        (r[0] if (r := classify_rules(f"{clean_merchant_text(d)} {m or ''}", t)) else None)
        for d, m, t, _ in items
    ]
    ml_pred: list[str] = [""] * n
    ml_conf = np.zeros(n)
    hyb_pred: list[str | None] = [None] * n
    hyb_conf = np.zeros(n)
    hyb_src: list[str | None] = [None] * n
    rng = np.random.default_rng(seed)

    for tr, te in GroupKFold(n_splits=folds).split(texts, y, groups):
        # Label noise only on the training side, as it would be in practice.
        y_tr = [y[i] if rng.random() > label_noise else str(rng.choice([x for x in LABELS if x != y[i]])) for i in tr]
        model = MLClassifier.fit([texts[i] for i in tr], y_tr)
        probs, classes = model.predict_proba([texts[i] for i in te], [types[i] for i in te])
        for k, i in enumerate(te):
            j = int(np.argmax(probs[k]))
            ml_pred[i], ml_conf[i] = classes[j], float(probs[k][j])
        hyb = HybridClassifier(model, min_confidence=0.0).predict([items[i] for i in te])
        for k, i in enumerate(te):
            if hyb[k] is not None:
                hyb_pred[i], hyb_conf[i], hyb_src[i] = hyb[k].label, hyb[k].confidence, hyb[k].source

    out: dict = {"n": n, "merchants": len(set(groups)), "folds": folds, "train_label_noise": label_noise}
    covered = [i for i in range(n) if rules_pred[i] is not None]
    out["rules"] = {
        **_prf(y, [p or "__none__" for p in rules_pred]),
        "coverage": round(len(covered) / n, 4),
        "precision_on_answered": round(float(np.mean([rules_pred[i] == y[i] for i in covered])), 4) if covered else None,
    }
    out["ml"] = _prf(y, ml_pred)
    out["hybrid"] = _prf(y, [p or "__none__" for p in hyb_pred])

    # Seen-merchant regime: plain shuffled K-fold, so the same merchants appear in
    # train and test. This is what a user's *own recurring merchants* look like
    # once the model has seen them -- and what in-distribution synthetic data
    # flatters most. Shown next to the grouped number on purpose.
    seen_ml: list[str] = [""] * n
    seen_hyb: list[str | None] = [None] * n
    for tr, te in KFold(n_splits=folds, shuffle=True, random_state=seed).split(texts):
        model = MLClassifier.fit([texts[i] for i in tr], [y[i] for i in tr])
        probs, classes = model.predict_proba([texts[i] for i in te], [types[i] for i in te])
        hyb = HybridClassifier(model, min_confidence=0.0).predict([items[i] for i in te])
        for k, i in enumerate(te):
            seen_ml[i] = classes[int(np.argmax(probs[k]))]
            seen_hyb[i] = hyb[k].label if hyb[k] else None
    out["seen_merchants"] = {"ml": _prf(y, seen_ml), "hybrid": _prf(y, [p or "__none__" for p in seen_hyb])}

    # Precision by prediction source (unseen merchants): drives the auto-apply policy.
    out["by_source_unseen"] = {}
    for src in ("rule", "hybrid", "ml"):
        sel = [i for i in range(n) if hyb_src[i] == src]
        out["by_source_unseen"][src] = {
            "share_of_rows": round(len(sel) / n, 4),
            "precision": round(float(np.mean([hyb_pred[i] == y[i] for i in sel])), 4) if sel else None,
        }
    ml_sweep = []
    for t in (0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
        sel = [i for i in range(n) if hyb_src[i] == "ml" and hyb_conf[i] >= t]
        ml_sweep.append({"threshold": t, "rows": len(sel),
                         "precision": round(float(np.mean([hyb_pred[i] == y[i] for i in sel])), 4) if sel else None})
    out["ml_only_sweep_unseen"] = ml_sweep

    # Threshold sweep for the hybrid: what do we get at each confidence floor?
    sweep = []
    for t in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99):
        sel = [i for i in range(n) if hyb_pred[i] is not None and hyb_conf[i] >= t]
        sweep.append({
            "threshold": t,
            "coverage": round(len(sel) / n, 4),
            "precision": round(float(np.mean([hyb_pred[i] == y[i] for i in sel])), 4) if sel else None,
        })
    out["hybrid_threshold_sweep"] = sweep

    # Per-class F1 and confusion matrix for the hybrid (abstentions as their own column).
    cols = list(LABELS) + ["__none__"]
    yp = [p or "__none__" for p in hyb_pred]
    out["hybrid_per_class_f1"] = {
        lab: round(float(f1_score([a == lab for a in y], [b == lab for b in yp], zero_division=0)), 3) for lab in LABELS
    }
    out["hybrid_confusion"] = {"labels": cols, "matrix": confusion_matrix(y, yp, labels=cols).tolist()}
    # Calibration check: mean confidence vs actual accuracy for ML in bins.
    bins = []
    for lo, hi in ((0, .5), (.5, .7), (.7, .9), (.9, 1.01)):
        sel = [i for i in range(n) if lo <= ml_conf[i] < hi]
        if sel:
            bins.append({"bin": f"{lo:.1f}-{min(hi, 1):.1f}", "n": len(sel),
                         "mean_confidence": round(float(np.mean(ml_conf[sel])), 3),
                         "accuracy": round(float(np.mean([ml_pred[i] == y[i] for i in sel])), 3)})
    out["ml_calibration"] = bins
    out["_oof"] = {"hyb_pred": hyb_pred, "hyb_conf": hyb_conf.tolist(), "hyb_src": hyb_src, "y": y}
    return out


def choose_ml_auto_threshold(sweep_source: dict, target_precision: float = 0.95, min_rows: int = 100) -> float | None:
    """
    Smallest confidence at which ML-ONLY predictions (no rule backing) reach
    `target_precision` on UNSEEN merchants (the conservative regime), with at
    least `min_rows` supporting rows. None = no such threshold exists, so
    ML-only predictions are never auto-applied -- only suggested.
    (Rule/hybrid-agreement predictions are auto-applied separately; see service.py.)
    """
    oof = sweep_source["_oof"]
    y, p, c, src = oof["y"], oof["hyb_pred"], oof["hyb_conf"], oof["hyb_src"]
    for t in [x / 100 for x in range(50, 100)]:
        sel = [i for i in range(len(y)) if src[i] == "ml" and c[i] >= t]
        if len(sel) >= min_rows and np.mean([p[i] == y[i] for i in sel]) >= target_precision:
            return round(t, 2)
    return None


# ----------------------------------------------------------------------------
# History-based evals
# ----------------------------------------------------------------------------


def _non_dups(h: History) -> list[HistTxn]:
    return [t for t in h.txns if t.dup_of is None]


def eval_recurring(seeds=range(100, 120)) -> dict:
    tp = fp = fn = 0
    cadence_ok = 0
    member_prec: list[float] = []
    fp_merchants: Counter = Counter()
    for s in seeds:
        h = generate_history(s)
        txns = _non_dups(h)
        r = [RTxn(t.key, t.date, t.merchant, Decimal(str(t.amount)), t.type, t.account, t.currency) for t in txns]
        found = detect_recurring(r)
        truth = {v["merchant"]: v["cadence"] for v in h.streams.values()}
        by_key = {t.key: t for t in txns}
        hit = set()
        for sr in found:
            if sr.merchant in truth:
                tp += 1
                hit.add(sr.merchant)
                cadence_ok += sr.cadence == truth[sr.merchant]
                member_prec.append(sum(by_key[k].recurring_stream is not None for k in sr.member_ids) / len(sr.member_ids))
            else:
                fp += 1
                fp_merchants[sr.merchant] += 1
        fn += len(set(truth) - hit)
    p = tp / (tp + fp) if tp + fp else 0.0
    r_ = tp / (tp + fn) if tp + fn else 0.0
    return {
        "users": len(list(seeds)), "series_precision": round(p, 4), "series_recall": round(r_, 4),
        "series_f1": round(2 * p * r_ / (p + r_), 4) if p + r_ else 0.0,
        "cadence_correct_given_found": round(cadence_ok / tp, 4) if tp else None,
        "member_precision": round(statistics.mean(member_prec), 4) if member_prec else None,
        "false_positive_merchants": dict(fp_merchants),
    }


def _hard_negative_history() -> list[HistTxn]:
    """Legit identical-looking payments that must NOT be auto-flagged."""
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    out = []
    for d in range(10):  # daily metro fare, same doc, no reference numbers
        out.append(HistTxn(len(out), base + timedelta(days=d), "Metro", "DELHI METRO DMRC", 30.0, "debit", "doc-a"))
    for r in ("111111111111", "222222222222"):  # two chais, same morning, distinct UPI refs
        out.append(HistTxn(len(out), base, "Chai", f"UPI/{r}/CHAI POINT", 20.0, "debit", "doc-a"))
    return out


def _as_dtxn(t: HistTxn) -> DTxn:
    upload_rank = 1 if t.doc.startswith("reupload") else 0
    return DTxn(t.key, t.account, t.currency, t.type, Decimal(str(t.amount)), t.date, t.description, t.doc,
                (upload_rank, t.date, t.key))


def eval_duplicates(seeds=range(200, 220)) -> dict:
    out = {}
    for name, thr in (("pending_or_auto", PENDING_THRESHOLD), ("auto_only", AUTO_THRESHOLD)):
        tp = fp = fn = wrong_target = 0
        for s in seeds:
            h = generate_history(s)
            truth = {t.key: t.dup_of for t in h.txns if t.dup_of is not None}
            res = {r.txn_id: r for r in detect_duplicates([_as_dtxn(t) for t in h.txns]) if r.score >= thr}
            for k, orig in truth.items():
                if k in res:
                    tp += 1
                    wrong_target += res[k].candidate_id != orig
                else:
                    fn += 1
            fp += sum(1 for k in res if k not in truth)
        # Hard negatives (should produce zero AUTO flags; pending is tolerable and counted separately).
        hn = detect_duplicates([_as_dtxn(t) for t in _hard_negative_history()])
        p = tp / (tp + fp) if tp + fp else 0.0
        r_ = tp / (tp + fn) if tp + fn else 0.0
        out[name] = {
            "threshold": thr, "precision": round(p, 4), "recall": round(r_, 4),
            "f1": round(2 * p * r_ / (p + r_), 4) if p + r_ else 0.0,
            "points_at_wrong_original": wrong_target,
            "hard_negative_flags_at_threshold": sum(1 for r in hn if r.score >= thr),
        }
    return out


def _iqr_flags(txns: list[HistTxn]) -> dict[int, float]:
    """IQR benchmark (merchant-level on log amount); score = distance above Q3 in IQR units."""
    import math
    out: dict[int, float] = {}
    groups: dict[tuple, list[HistTxn]] = {}
    for t in txns:
        groups.setdefault((t.merchant, t.type), []).append(t)
    for g in groups.values():
        logs = [math.log(x.amount) for x in g]
        if len(g) < 8:
            for x in g:
                out[x.key] = float("-inf")
            continue
        q1, q3 = np.percentile(logs, [25, 75])
        iqr = max(q3 - q1, 0.15)
        for x in g:
            out[x.key] = (math.log(x.amount) - q3) / iqr
    return out


def _iforest_scores(txns: list[HistTxn], seed: int) -> dict[int, float]:
    import math
    med: dict[tuple, float] = {}
    cnt: Counter = Counter()
    groups: dict[tuple, list[float]] = {}
    for t in txns:
        groups.setdefault((t.merchant, t.type), []).append(math.log(t.amount))
    for k, v in groups.items():
        med[k], cnt[k] = float(np.median(v)), len(v)
    X = np.array([[math.log(t.amount), math.log(t.amount) - med[(t.merchant, t.type)], math.log(cnt[(t.merchant, t.type)])]
                  for t in txns])
    iso = IsolationForest(n_estimators=200, contamination="auto", random_state=seed).fit(X)
    s = -iso.score_samples(X)  # higher = more anomalous
    return {t.key: float(v) for t, v in zip(txns, s)}


def eval_anomalies(seeds=range(300, 320)) -> dict:
    y_all, rz_all, iqr_all, if_all = [], [], [], []
    tp = fp = fn = 0
    sev = {"moderate": [0, 0], "severe": [0, 0]}  # [caught, total]
    for s in seeds:
        h = generate_history(s)
        txns = _non_dups(h)
        res = {r.txn_id: r for r in score_anomalies(
            [ATxn(t.key, t.currency, t.type, Decimal(str(t.amount)), t.merchant, None) for t in txns]
        )}
        iqr = _iqr_flags(txns)
        ifs = _iforest_scores(txns, s)
        for t in txns:
            y_all.append(int(t.is_anomaly))
            sc = res[t.key].score
            rz_all.append(sc if sc is not None else -1e9)
            iqr_all.append(iqr[t.key])
            if_all.append(ifs[t.key])
            flagged = res[t.key].flagged
            tp += flagged and t.is_anomaly
            fp += flagged and not t.is_anomaly
            fn += (not flagged) and t.is_anomaly
            if t.is_anomaly:
                sev[t.anomaly_severity][1] += 1
                sev[t.anomaly_severity][0] += flagged
    p = tp / (tp + fp) if tp + fp else 0.0
    r_ = tp / (tp + fn) if tp + fn else 0.0
    return {
        "users": len(list(seeds)), "positives": int(sum(y_all)), "rows": len(y_all),
        "robust_z_at_3.5": {"precision": round(p, 4), "recall": round(r_, 4),
                             "f1": round(2 * p * r_ / (p + r_), 4) if p + r_ else 0.0},
        "recall_by_severity": {k: round(v[0] / v[1], 4) if v[1] else None for k, v in sev.items()},
        "pr_auc": {
            "robust_z_hierarchical": round(float(average_precision_score(y_all, rz_all)), 4),
            "iqr_merchant": round(float(average_precision_score(y_all, iqr_all)), 4),
            "isolation_forest": round(float(average_precision_score(y_all, if_all)), 4),
        },
        "base_rate": round(float(np.mean(y_all)), 4),
    }


def run_all() -> dict:
    cls = eval_classification()
    thr = choose_ml_auto_threshold(cls)
    cls.pop("_oof")
    return {
        "classification": cls, "ml_only_auto_apply_threshold": thr,
        "recurring": eval_recurring(), "duplicates": eval_duplicates(), "anomalies": eval_anomalies(),
    }


def _md(r: dict) -> str:
    c = r["classification"]
    L = ["# Phase 5 evaluation (synthetic data)\n",
         "> All numbers are from synthetic data authored alongside the models -- optimistic by construction. "
         "Use them to compare methods, not as an accuracy promise.\n",
         f"## Classification -- {c['n']} txns, {c['merchants']} merchants, {c['folds']}-fold CV grouped by merchant\n",
         "| Method | Accuracy (abstain=wrong) | Macro-F1 | Notes |", "|---|---|---|---|",
         f"| Rules | {c['rules']['accuracy']} | {c['rules']['macro_f1']} | coverage {c['rules']['coverage']}, precision-on-answered {c['rules']['precision_on_answered']} |",
         f"| ML (TF-IDF + LogReg) | {c['ml']['accuracy']} | {c['ml']['macro_f1']} | always answers |",
         f"| Hybrid | {c['hybrid']['accuracy']} | {c['hybrid']['macro_f1']} | rules + ML |",
         "| LLM | not run | not run | no API key in the build sandbox -- see README Known Gaps |\n",
         "### Hybrid confidence sweep\n", "| floor | coverage | precision |", "|---|---|---|"]
    L += [f"| {s['threshold']} | {s['coverage']} | {s['precision']} |" for s in c["hybrid_threshold_sweep"]]
    sm = c["seen_merchants"]
    L += [f"\n### Seen vs unseen merchants\n",
          "| Regime | ML accuracy | ML macro-F1 | Hybrid accuracy | Hybrid macro-F1 |", "|---|---|---|---|---|",
          f"| Unseen merchants (grouped CV, above) | {c['ml']['accuracy']} | {c['ml']['macro_f1']} | {c['hybrid']['accuracy']} | {c['hybrid']['macro_f1']} |",
          f"| Seen merchants (shuffled CV) | {sm['ml']['accuracy']} | {sm['ml']['macro_f1']} | {sm['hybrid']['accuracy']} | {sm['hybrid']['macro_f1']} |",
          "\n### Precision by prediction source (unseen merchants)\n", "```", json.dumps(c["by_source_unseen"], indent=1), "```\n",
          "ML-only predictions by confidence floor (unseen merchants):\n", "```", json.dumps(c["ml_only_sweep_unseen"]), "```\n",
          f"ML-only auto-apply threshold (smallest floor reaching 0.95 precision with >=100 rows): **{r['ml_only_auto_apply_threshold']}** (None = ML-only is never auto-applied)\n",
          "### Hybrid per-class F1\n", "```", json.dumps(c["hybrid_per_class_f1"], indent=1), "```\n",
          "### ML calibration (confidence vs accuracy)\n", "| bin | n | mean conf | accuracy |", "|---|---|---|---|"]
    L += [f"| {b['bin']} | {b['n']} | {b['mean_confidence']} | {b['accuracy']} |" for b in c["ml_calibration"]]
    for k in ("recurring", "duplicates", "anomalies"):
        L += [f"\n## {k.capitalize()}\n", "```", json.dumps(r[k], indent=1), "```"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    rep = run_all()
    out_dir = Path(__file__).resolve().parents[2] / "docs" / "ml_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(rep, indent=1))
    (out_dir / "report.md").write_text(_md(rep))
    sys.stdout.write(_md(rep))
