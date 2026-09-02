# Architecture

How DhanRaksha 2.0 is put together, and why. This document records decisions and
their reasoning, so a future change can tell whether it is contradicting
something deliberate or just something inherited.

---

## 1. Layering

```
frontend/            static SPA, no build step
    │  HTTP
backend/routes/      HTTP concerns only: parse, delegate, serialise
    │
backend/services/    all business logic
    │
backend/repositories/ storage interfaces + one implementation
    │
SQLite               a file
```

The rule that keeps this honest: **a layer may only call downward.** Routes
never touch repositories. Services never import Flask. Repositories know nothing
about fraud.

A concrete consequence: `FraudService.predict()` has no reference to `request`,
`jsonify`, or any HTTP concept. It takes a validated dictionary and returns a
dictionary. An Azure Function or a queue consumer in Milestone 2 can call the
identical method.

---

## 2. Where the ML boundary sits

The most common failure in ML applications is training/serving skew — the model
sees differently-shaped data in production than it saw in training, and quietly
degrades.

DhanRaksha eliminates the possibility structurally: there is exactly one
preprocessing implementation, `ml/preprocessing.FeaturePipeline`, imported by
both `ml/train.py` and `backend/services/model_service.py`. The fitted scaler is
serialised to `feature_pipeline.pkl` during training and loaded by the backend.

```
ml/preprocessing.py  ←── imported by ──→  ml/train.py
        │                                      │ fits, saves
        └──── imported by ──→ ModelService  ←──┘ loads artifact
```

There is no second copy of the scaling logic to fall out of sync. The original
project had exactly that problem: `train_model.py` scaled inside the training
script while `app.py` rebuilt the feature vector by hand in `build_feature_array`,
with a comment explaining the column order — a comment that would silently become
wrong the moment training changed.

---

## 3. Decision records

### ADR-1: The scaler is fitted after the train/test split

**Context.** The original `train_model.py` ran
`scaler.fit_transform(X[['Time','Amount']])` on the full frame, then split.

**Problem.** The scaler's mean and standard deviation are computed partly from
test rows. The model therefore trains on features normalised with information
from data it is supposed to have never seen. The effect is small for two columns,
but it is leakage, and it invalidates the claim that the test set is untouched.

**Decision.** `FeaturePipeline.fit()` is called only on `X_train`.

**Consequence.** Reported metrics are trustworthy. Precision, recall and F1 came
out identical to four decimals against the previous artifacts, confirming the
leakage was not materially inflating results — but the claim is now defensible
rather than merely probably fine.

---

### ADR-2: The risk engine is separate from the model

**Context.** The original code classified risk inline in the Flask route:
`"High" if probability > 0.7 else "Medium" if probability > 0.4 else "Low"`.

**Problems.** Thresholds were untestable without an HTTP request, changing policy
meant editing a route, and the risk level carried no explanation.

**Decision.** A standalone `RiskEngine` class taking probability plus transaction
attributes and returning a level, a score, named signals, and per-rule
explanations.

**Consequences.** Policy changes need no retraining. The engine is unit-tested in
isolation (13 tests). Every decision is explainable. Rule thresholds are loaded
from training-derived statistics rather than being constants.

**Constraint accepted.** Rules add risk only, capped at 0.25 total, so the model
remains dominant and rules cannot manufacture a HIGH from a confidently-safe
score.

---

### ADR-3: Storage behind an abstract interface

**Context.** Milestone 2 replaces SQLite with Cosmos DB.

**Decision.** `TransactionRepository` and `CaseRepository` are ABCs in
`repositories/base.py`. Services depend on those types. `SqliteTransactionRepository`
is one implementation.

**Consequence.** Milestone 2 writes `CosmosTransactionRepository` and changes
`build_container()` in `app.py`. No service, route or test changes. Records are
stored in a document-friendly shape (JSON columns for signals, rules and
features) so they map onto Cosmos documents without restructuring.

**Cost accepted.** More indirection than a small app strictly needs. Justified
only because the migration is a known, scheduled requirement — not speculative
generality.

---

### ADR-4: SQLite rather than Postgres

**Decision.** SQLite for Milestone 1.

**Reasoning.** It is a file. No container, no connection string, no daemon.
`git clone && pip install && python -m backend.app` and the system works. Adding
Postgres would mean a database container in compose, buying operational
complexity for concurrency this project will never see. ADR-3 makes the choice
reversible.

**Configuration.** WAL journal mode and per-thread connections, so Gunicorn's
two workers do not trip over each other.

---

### ADR-5: The frontend stays a single-page application

**Context.** The brief sketched separate `dashboard.html`, `transactions.html`,
`cases.html` files.

