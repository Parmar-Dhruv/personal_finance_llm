# Phase 5 evaluation (synthetic data)

> All numbers are from synthetic data authored alongside the models -- optimistic by construction. Use them to compare methods, not as an accuracy promise.

## Classification -- 9000 txns, 237 merchants, 5-fold CV grouped by merchant

| Method | Accuracy (abstain=wrong) | Macro-F1 | Notes |
|---|---|---|---|
| Rules | 0.8196 | 0.9121 | coverage 0.8283, precision-on-answered 0.9894 |
| ML (TF-IDF + LogReg) | 0.4199 | 0.5097 | always answers |
| Hybrid | 0.8643 | 0.8908 | rules + ML |
| LLM | not run | not run | no API key in the build sandbox -- see README Known Gaps |

### Hybrid confidence sweep

| floor | coverage | precision |
|---|---|---|
| 0.5 | 0.8804 | 0.9514 |
| 0.6 | 0.8633 | 0.9618 |
| 0.7 | 0.8513 | 0.9679 |
| 0.8 | 0.8362 | 0.9746 |
| 0.9 | 0.8311 | 0.9779 |
| 0.95 | 0.0829 | 0.8861 |
| 0.99 | 0.0349 | 0.9936 |

### Seen vs unseen merchants

| Regime | ML accuracy | ML macro-F1 | Hybrid accuracy | Hybrid macro-F1 |
|---|---|---|---|---|
| Unseen merchants (grouped CV, above) | 0.4199 | 0.5097 | 0.8643 | 0.8908 |
| Seen merchants (shuffled CV) | 0.997 | 0.9976 | 0.9944 | 0.9952 |

### Precision by prediction source (unseen merchants)

```
{
 "rule": {
  "share_of_rows": 0.4538,
  "precision": 0.9865
 },
 "hybrid": {
  "share_of_rows": 0.3659,
  "precision": 0.9927
 },
 "ml": {
  "share_of_rows": 0.1803,
  "precision": 0.2964
 }
}
```

ML-only predictions by confidence floor (unseen merchants):

```
[{"threshold": 0.5, "rows": 547, "precision": 0.4406}, {"threshold": 0.7, "rows": 285, "precision": 0.414}, {"threshold": 0.8, "rows": 149, "precision": 0.2483}, {"threshold": 0.9, "rows": 103, "precision": 0.165}, {"threshold": 0.95, "rows": 92, "precision": 0.1087}, {"threshold": 0.99, "rows": 2, "precision": 0.0}]
```

ML-only auto-apply threshold (smallest floor reaching 0.95 precision with >=100 rows): **None** (None = ML-only is never auto-applied)

### Hybrid per-class F1

```
{
 "Food": 0.842,
 "Transportation": 0.772,
 "Shopping": 0.815,
 "Utilities": 0.881,
 "Entertainment": 0.904,
 "Healthcare": 0.948,
 "Travel": 0.828,
 "Rent": 0.985,
 "Salary": 0.998,
 "Business expenses": 0.936
}
```

### ML calibration (confidence vs accuracy)

| bin | n | mean conf | accuracy |
|---|---|---|---|
| 0.0-0.5 | 4935 | 0.341 | 0.271 |
| 0.5-0.7 | 1651 | 0.592 | 0.423 |
| 0.7-0.9 | 1275 | 0.804 | 0.623 |
| 0.9-1.0 | 1139 | 0.963 | 0.832 |

## Recurring

```
{
 "users": 20,
 "series_precision": 1.0,
 "series_recall": 0.9714,
 "series_f1": 0.9855,
 "cadence_correct_given_found": 1.0,
 "member_precision": 1.0,
 "false_positive_merchants": {}
}
```

## Duplicates

```
{
 "pending_or_auto": {
  "threshold": 0.7,
  "precision": 1.0,
  "recall": 1.0,
  "f1": 1.0,
  "points_at_wrong_original": 0,
  "hard_negative_flags_at_threshold": 0
 },
 "auto_only": {
  "threshold": 0.95,
  "precision": 1.0,
  "recall": 0.587,
  "f1": 0.7397,
  "points_at_wrong_original": 0,
  "hard_negative_flags_at_threshold": 0
 }
}
```

## Anomalies

```
{
 "users": 20,
 "positives": 180,
 "rows": 11592,
 "robust_z_at_3.5": {
  "precision": 0.8904,
  "recall": 0.3611,
  "f1": 0.5138
 },
 "recall_by_severity": {
  "moderate": 0.125,
  "severe": 0.55
 },
 "pr_auc": {
  "robust_z_hierarchical": 0.6318,
  "iqr_merchant": 0.6363,
  "isolation_forest": 0.3554
 },
 "base_rate": 0.0155
}
```
