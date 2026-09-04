# API reference

Base URL: `http://localhost:5000/api/v1`

All requests and responses are JSON. All timestamps are UTC, ISO-8601, second
precision.

---

## Conventions

### Status codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 201 | Created (a prediction or a case) |
| 400 | `VALIDATION_ERROR` — the request was malformed |
| 404 | `NOT_FOUND` — the resource does not exist |
| 409 | `CONFLICT` — e.g. a case already exists for that transaction |
| 500 | `INTERNAL_ERROR` — logged server-side with an incident ID |
| 503 | `MODEL_UNAVAILABLE` — artifacts are not loaded |

### Error shape

```json
{
  "error": "VALIDATION_ERROR",
  "message": "Amount must be a non-negative number."
}
```

Some errors carry a `details` object. `INTERNAL_ERROR` carries an `incident_id`
that matches a server log entry — quote it when reporting a problem. Stack
traces are never returned.

---

## GET /health

Component status. Returns 200 when healthy, 503 when degraded, so it works
directly as a container or load-balancer probe.

```json
{
  "status": "ok",
  "components": {
    "model": { "loaded": true, "version": "rf-v1", "error": null },
    "database": { "connected": true, "engine": "sqlite" }
  },
  "config": {
    "env": "development",
    "fraud_threshold": 0.5,
    "risk_high_threshold": 0.7,
    "risk_medium_threshold": 0.4,
    "auto_create_cases": true
  },
  "api_version": "v1"
}
```

---

## GET /model-info

The full model card: hyperparameters, dataset provenance, measured test-set
metrics, threshold analysis, feature importances and the live risk configuration.

Abbreviated:

```json
{
  "model_version": "rf-v1",
  "algorithm": "RandomForestClassifier",
  "loaded": true,
  "trained_at": "2026-09-01T18:07:11+00:00",
  "hyperparameters": { "n_estimators": 100, "class_weight": "balanced", "random_state": 42 },
  "feature_count": 30,
  "dataset": {
    "total_rows": 283726, "fraud_rows": 473, "fraud_percentage": 0.1667,
    "test_size": 0.2, "random_seed": 42
  },
  "resampling": {
    "method": "SMOTE",
    "applied_to": "training split only",
    "before": { "legit": 226602, "fraud": 378 },
    "after":  { "legit": 226602, "fraud": 226602 }
  },
  "test_set_metrics": {
    "threshold": 0.5,
    "precision": 0.9114, "recall": 0.7579, "f1_score": 0.8276,
    "roc_auc": 0.9662, "pr_auc": 0.8040,
    "confusion_matrix": [[56644, 7], [23, 72]],
    "true_negatives": 56644, "false_positives": 7,
    "false_negatives": 23, "true_positives": 72,
    "support": { "legitimate": 56651, "fraud": 95 }
  },
  "threshold_analysis": [
    { "threshold": 0.3, "precision": 0.77,   "recall": 0.8105, "f1_score": 0.7897, "false_positives": 23, "false_negatives": 18 },
    { "threshold": 0.4, "precision": 0.8736, "recall": 0.8,    "f1_score": 0.8352, "false_positives": 11, "false_negatives": 19 },
    { "threshold": 0.5, "precision": 0.9114, "recall": 0.7579, "f1_score": 0.8276, "false_positives": 7,  "false_negatives": 23 }
  ],
  "risk_engine": {
    "risk_high_threshold": 0.7,
    "risk_medium_threshold": 0.4,
    "amount_percentiles": { "p99": 1016.16, "p999": 3042.80 },
    "elevated_risk_hours": [2, 3, 4, 5, 7, 11],
    "pca_components_monitored": ["V10","V11","V12","V14","V17","V4"],
    "behavioural_signals": "not available in Milestone 1 (dataset is anonymised)"
  }
}
```

---

## POST /predict

Score a transaction. The result is persisted before the response returns.

**Body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `amount` | number | yes | ≥ 0, ≤ 1,000,000 |
| `hour` | integer | yes | 0–23 |
| `v1`…`v28` | number | no | PCA components; `V1` casing also accepted. Omitted values default to 0.0, the mean of a centred component. Each must be within ±200 |
| `transaction_id` | string | no | 1–64 chars; generated if absent |
| `behavioural_signals` | object | no | Milestone 3 seam; contributes nothing today |

**Request**

```bash
curl -X POST http://localhost:5000/api/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"amount": 529.00, "hour": 0, "v1": -3.043541, "v14": -1.692029}'
```

**Response — 201**

```json
{
  "transaction_id": "TXN-22AACCF1E1",
  "prediction": "fraud",
  "fraud_probability": 1.0,
  "fraud_probability_percent": 100.0,
  "threshold_used": 0.5,
  "risk_level": "HIGH",
  "risk_score": 1.0,
  "risk_signals": ["high_model_probability"],
  "triggered_rules": [
    {
      "rule": "high_model_probability",
      "description": "Model fraud probability at or above 0.70",
      "weight": 0.1,
      "detail": "probability=1.0000"
    }
  ],
  "explanation": "Model scored this transaction at 100.0% fraud probability. Rules fired: high_model_probability. Risk classified HIGH.",
  "model_version": "rf-v1",
  "timestamp": "2026-09-01T18:12:14+00:00",
  "case_id": "CASE-B6EA8336"
}
```

`case_id` is `null` unless the transaction was HIGH risk and `AUTO_CREATE_CASES`
is enabled.

`prediction` is decided by `fraud_probability >= FRAUD_THRESHOLD`.
`risk_level` is decided by the risk engine, which adds rule weight on top of the
probability — so a transaction can be `legitimate` and `MEDIUM` at the same time.
That is intended: the prediction is the model's call, the risk level is the
policy's.

**Errors**