**Decision.** One `index.html` with six sections, sharing one shell, one API
client and one chart layer.

**Reasoning.** The alternative duplicates the sidebar, health badge, API client
and Chart.js setup across five documents. A fix to the error handler would need
applying five times. There is no build step and no framework — three plain
scripts and one stylesheet.

**Preserved.** The original design system is kept verbatim in
`css/dhanraksha.css` (604 lines lifted unchanged, new components appended). The
work worth keeping was the visual design; the work worth discarding was the
hardcoded data.

---

### ADR-6: The model never fabricates, and the application never overrides

Two rules, both enforced by tests:

**Probabilities come only from the model.** `FraudService` calls
`predict_proba` and passes the value through. There is no fallback path that
invents a probability when the model is missing — `/predict` returns 503
`MODEL_UNAVAILABLE` instead.

**No LLM in the decision path.** The fraud decision is a threshold on a Random
Forest probability, adjusted by deterministic rules. If a language model appears
in Milestone 3, it will summarise cases for analysts and nothing more.

---

### ADR-7: The application starts even when the model does not

**Context.** The original `app.py` loaded artifacts at import time and printed an
error if they were missing.

**Decision.** `ModelService.load()` catches failures, records the reason, and
leaves the service in a degraded state. `/health` reports it. `/predict` returns
503 with a clear message. Everything not requiring the model — history,
analytics, cases, the frontend — keeps working.

**Reasoning.** A container that will not start is harder to diagnose than one
that starts and tells you what is wrong. This also matters for Milestone 2, where
artifacts arrive from Blob Storage and may briefly be unavailable.

---

## 4. Error handling

One rule: **internal detail never reaches the client.**

```
ApiError subclass raised   →  its own code and message, as intended
werkzeug HTTPException     →  mapped to a JSON code (never an HTML page)
any other Exception        →  logged with traceback + incident ID;
                              client gets INTERNAL_ERROR + that ID
```

The original returned `jsonify({"error": str(e)})` on any exception, which could
expose file paths, library internals and query fragments. The incident ID lets a
user report a failure and an operator find the exact log line, without either
seeing the other's information.

---

## 5. Request lifecycle

```
POST /api/v1/predict
  │
  ├─ routes/prediction.py
  │     validate_prediction_payload()      ← rejects before any work is done
  │
  ├─ services/fraud_service.py
  │     ├─ FeaturePipeline.transform_transaction_frame()
  │     │     Time  = hour × 3600, scaled with the training-fitted scaler
  │     │     Amount scaled likewise; V1–V28 pass through untouched
  │     │
  │     ├─ RandomForest.predict_proba()    ← the only source of probability
  │     │
  │     ├─ RiskEngine.assess()
  │     │     score = probability + min(0.25, Σ rule weights)
  │     │     band  = HIGH ≥ 0.70 | MEDIUM ≥ 0.40 | LOW
  │     │
  │     ├─ TransactionService.record()     ← persisted before responding
  │     │
  │     └─ CaseService.open_case_for_transaction()   if HIGH
  │
  └─ 201 Created
```

Persistence happens before the response is returned, so a client that receives
201 can rely on the transaction being retrievable.

---

## 6. Milestone 2 mapping

Where each component moves, and what changes:

| Component | Milestone 1 | Milestone 2 | Code change |
|---|---|---|---|
| Web + API | `python -m backend.app` | App Service (B1/free) | none — same image |
| Storage | `SqliteTransactionRepository` | `CosmosTransactionRepository` | new class, one line in `build_container()` |
| Artifacts | `ml/artifacts/` | Blob Storage | `ModelService` gains a download step |
| Secrets | `.env` | Key Vault | `config.py` gains a resolver |
| Logging | Python logging | Application Insights | handler added in `create_app()` |
| Auth | none | Entra ID | new middleware |

The interfaces that make this work already exist. Nothing in Milestone 2 should
require touching a service or a route.

---

## 7. What was deliberately not built

Recorded so these read as decisions rather than omissions:

- **No authentication.** Milestone 2, via Entra ID. Adding a bespoke auth system
  now would be thrown away.
- **No async processing.** Prediction takes milliseconds. A queue would be
  complexity without benefit; Azure Functions arrive in Milestone 2 for genuinely
  event-driven work.
- **No model registry or drift monitoring.** Real needs for a real system,
  disproportionate for one model trained on a static dataset. `model_version` in
  every stored record is the minimum groundwork.
- **No hyperparameter search.** The original Random Forest configuration was
  preserved deliberately, so measured differences are attributable to the
  pipeline fix rather than confounded by retuning.
- **No frontend framework.** Three scripts, no build step, no `node_modules`,
  nothing to keep patched.
