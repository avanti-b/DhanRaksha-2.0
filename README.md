# DhanRaksha 2.0

**Real-time financial fraud detection and risk intelligence — Milestone 1 (local build)**

DhanRaksha scores card transactions for fraud risk, explains why it reached that
conclusion, persists the decision, and opens a reviewable case when the risk is
high. This repository is the Milestone 1 deliverable: a complete, locally
runnable system with no cloud dependency of any kind.

> **Scope.** This is a student research project, not a production banking fraud
> system. See [Limitations](#limitations) before drawing any conclusion from the
> numbers below.

---

## Table of contents

1. [Problem statement](#problem-statement)
2. [Architecture](#architecture)
3. [Quick start](#quick-start)
4. [Dataset](#dataset)
5. [ML pipeline](#ml-pipeline)
6. [Model evaluation](#model-evaluation)
7. [Risk engine](#risk-engine)
8. [Database](#database)
9. [API endpoints](#api-endpoints)
10. [Frontend](#frontend)
11. [Testing](#testing)
12. [Docker](#docker)
13. [Configuration](#configuration)
14. [Project structure](#project-structure)
15. [Limitations](#limitations)
16. [Roadmap: Milestone 2 and 3](#roadmap-milestone-2-and-3)

---

## Problem statement

Card fraud is a needle-in-a-haystack problem. In the reference dataset, 473 of
283,726 transactions are fraudulent — 0.167%. A model that predicts
"legitimate" for every transaction scores 99.83% accuracy and catches nothing,
which is why accuracy is never reported as a headline metric here.

The real trade-off is between two costs that pull in opposite directions:

- A **false negative** is fraud that goes through. The bank absorbs the loss.
- A **false positive** is a legitimate customer whose card is declined. That
  costs goodwill, support time, and sometimes the customer.

There is no threshold that eliminates both. Choosing where to sit on that curve
is a business decision, so the decision threshold in DhanRaksha is
configuration, never a constant buried in the code.

---

## Architecture

```
                        ┌──────────────────────────────┐
                        │  Frontend (static SPA)       │
                        │  dashboard · history · cases │
                        └───────────────┬──────────────┘
                                        │ fetch /api/v1/*
                        ┌───────────────▼──────────────┐
                        │  Flask application           │
                        │  routes/  (HTTP only)        │
                        └───────────────┬──────────────┘
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             │                          │                          │
     ┌───────▼────────┐        ┌────────▼────────┐        ┌────────▼────────┐
     │ FraudService   │        │ TransactionSvc  │        │ CaseService     │
     │ orchestration  │        │ history+analytics│       │ lifecycle       │
     └───────┬────────┘        └────────┬────────┘        └────────┬────────┘
             │                          │                          │
   ┌─────────┼─────────┐                └────────────┬─────────────┘
   │                   │                             │
┌──▼───────────┐ ┌─────▼────────┐          ┌─────────▼──────────┐
│ ModelService │ │ RiskEngine   │          │ Repository layer   │
│ RF + pipeline│ │ deterministic│          │ (abstract)         │
└──────┬───────┘ │ rules        │          └─────────┬──────────┘
       │         └──────────────┘                    │
┌──────▼────────────────┐                  ┌─────────▼──────────┐
│ ml/artifacts/         │                  │ SQLite             │
│ model · pipeline · md │                  │ ← swappable        │
└───────────────────────┘                  └────────────────────┘
```

**Request flow for a prediction:**

```
POST /api/v1/predict
   → validate (schemas/validators.py)        reject bad input before any work
   → FeaturePipeline.transform               same object fitted during training
   → RandomForest.predict_proba              the only source of probability
   → RiskEngine.assess                       deterministic rules → LOW/MED/HIGH
   → TransactionService.record               persisted
   → CaseService (if HIGH)                   case opened
   → 201 with the full decision
```

Three architectural decisions worth stating explicitly:

**Preprocessing lives in one module.** `ml/preprocessing.py` is imported by both
`ml/train.py` and the inference path. The scaler is fitted once during training
and saved as an artifact the backend loads. Training and serving cannot drift
apart because there is only one implementation.

**The risk engine is separate from the model.** The model answers "how likely is
this fraud?". The engine answers "what should be done about it?". Keeping them
apart means the scoring policy can change without retraining, and every decision
is explainable to a reviewer.

**Storage is behind an interface.** Services depend on `TransactionRepository`
and `CaseRepository` (abstract base classes), never on SQLite. Milestone 2 adds
Cosmos implementations of the same interfaces; no service or route changes.

---

## Quick start

Requires Python 3.11 or newer.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env

# 3. Run — trained artifacts are already in ml/artifacts/
python -m backend.app
```

Open <http://localhost:5000>. Flask serves both the API and the frontend, so
there is nothing else to start.

**To retrain from scratch** (optional — takes a few minutes):

```bash
# Download creditcard.csv from Kaggle, place it in data/
python -m ml.train --data data/creditcard.csv --version rf-v1
```

On a machine with little RAM, set `TRAIN_N_JOBS=1` to stop worker processes
duplicating the resampled matrix.

---

## Dataset

[Credit Card Fraud Detection](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud)
(MLG-ULB) — two days of European card transactions from September 2013.

| Property | Value |
|---|---|
| Raw rows | 284,807 |
| Exact duplicates removed | 1,081 |
| Rows after cleaning | 283,726 |
| Fraud | 473 (0.167%) |
| Legitimate | 283,253 |
| Features | `Time`, `V1`–`V28`, `Amount` |

`V1`–`V28` are PCA components. The original features were removed for
confidentiality, so no feature has a human-readable meaning. `Time` is seconds
elapsed since the first transaction in the dataset.

**The CSV is not included in this repository** — it is 144 MB and is not ours to
redistribute. Download it from Kaggle into `data/` if you want to retrain or use
the sample-loading button in the prediction UI. Everything else runs without it.

---

## ML pipeline

```
dataset → clean → stratified split → fit scaler (TRAIN ONLY)
        → SMOTE (TRAIN ONLY) → Random Forest → evaluate on untouched test set
        → save versioned artifacts
```

**Why scaling only `Time` and `Amount`.** `V1`–`V28` are already PCA outputs,
centred and scaled by the dataset authors. Re-scaling them would distort the
component geometry. `Time` and `Amount` are raw and on wildly different scales,
so they are standardised.

**Why the scaler is fitted after the split.** Fitting on the full frame lets the
test set's mean and standard deviation influence training — mild leakage, but
leakage. The original `train_model.py` did this; it is fixed here. `FeaturePipeline.fit`
is only ever called on `X_train`.

**Why SMOTE, and only on training data.** With 378 fraud rows in the training
split against 226,602 legitimate ones, a tree ensemble has almost no fraud
signal to split on. SMOTE synthesises minority examples by interpolating between
near neighbours, balancing training to 226,602 per class.

Applying SMOTE to the test set would be a serious methodological error: it would
mean evaluating on synthetic rows the model was effectively taught to recognise,
inflating every metric. **The test split is never resampled.** It keeps its real
95 fraud / 56,651 legitimate distribution, which is why precision looks modest
compared to the balanced training set.

**Why Random Forest.** It handles the non-linear interactions among PCA
components without feature engineering, gives feature importances that make the
risk engine explainable, and needs no GPU. Its probability output is the fraction
of trees voting fraud — a real quantity from a real model, never fabricated by
the application. The logistic regression baseline is retained for comparison and
shows exactly why a linear model is the wrong choice here (see below).

---

## Model evaluation

Measured on the held-out test split (56,746 transactions, 95 fraud), threshold
0.5, model version `rf-v1`.

| Metric | Random Forest | Logistic Regression (baseline) |
|---|---|---|
| Precision | **0.9114** | 0.0530 |
| Recall | **0.7579** | 0.8737 |
| F1 | **0.8276** | 0.1000 |
| ROC-AUC | **0.9662** | 0.9619 |
| PR-AUC | **0.8040** | — |

**Confusion matrix (Random Forest, threshold 0.5):**

|  | Predicted legitimate | Predicted fraud |
|---|---|---|
| **Actually legitimate** | 56,644 | 7 |
| **Actually fraud** | 23 | 72 |

The baseline is instructive. Logistic regression achieves a *higher* ROC-AUC
than the forest and catches more fraud (recall 0.87), but with 1,479 false
positives against 83 true positives, 95% of its alarms are wrong. This is
precisely why ROC-AUC alone is misleading on imbalanced data, and why PR-AUC and
raw FP/FN counts are reported alongside it.

### Threshold analysis

| Threshold | Precision | Recall | F1 | False positives | False negatives |
|---|---|---|---|---|---|
| 0.30 | 0.7700 | 0.8105 | 0.7897 | 23 | 18 |
| 0.40 | 0.8736 | 0.8000 | **0.8352** | 11 | 19 |
| 0.50 | 0.9114 | 0.7579 | 0.8276 | 7 | 23 |
| 0.60 | 0.9324 | 0.7263 | 0.8166 | 5 | 26 |
| 0.70 | 0.9714 | 0.7158 | 0.8242 | 2 | 27 |

Reading this: dropping from 0.50 to 0.40 catches four more frauds at the cost of
four more false alarms — probably worth it, since F1 peaks at 0.40. Pushing to
0.70 nearly eliminates false alarms (2) but misses 27 of 95 frauds.

The default ships at 0.50. Change it with `FRAUD_THRESHOLD` in `.env`; nothing
else in the codebase needs touching.

### Original vs reproduced metrics

The original project paper reported precision 0.934, recall 0.844, F1 0.887,
ROC-AUC 0.971. **These were not reproduced.** The `metrics.json` committed
alongside the original artifacts actually recorded precision 0.9114, recall
0.7579, F1 0.8276, ROC-AUC 0.9543 — matching this rebuild almost exactly, which
suggests the paper's figures came from a different run than the one that
produced the shipped model.

The leakage-free retrain here reproduces the committed precision, recall and F1
to four decimals, with ROC-AUC improving slightly (0.9543 → 0.9662). **Use the
numbers in this README, not the paper's**, and correct the paper before
submission.

Top features by importance: `V14`, `V10`, `V12`, `V4`, `V17`, `V11`.

---

## Risk engine

The model gives a probability. The risk engine turns it into a decision, and
explains itself. It is deterministic — same input, same output, no randomness
and **no LLM anywhere in the decision path**.

```
risk_score = model_probability + min(0.25, Σ triggered rule weights)

HIGH    ≥ 0.70      (RISK_HIGH_THRESHOLD)
MEDIUM  ≥ 0.40      (RISK_MEDIUM_THRESHOLD)
LOW     otherwise
```

Rules can only *add* risk, never subtract it, and their total contribution is
capped at 0.25 so the model stays the dominant term. A transaction the model
considers safe cannot be escalated to HIGH by rules alone.

| Rule | Weight | Fires when |
|---|---|---|
| `high_model_probability` | 0.10 | probability ≥ 0.70 |
| `elevated_model_probability` | 0.05 | 0.40 ≤ probability < 0.70 |
| `very_high_value_transaction` | 0.08 | amount ≥ p99.9 of training data (3,042.80) |
| `high_value_transaction` | 0.04 | p99 (1,016.16) ≤ amount < p99.9 |
| `zero_amount_probe` | 0.05 | amount = 0 (card-testing pattern) |
| `elevated_risk_hour` | 0.05 | hour in {2, 3, 4, 5, 7, 11} |
| `anomalous_pca_components` | 0.04 each, max 0.12 | `V14`/`V17`/`V12`/`V10`/`V4`/`V11` outside the 0.5–99.5 percentile range of legitimate training traffic |

**Every threshold above is measured, not invented.** They are computed from the
training split during `ml/train.py` and written to `risk_reference` in
`model_metadata.json`, which the engine loads at startup. The elevated hours are
those whose fraud rate exceeds twice the overall rate; the PCA bounds are
literally "outside where 99% of legitimate transactions sit".

**On behavioural signals.** A real fraud system would weigh device
fingerprints, geography, velocity and customer history. This dataset is
anonymised — no customer ID, no merchant, no device, no location. Rather than
invent plausible-looking behavioural data, the engine exposes a
`behavioural_signals` parameter that contributes nothing when empty. Two example
rules (`unrecognised_device`, `high_transaction_velocity`) are implemented and
tested, ready for Milestone 3 to supply real inputs.

Example output:

```json
{
  "risk_level": "HIGH",
  "risk_score": 1.0,
  "model_probability": 1.0,
  "signals": ["high_model_probability"],
  "triggered_rules": [{
    "rule": "high_model_probability",
    "description": "Model fraud probability at or above 0.70",
    "weight": 0.1,
    "detail": "probability=1.0000"
  }],
  "explanation": "Model scored this transaction at 100.0% fraud probability. Rules fired: high_model_probability. Risk classified HIGH."
}
```

---

## Database

SQLite, via a repository abstraction. Two tables.

**`transactions`** — one row per scored transaction: `transaction_id` (PK),
`created_at`, `amount`, `hour`, `prediction`, `is_fraud`, `fraud_probability`,
`risk_level`, `risk_score`, `risk_signals` (JSON), `triggered_rules` (JSON),
`model_version`, `threshold_used`, `features` (JSON), `source`. Indexed on
`created_at`, `risk_level`, `is_fraud`.

**`cases`** — `case_id` (PK), `transaction_id` (FK), `created_at`, `updated_at`,
`status`, `risk_level`, `risk_score`, `signals` (JSON), `reviewer`,
`resolution`, `notes`.

**On stored data.** The persisted `features` are the *scaled model inputs* —
PCA components and standardised Time/Amount. The source dataset contains no card
number, cardholder name, merchant or location, so nothing personally identifying
is stored. Signals and rules are kept as JSON so a reviewer can see exactly why
a decision was made months later, and so the document shape maps cleanly onto
Cosmos DB.

**Why SQLite rather than Postgres.** It is a file, needs no container, and the
whole point is that Milestone 1 runs anywhere with zero infrastructure. Because
access goes through the repository interface, the choice is reversible.

---

## API endpoints

All endpoints are under `/api/v1`.

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/health` | Model and database status | 200 / 503 |
| GET | `/model-info` | Model card, metrics, threshold analysis, risk config | 200 |
| POST | `/predict` | Score a transaction | 201 |
| GET | `/transactions` | History, filterable and paginated | 200 |
| GET | `/transactions/{id}` | One transaction plus its case | 200 |
| GET | `/analytics` | Aggregates over persisted predictions | 200 |
| GET | `/cases` | Case list with status counts | 200 |
| GET | `/cases/{id}` | One case plus its transaction | 200 |
| POST | `/cases` | Open a case for a scored transaction | 201 |
| PATCH | `/cases/{id}` | Update status, reviewer, resolution, notes | 200 |
| GET | `/sample-transactions` | Real labelled dataset rows for the UI | 200 |

`GET /transactions` accepts `limit`, `offset`, `risk_level`, `prediction`,
`start_date`, `end_date`.

**Errors** are always JSON, never HTML, and never a stack trace:

```json
{ "error": "VALIDATION_ERROR", "message": "Amount must be a non-negative number." }
```

Codes: `VALIDATION_ERROR` (400), `NOT_FOUND` (404), `CONFLICT` (409),
`MODEL_UNAVAILABLE` (503), `INTERNAL_ERROR` (500). Internal errors are logged
server-side with an incident ID that is returned to the caller, so a report can
be traced to a log line without exposing anything.

Full request and response examples: [`docs/api.md`](docs/api.md).

---

## Frontend

A single-page application served by Flask, in the original project's visual
language — cream and bark palette, Cormorant Garamond headings, DM Sans body.

The original `index.html` was 1,262 lines with CSS, markup and JavaScript in one
file, and its transaction table, alerts feed and charts were **hardcoded
JavaScript arrays**. The styling was worth keeping; the fake data was not.

The stylesheet is preserved and extracted to `css/dhanraksha.css`, with new
components appended. Logic is split into `js/api.js` (typed client),
`js/charts.js` (Chart.js rendering) and `js/app.js` (views). **Every number now
comes from the API.** With an empty database the dashboard shows "No transactions
yet" rather than an invented figure.

Six views: dashboard, transaction history with filters and pagination, fraud
cases with status management, prediction form, model card with threshold
analysis, and an about page. Clicking any row opens a detail drawer showing the
decision, each triggered rule with its explanation, the case, and the exact
30-feature model input.

Kept as a SPA rather than the separate `dashboard.html` / `transactions.html`
files sketched in the brief: the views share a shell, a client and a chart
layer, and splitting them would mean duplicating all three across five pages.

---

## Testing

```bash
pytest
```

**84 tests, all passing**, in about 4 seconds.

| File | Tests | Covers |
|---|---|---|
| `test_preprocessing.py` | 10 | Column order, that only Time/Amount are scaled, artifact round-trip, cleaning |
| `test_risk_engine.py` | 13 | Banding, additive-only scoring, the 0.25 cap, determinism, every rule |
| `test_validation.py` | 15 | Missing fields, negatives, out-of-range hours, NaN/inf, numeric strings |
| `test_model.py` | 7 | Real artifact loading, 30-feature contract, determinism, graceful degradation |
| `test_api.py` | 11 | Every endpoint, persistence round-trip, JSON errors, empty-store analytics |
| `test_transactions.py` | 7 | Ordering, pagination, filters, stored decision context |
| `test_cases.py` | 12 | Lifecycle, referential integrity, duplicate conflict, auto-creation |

Tests run against the **real trained artifacts**, so model loading and inference
are genuinely exercised — but against a temporary SQLite file per test, so a run
never touches the development database.

Two tests deserve mention. `test_real_fraud_row_is_scored_high_and_opens_a_case`
uses a verbatim confirmed-fraud row from the dataset rather than hand-made
numbers, so the model has to actually recognise real fraud. And
`test_missing_artifacts_degrade_instead_of_crashing` asserts the app starts and
reports its state through `/health` when the model is absent, instead of dying
at import.

---

## Docker

```bash
docker compose up --build
```

Then open <http://localhost:5000>.

One service, because that is all this needs: SQLite is a file and the frontend is
static, so a database container or reverse proxy would be architecture for its
own sake. The image runs as a non-root user, has a health check, and mounts a
named volume so scored transactions survive a rebuild. Gunicorn with two workers
serves it.

```bash
docker compose down          # stop
docker compose down -v       # stop and discard stored transactions
```

---

## Configuration

Everything is environment-driven; nothing secret is committed. Copy
`.env.example` to `.env` and adjust.

| Variable | Default | Purpose |
|---|---|---|
| `FRAUD_THRESHOLD` | `0.5` | Probability at or above which a transaction is fraud |
| `RISK_HIGH_THRESHOLD` | `0.70` | Risk score for HIGH |
| `RISK_MEDIUM_THRESHOLD` | `0.40` | Risk score for MEDIUM |
| `DATABASE_PATH` | `data/dhanraksha.db` | SQLite location |
| `ARTIFACT_DIR` | `ml/artifacts` | Where model artifacts are loaded from |
| `AUTO_CREATE_CASES` | `true` | Open a case automatically on HIGH risk |
| `SECRET_KEY` | dev placeholder | Must be changed for any shared deployment |
| `TRAIN_N_JOBS` | `-1` | Training parallelism; set to `1` on low-memory machines |

`.env.example` also carries commented Azure placeholders so the shape of
Milestone 2 configuration is visible. **No Azure resource exists and none is
referenced by running code.**

---

## Project structure

```
DhanRaksha/
├── backend/
│   ├── app.py                 application factory + service container
│   ├── config.py              environment-driven configuration
│   ├── errors.py              error types and JSON handlers
│   ├── routes/                HTTP only — no business logic
│   │   ├── prediction.py  transactions.py  analytics.py
│   │   ├── cases.py       system.py
│   ├── services/
│   │   ├── fraud_service.py       end-to-end orchestration
│   │   ├── risk_engine.py         deterministic scoring
│   │   ├── model_service.py       artifact loading and inference
│   │   ├── transaction_service.py history and analytics
│   │   └── case_service.py        case lifecycle
│   ├── repositories/
│   │   ├── base.py            abstract interfaces ← the Cosmos seam
│   │   ├── database.py        SQLite connection and schema
│   │   └── sqlite_repository.py
│   └── schemas/validators.py  input validation
├── ml/
│   ├── preprocessing.py       shared by training AND inference
│   ├── train.py               reproducible pipeline
│   ├── evaluate.py            metrics and threshold analysis
│   └── artifacts/             fraud_model.pkl · feature_pipeline.pkl · model_metadata.json
├── frontend/
│   ├── index.html             SPA shell
│   ├── css/dhanraksha.css     original design system, extracted
│   └── js/                    api.js · charts.js · app.js
├── tests/                     84 tests
├── docs/                      architecture · api · ml-pipeline · development
├── data/                      SQLite file; creditcard.csv goes here (gitignored)
├── Dockerfile · docker-compose.yml
├── requirements.txt · .env.example · .gitignore · pytest.ini
└── README.md
```

---

## Limitations

Stated plainly, because a fraud system that overstates itself is worse than none.

**This is not a production fraud system.** It has no authentication, no rate
limiting, no audit trail, no model monitoring, and no drift detection. Anyone who
can reach the API can score transactions and modify cases.

**The data is from 2013 and anonymised.** Two days of European card
transactions, PCA-transformed. Fraud patterns have changed substantially since;
nothing here generalises to live payment traffic.

**Features have no meaning.** `V1`–`V28` are PCA components. When the engine
flags `V14` as anomalous it cannot say *what* is anomalous, which limits how
useful the explanation is to a human reviewer.

**Metrics come from one split.** A single stratified 80/20 split with
`random_state=42`. No cross-validation, no repeated runs, no confidence
intervals. With only 95 fraud cases in the test set, one or two
reclassifications move recall by a full percentage point — treat differences
below ~2% as noise.

**No behavioural signals exist.** The dataset has no customer identity, device,
geography or history, so the most valuable fraud signals in a real system are
simply absent.

**`Time` is approximated at inference.** The API accepts hour-of-day, because
that is what a human can supply, and maps it onto the first day of the dataset's
timeline. Training uses the true `Time` value. This is a documented mismatch;
`Time` has low feature importance, so the effect is small, but it is not zero.

**SMOTE synthesises fraud that never happened.** Interpolating between minority
neighbours can produce combinations that do not occur in reality. It helps here,
but it is a modelling assumption, not a free lunch.

---

## Roadmap: Milestone 2 and 3

**No Azure resource has been created, and no Azure SDK is imported by any code
in this repository.** Milestone 1 runs entirely locally, by design.

Milestone 1 was built so Milestone 2 is mostly substitution rather than rewriting:

| Milestone 1 | Milestone 2 |
|---|---|
| `SqliteTransactionRepository` | `CosmosTransactionRepository` (same interface) |
| Local `ml/artifacts/` | Azure Blob Storage |
| `.env` file | Key Vault + App Service settings |
| `python -m backend.app` | Azure App Service (same Docker image) |
| Python logging | Application Insights |
| Open API | Microsoft Entra ID |

Milestone 3 adds behavioural signals through the seam already present in the
risk engine, plus richer analytics. If an LLM appears at all, it will summarise
cases for analysts — **it will never make the fraud decision**, which stays with
deterministic rules and the model.

Target Azure spend is under USD 60 of the USD 100 student credit, using free
tiers, consumption pricing, and shutting resources down when idle.

---

## Credits

Original DhanRaksha / FraudShield AI project — Khushi Agarwal, Avantika
Bhattacharya, Shreyas Birje, Meenakshi S Nair, Saketh Kallakuri, Shreyansh
Bhaik. Department of Data Science and Engineering.

Dataset: Machine Learning Group, Université Libre de Bruxelles (MLG-ULB), via
Kaggle.