```json
{ "error": "VALIDATION_ERROR", "message": "Missing required field(s): amount.",
  "details": { "required": ["amount", "hour"] } }
```

---

## GET /transactions

**Query parameters**

| Name | Default | Notes |
|---|---|---|
| `limit` | 50 | 1 to `MAX_PAGE_SIZE` (200) |
| `offset` | 0 | ≥ 0 |
| `risk_level` | — | `LOW` / `MEDIUM` / `HIGH`, case-insensitive |
| `prediction` | — | `fraud` / `legitimate`, case-insensitive |
| `start_date` | — | ISO date or datetime, inclusive |
| `end_date` | — | ISO date or datetime, inclusive |

```bash
curl "http://localhost:5000/api/v1/transactions?risk_level=HIGH&limit=10"
```

```json
{
  "items": [
    {
      "transaction_id": "TXN-22AACCF1E1",
      "timestamp": "2026-09-01T18:12:14+00:00",
      "amount": 529.0,
      "hour": 0,
      "prediction": "fraud",
      "is_fraud": true,
      "fraud_probability": 1.0,
      "risk_level": "HIGH",
      "risk_score": 1.0,
      "risk_signals": ["high_model_probability"],
      "triggered_rules": [ "..." ],
      "model_version": "rf-v1",
      "threshold_used": 0.5,
      "features": { "Time": -1.9, "V1": -3.043541, "...": 0.0, "Amount": 1.75 },
      "source": "api"
    }
  ],
  "pagination": { "total": 1, "limit": 10, "offset": 0, "returned": 1, "has_more": false },
  "filters": { "risk_level": "HIGH", "prediction": null, "start_date": null, "end_date": null }
}
```

Ordered newest first. `features` holds the scaled model input — the exact
30-value vector the forest saw.

---

## GET /transactions/{id}

```json
{
  "transaction": { "...": "as above" },
  "case": { "case_id": "CASE-B6EA8336", "status": "OPEN", "...": "..." }
}
```

`case` is `null` when no case is attached. 404 if the transaction is unknown.

---

## GET /analytics

Aggregates computed from persisted predictions. **Never precomputed or
hardcoded** — an empty database returns zeros.

```json
{
  "totals": {
    "total_transactions": 3, "fraud_detected": 1,
    "legitimate": 2, "fraud_rate_percent": 33.3333
  },
  "amounts": { "average_amount": 1358.07, "total_amount": 4074.2, "max_amount": 3500.0 },
  "risk_distribution": { "LOW": 2, "MEDIUM": 0, "HIGH": 1 },
  "average_fraud_probability": 0.353333,
  "by_hour": [ { "hour": 0, "count": 1, "fraud": 1 } ],
  "by_day": [ { "day": "2026-09-01", "count": 3, "fraud": 1 } ],
  "by_amount_band": [ { "band": "100-500", "count": 1, "fraud": 0 } ],
  "recent_transactions": [ "... 10 most recent ..." ],
  "cases": {
    "OPEN": 1, "UNDER_REVIEW": 0, "CONFIRMED_FRAUD": 0,
    "MARKED_LEGITIMATE": 0, "CLOSED": 0, "total": 1, "open_or_review": 1
  },
  "model": { "model_version": "rf-v1", "loaded": true, "fraud_threshold": 0.5 },
  "data_source": "persisted predictions from this deployment only"
}
```

`fraud_rate_percent` reflects this deployment's scored traffic, not the dataset's
0.167% base rate. Scoring three transactions of which one is fraud gives 33%.

---

## Cases

A case always references a transaction this system actually scored.

Statuses: `OPEN`, `UNDER_REVIEW`, `CONFIRMED_FRAUD`, `MARKED_LEGITIMATE`,
`CLOSED`.

### GET /cases

Parameters: `limit`, `offset`, `status`.

```json
{
  "items": [ { "case_id": "CASE-B6EA8336", "transaction_id": "TXN-22AACCF1E1",
               "created_at": "...", "updated_at": "...", "status": "OPEN",
               "risk_level": "HIGH", "risk_score": 1.0,
               "signals": ["high_model_probability"],
               "reviewer": null, "resolution": null, "notes": null } ],
  "status_counts": { "OPEN": 1, "UNDER_REVIEW": 0, "CONFIRMED_FRAUD": 0,
                     "MARKED_LEGITIMATE": 0, "CLOSED": 0 },
  "pagination": { "limit": 50, "offset": 0, "returned": 1, "total": 1 }
}
```

### GET /cases/{id}

Returns the case with a nested `transaction` object.

### POST /cases

```bash
curl -X POST http://localhost:5000/api/v1/cases \
  -H 'Content-Type: application/json' \
  -d '{"transaction_id": "TXN-22AACCF1E1", "notes": "flagged by analyst"}'
```

- 404 if the transaction does not exist — a case cannot reference a transaction
  that was never scored.
- 409 if a case already exists for it; the existing `case_id` is in `details`.

### PATCH /cases/{id}

At least one of `status`, `reviewer`, `resolution`, `notes`.

```bash
curl -X PATCH http://localhost:5000/api/v1/cases/CASE-B6EA8336 \
  -H 'Content-Type: application/json' \
  -d '{"status": "CONFIRMED_FRAUD", "reviewer": "analyst-1", "resolution": "chargeback raised"}'
```

`updated_at` is set server-side. An empty body is a 400; an unknown status is a
400; an unknown case is a 404.

---

## GET /sample-transactions

Four confirmed-fraud and four confirmed-legitimate rows read from
`creditcard.csv`, each labelled with its ground truth. These are genuine dataset
records used to populate the prediction form, not synthetic data, and they are
never persisted unless submitted for scoring.

Returns 404 when the dataset is not present — the rest of the system is
unaffected.
