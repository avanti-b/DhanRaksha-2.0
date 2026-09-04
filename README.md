<div align="center">

# 🛡️ DhanRaksha 2.0

### Azure-Powered Real-Time Financial Fraud Detection & Risk Intelligence

[![Live Demo](https://img.shields.io/badge/Live_Demo-dhanraksha--api.azurewebsites.net-2ea44f?style=for-the-badge&logo=microsoftazure&logoColor=white)](https://dhanraksha-api.azurewebsites.net/)

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.5-F7931E?style=flat-square&logo=scikitlearn&logoColor=white)](https://scikit-learn.org)
[![Azure](https://img.shields.io/badge/Azure-App_Service_·_Cosmos_DB-0078D4?style=flat-square&logo=microsoftazure&logoColor=white)](https://azure.microsoft.com)
[![Tests](https://img.shields.io/badge/tests-120_passing-success?style=flat-square)](#-testing)

**[🌐 Open the live application →](https://dhanraksha-api.azurewebsites.net/)**

*No installation required. Works on desktop and mobile.*

</div>

---

## 📖 Overview

DhanRaksha scores card transactions for fraud risk, explains the reasoning behind each decision, persists the result, and opens a reviewable case when risk is high.

A trained Random Forest produces a fraud probability. A separate deterministic Risk Engine turns that probability into an action — combining it with transaction-level rules whose thresholds are measured from the training data rather than invented. Every decision is traceable to the rules that produced it.

| | |
|---|---|
| **Live application** | https://dhanraksha-api.azurewebsites.net/ |
| **REST API** | https://dhanraksha-api.azurewebsites.net/api/v1 |
| **Health check** | https://dhanraksha-api.azurewebsites.net/api/v1/health |
| **Hosting cost** | ~$0.05/month (every service on a free tier) |

> ⚠️ **Scope.** Student research project, not a production banking system. See [Limitations](#-limitations).

---

## 🗺️ Project Milestones

Built across three planned milestones, each fully completed before the next began.

<table>
<tr><th width="120">Milestone</th><th>Goal</th><th>Delivered</th><th width="90">Status</th></tr>
<tr>
<td><b>M1</b><br><sub>Local</sub></td>
<td>Turn a college prototype into a maintainable, testable local application</td>
<td>
- Layered architecture (routes → services → repositories)<br>
- Reproducible ML pipeline, leakage fixed<br>
- Deterministic Risk Engine<br>
- SQLite persistence + case management<br>
- Real dashboard on live API data<br>
- 84 tests, Docker, documentation
</td>
<td>✅</td>
</tr>
<tr>
<td><b>M2</b><br><sub>Azure</sub></td>
<td>Integrate with Azure without making Azure mandatory locally</td>
<td>
- Cosmos DB repositories behind the M1 interfaces<br>
- Blob Storage for model artifacts + reports<br>
- Azure Functions for async enrichment<br>
- Key Vault via managed identity<br>
- Entra ID roles (backend)<br>
- Application Insights<br>
- 105 tests
</td>
<td>✅</td>
</tr>
<tr>
<td><b>M3</b><br><sub>Public</sub></td>
<td>Make the whole application publicly usable from any device</td>
<td>
- Single App Service serving frontend + API<br>
- Removed the runtime dataset dependency<br>
- Windows PowerShell deployment tooling<br>
- Package validation + startup hardening<br>
- 120 tests
</td>
<td>✅</td>
</tr>
</table>

### What changed between milestones

**M1 fixed a real bug.** The original training script fitted the `StandardScaler` on the full dataframe *before* `train_test_split`, leaking test-set statistics into training. The scaler is now fitted on the training split only.

**M2 proved the abstraction held.** Swapping SQLite for Cosmos DB required one new file and one branch in `build_repositories()`. All 84 M1 tests passed unmodified — no service, route, or test changed.

**M3 removed a hidden deployment blocker.** The "Load a dataset sample" button read the 144 MB Kaggle CSV, which cannot ship. It now reads a 6 KB bundle of eight real labelled transactions, so the deployed demo works without the dataset.

---

## 🏗️ Architecture

```
  Browser (any device)
        │  https://dhanraksha-api.azurewebsites.net
        ▼
  ┌──────────────────────────────────────┐
  │      Azure App Service               │
  │  ┌────────────┐    ┌───────────────┐ │
  │  │  Frontend  │──▶│  Flask API    │  │   one app, one origin
  │  │  dashboard │    │  /api/v1/*    │ │
  │  └────────────┘    └───────┬───────┘ │
  └───────────────────────────┼──────────┘
                              ▼
                  ┌───────────────────────┐
                  │  Random Forest model  │  fraud probability
                  └───────────┬───────────┘
                              ▼
                  ┌───────────────────────┐
                  │     Risk Engine       │  LOW / MEDIUM / HIGH
                  └───────────┬───────────┘
                              ▼
                  ┌───────────────────────┐
                  │   Azure Cosmos DB     │  transactions + cases
                  └───────────┬───────────┘
                              ▼
                  ┌───────────────────────┐
                  │   Azure Functions     │  async enrichment
                  └───────────────────────┘

  Supporting: Blob Storage (artifacts) · Key Vault (secrets)
              Application Insights (monitoring) · Entra ID (roles)
```

**Frontend and API are one deployment.** The JavaScript calls `/api/v1` on whatever origin served the page, so no hostname is hardcoded and there is no second service to keep in sync. A test enforces this.

### Design decisions worth noting

| Decision | Reasoning |
|---|---|
| **One preprocessing module** | `ml/preprocessing.py` is imported by both training and inference, so training/serving skew is structurally impossible |
| **Risk Engine separate from the model** | Scoring policy can change without retraining; every decision stays explainable |
| **Storage behind an interface** | Services depend on abstract repositories, never on SQLite or Cosmos directly |
| **Rules add risk only, capped at 0.25** | The model stays dominant; rules cannot manufacture a HIGH from a confidently-safe score |
| **The Function annotates, never decides** | Two components that can both decide "is this fraud?" means two answers that can disagree |

---

## 🔄 Fraud Detection Flow

```
POST /api/v1/predict
  │
  ├─ Validate              reject malformed input before any work
  ├─ Preprocess            scaler fitted during training, loaded as an artifact
  ├─ Random Forest         predict_proba → fraud probability
  ├─ Risk Engine           probability + rule weights → LOW / MEDIUM / HIGH
  ├─ Persist               written to Cosmos before responding
  └─ Open case             automatically, if risk is HIGH
  
  → 201 Created, in roughly 20 ms
```

**Risk banding**

```
risk_score = model_probability + min(0.25, Σ triggered rule weights)

HIGH   ≥ 0.70        MEDIUM ≥ 0.40        LOW otherwise
```

**Rules** — every threshold measured from the training split, not invented:

| Rule | Weight | Fires when |
|---|---|---|
| `high_model_probability` | 0.10 | probability ≥ 0.70 |
| `elevated_model_probability` | 0.05 | 0.40 ≤ probability < 0.70 |
| `very_high_value_transaction` | 0.08 | amount ≥ p99.9 of training data (3,042.80) |
| `high_value_transaction` | 0.04 | p99 (1,016.16) ≤ amount < p99.9 |
| `zero_amount_probe` | 0.05 | amount = 0 — card-testing pattern |
| `elevated_risk_hour` | 0.05 | hour in {2, 3, 4, 5, 7, 11} |
| `anomalous_pca_components` | 0.04 each, max 0.12 | V14/V17/V12/V10/V4/V11 outside the range of 99% of legitimate traffic |

---

## 🤖 The Model

### Pipeline

```
dataset → clean → stratified split → fit scaler (TRAIN ONLY)
        → SMOTE (TRAIN ONLY) → Random Forest → evaluate on untouched test set
        → save versioned artifacts
```

**SMOTE is never applied to the test set.** Synthetic points are interpolations of real ones; evaluating on them would mean scoring the model on data derived from its own training set, inflating every metric.

### Dataset

[Credit Card Fraud Detection](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud) (MLG-ULB) — two days of European card transactions, September 2013.

| Property | Value |
|---|---|
| Raw rows | 284,807 |
| Exact duplicates removed | 1,081 |
| Rows after cleaning | 283,726 |
| Fraud | 473 (**0.167%**) |
| Features | `Time`, `V1`–`V28` (PCA), `Amount` |

Severe imbalance is the whole problem: predicting "legitimate" for everything scores 99.83% accuracy and catches nothing. Accuracy is therefore never reported as a headline metric.

### Results

Held-out test split — 56,746 transactions, 95 fraud, threshold 0.5, model `rf-v1`.

| Metric | Random Forest | Logistic Regression |
|---|---|---|
| Precision | **0.9114** | 0.0530 |
| Recall | **0.7579** | 0.8737 |
| F1 | **0.8276** | 0.1000 |
| ROC-AUC | **0.9662** | 0.9619 |
| PR-AUC | **0.8040** | — |

**Confusion matrix**

| | Predicted legitimate | Predicted fraud |
|---|---|---|
| **Actually legitimate** | 56,644 | 7 |
| **Actually fraud** | 23 | 72 |

**Why the baseline matters.** Logistic regression scores a *higher* recall and near-identical ROC-AUC, yet produced 1,479 false positives against 83 true positives — 95% of its alarms are wrong. ROC-AUC computes its false-positive rate against a denominator of 56,651, so 1,479 false alarms barely dents the curve while being operationally unusable. PR-AUC and raw FP/FN counts are reported precisely because they do not hide this.

### Threshold analysis

| Threshold | Precision | Recall | F1 | FP | FN |
|---|---|---|---|---|---|
| 0.30 | 0.7700 | 0.8105 | 0.7897 | 23 | 18 |
| 0.40 | 0.8736 | 0.8000 | **0.8352** | 11 | 19 |
| 0.50 | 0.9114 | 0.7579 | 0.8276 | 7 | 23 |
| 0.60 | 0.9324 | 0.7263 | 0.8166 | 5 | 26 |
| 0.70 | 0.9714 | 0.7158 | 0.8242 | 2 | 27 |

F1 peaks at **0.40**, not the 0.50 default. The operating point is a business decision — the cost of a missed fraud versus a declined customer — so it is set via `FRAUD_THRESHOLD` rather than hardcoded.

> **Note on reported metrics.** The original project paper reported P 0.934 / R 0.844 / F1 0.887 / ROC-AUC 0.971. Those figures were **not reproduced** and appear to come from a different run than the one that produced the shipped model. The numbers above are reproducible with a single documented command.

---

## ☁️ Azure Services

| Service | Purpose | Tier | Cost |
|---|---|---|---|
| **App Service** | Hosts the Flask API and serves the frontend | F1 Free | $0 |
| **Cosmos DB** | Transactions and cases — App Service has no durable disk | Free tier | $0 |
| **Blob Storage** | Model artifacts (~4.3 MB) + daily reports | Standard LRS | ~$0.05 |
| **Storage Queue** | Hands work to Functions without blocking the caller | included | $0 |
| **Azure Functions** | Async enrichment + scheduled daily report | Consumption | $0 |
| **Key Vault** | Secrets via managed identity | Standard | ~$0 |
| **Entra ID** | USER / ANALYST / ADMIN roles (backend) | Free | $0 |
| **App Insights** | Requests, latency, errors, prediction metrics | Workspace | $0 |

**Total ≈ $0.05/month.** Deliberately rejected: AKS, always-on VMs, Databricks, Synapse, Premium tiers, Event Hubs, multi-region — none justified at this scale.

### Cosmos DB design

```
Database: dhanraksha            400 RU/s SHARED by both containers
  ├── transactions              partition key: /risk_level
  └── cases                     partition key: /status
```

Shared throughput keeps the account inside the free tier's 1000 RU/s — per-container throughput would reserve 400 RU/s each. `/risk_level` makes the dominant "filter by risk" query single-partition; `/status` does the same for the analyst's open-case queue.

---

## 🚀 Running It

### Use the deployed app

**[https://dhanraksha-api.azurewebsites.net/](https://dhanraksha-api.azurewebsites.net/)** — nothing to install.

> First request after an idle period takes 10–30 seconds. The free tier sleeps when idle and reloads the model on wake.

### Run locally

No Azure account, credentials, or dataset needed.

```bash
git clone <your-repo-url>
cd DhanRaksha

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env              # Windows: copy .env.example .env

python -m backend.app
```

Open **http://localhost:5000**. Runs on SQLite with every Azure integration dormant:

```bash
curl http://localhost:5000/api/v1/health
# components.database.engine → "sqlite"
```

**Docker alternative:**

```bash
docker compose up --build
```

### Deploy to Azure

Windows, in **PowerShell** (not Command Prompt), from the project folder:

```powershell
az login

.\scripts\deploy.ps1 -CheckPackage   # build + validate the package, no upload
.\scripts\deploy.ps1 -Settings       # once: point the app at Cosmos + Key Vault
.\scripts\deploy.ps1 -Deploy         # package and upload
.\scripts\deploy.ps1 -Verify         # prove it works end to end
```

`-Verify` is not a ping: it scores a real fraud transaction, confirms the result persisted to Cosmos and read back, and checks analytics, cases, model-info and samples.

Troubleshooting: `.\scripts\deploy.ps1 -Logs`

---

## 📊 The creditcard.csv Question

**You do not need it.** The deployed application works fully without it, and it is not in the repository.

| Question | Answer |
|---|---|
| Needed for fraud prediction? | **No** — prediction uses the trained model in `ml/artifacts/` |
| Needed for the deployed app? | **No** — including the demo samples |
| What is it used for? | Training only: `ml/train.py`, `ml/evaluate.py` |
| Where does it go locally, if retraining? | `data/creditcard.csv` |
| Upload to Azure Blob Storage? | **No** — training is local; the cloud never reads it |

The "Load a dataset sample" button reads `ml/artifacts/sample_transactions.json` — a 6 KB bundle of **eight real transactions** copied verbatim from the dataset with their true labels, four fraudulent and four legitimate. These include **one fraud the model actually misses** (scores 0.28, below threshold), so the demo shows honest behaviour rather than a curated success.

**To retrain:**

```bash
# Download creditcard.csv from Kaggle → data/
python -m ml.train --data data/creditcard.csv --version rf-v1
```

---

## 🔌 API Reference

Base URL: `https://dhanraksha-api.azurewebsites.net/api/v1`

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Component status — model, database, Azure services |
| `GET` | `/model-info` | Model card, metrics, threshold analysis, risk config |
| `POST` | `/predict` | Score a transaction |
| `GET` | `/transactions` | History — filterable, paginated |
| `GET` | `/transactions/{id}` | One transaction plus its case |
| `GET` | `/analytics` | Aggregates over persisted predictions |
| `GET` | `/cases` | Case list with status counts |
| `GET` | `/cases/{id}` | One case plus its transaction |
| `POST` | `/cases` | Open a case for a scored transaction |
| `PATCH` | `/cases/{id}` | Update status, reviewer, resolution, notes |
| `GET` | `/sample-transactions` | Real labelled rows for the UI |
| `GET` | `/me` | Caller identity and roles |

**Example**

```bash
curl -X POST https://dhanraksha-api.azurewebsites.net/api/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"amount": 529.00, "hour": 0, "v1": -3.043541, "v14": -1.692029}'
```

```json
{
  "transaction_id": "TXN-22AACCF1E1",
  "prediction": "fraud",
  "fraud_probability": 1.0,
  "risk_level": "HIGH",
  "risk_score": 1.0,
  "risk_signals": ["high_model_probability"],
  "explanation": "Model scored this transaction at 100.0% fraud probability. Rules fired: high_model_probability. Risk classified HIGH.",
  "model_version": "rf-v1",
  "case_id": "CASE-B6EA8336"
}
```

Errors are always JSON, never HTML, never a stack trace:

```json
{ "error": "VALIDATION_ERROR", "message": "Amount must be a non-negative number." }
```

---

## 🧪 Testing

```bash
pytest
```

**120 tests, all passing**, in about 5 seconds. No Azure account required.

| File | Tests | Covers |
|---|---|---|
| `test_preprocessing.py` | 10 | Column order, scaling scope, artifact round-trip, cleaning |
| `test_risk_engine.py` | 13 | Banding, additive-only scoring, the 0.25 cap, determinism |
| `test_validation.py` | 15 | Missing fields, negatives, out-of-range, NaN/inf |
| `test_model.py` | 7 | Real artifact loading, 30-feature contract, graceful degradation |
| `test_api.py` | 11 | Every endpoint, persistence, JSON errors, empty-store analytics |
| `test_transactions.py` | 7 | Ordering, pagination, filters, decision context |
| `test_cases.py` | 12 | Lifecycle, referential integrity, auto-creation |
| `test_azure_config.py` | 12 | Backend switching, validation, secrets never in public output |
| `test_auth.py` | 9 | Role hierarchy, open when disabled, 401 shape when enabled |
| `test_deployment.py` | 15 | Frontend served by the API, no hardcoded hostname, works with no dataset |

Tests run against the **real trained artifacts** but a temporary database per test.

---

## 📁 Project Structure

```
DhanRaksha/
├── backend/
│   ├── app.py                     application factory + service container
│   ├── config.py                  environment config + Key Vault resolution
│   ├── errors.py                  error types and JSON handlers
│   ├── routes/                    HTTP only — no business logic
│   ├── services/
│   │   ├── fraud_service.py       end-to-end orchestration
│   │   ├── risk_engine.py         deterministic scoring
│   │   ├── model_service.py       artifact loading and inference
│   │   ├── transaction_service.py history and analytics
│   │   └── case_service.py        case lifecycle
│   ├── repositories/
│   │   ├── base.py                abstract interfaces — the storage seam
│   │   ├── sqlite_repository.py   local development
│   │   └── cosmos_repository.py   Azure — same interfaces
│   ├── auth/entra.py              Entra ID token validation + roles
│   ├── azure_integration/         key_vault · blob_storage · queue · telemetry
│   └── schemas/validators.py      input validation
├── ml/
│   ├── preprocessing.py           shared by training AND inference
│   ├── train.py                   reproducible pipeline
│   ├── evaluate.py                metrics and threshold analysis
│   └── artifacts/                 model · pipeline · metadata · samples
├── frontend/
│   ├── index.html                 SPA shell
│   ├── css/dhanraksha.css
│   └── js/                        api.js · charts.js · app.js
├── functions/                     Azure Functions app
├── scripts/
│   ├── deploy.ps1                 Windows deployment
│   └── upload_artifacts.py        publish a retrained model to Blob
├── tests/                         120 tests
├── docs/                          architecture · api · ml-pipeline
│                                  deployment · azure-cost-control
├── Dockerfile · docker-compose.yml · startup.sh
└── requirements.txt · requirements-azure.txt · requirements-deploy.txt
```

---

## ⚙️ Configuration

Every value is environment-driven; nothing secret is committed.

| Variable | Default | Purpose |
|---|---|---|
| `STORAGE_BACKEND` | `sqlite` | `sqlite` or `cosmos` — the entire database switch |
| `FRAUD_THRESHOLD` | `0.5` | Probability at or above which a transaction is fraud |
| `RISK_HIGH_THRESHOLD` | `0.70` | Risk score for HIGH |
| `RISK_MEDIUM_THRESHOLD` | `0.40` | Risk score for MEDIUM |
| `AUTO_CREATE_CASES` | `true` | Open a case automatically on HIGH risk |
| `KEY_VAULT_URL` | empty | When set, secrets come from the vault first |
| `AUTH_ENABLED` | `false` | Entra ID token validation and role checks |

On Azure these live in **App Service → Environment variables**, with secrets in **Key Vault**. No `.env` file is used in production. See `.env.example`.

---

## ⚠️ Limitations

Stated plainly, because a fraud system that overstates itself is worse than none.

**Not a production fraud system.** No rate limiting, no audit trail, no model monitoring, no drift detection.

**No authentication is enabled in the deployment.** The backend auth layer exists and is tested, but the frontend has no sign-in, so `AUTH_ENABLED=false`. Anyone with the URL can use the app. Do not treat it as private.

**The data is from 2013 and anonymised.** Fraud patterns have changed substantially; nothing here generalises to live payment traffic.

**Features have no meaning.** `V1`–`V28` are PCA components, so flagging `V14` as anomalous cannot say *what* is anomalous — limiting how useful the explanation is to a human reviewer.

**Metrics come from one split.** A single stratified 80/20 split with `random_state=42`. No cross-validation, no confidence intervals. With 95 fraud cases in the test set, one reclassification moves recall by 1.05pp — treat sub-2% differences as noise.

**No behavioural signals exist.** The dataset has no customer identity, device, geography or history. The Risk Engine exposes a `behavioural_signals` seam rather than inventing them.

**`Time` is approximated at inference.** Training uses the dataset's true `Time`; the API accepts hour-of-day and maps it to `hour × 3600`. Low feature importance, so small effect, but a genuine train/serve mismatch.

**Cosmos analytics load every document.** Fine at demo scale, wrong past tens of thousands.

---

## 🔮 Future Work

- **Frontend sign-in** — MSAL.js so the browser can obtain a token and role-based navigation applies
- **Behavioural signals** — real device, velocity and geography inputs through the existing seam
- **Materialised analytics** — a summary document maintained by the Function instead of reading every record
- **Fraud-analyst copilot** — if a language model is ever added, it will summarise cases for reviewers. **It will never make the fraud decision** — that stays with the deterministic rules and the model.

---

## 📚 Documentation

| Document | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Layering, decision records, Milestone 2 mapping |
| [`docs/api.md`](docs/api.md) | Full endpoint reference with examples |
| [`docs/ml-pipeline.md`](docs/ml-pipeline.md) | Training, evaluation, threshold reasoning |
| [`docs/deployment.md`](docs/deployment.md) | Windows deployment walkthrough |
| [`docs/azure-deployment.md`](docs/azure-deployment.md) | First-time Azure resource setup |
| [`docs/azure-cost-control.md`](docs/azure-cost-control.md) | Cost breakdown, guardrails, teardown |
| [`docs/development.md`](docs/development.md) | Contributing conventions |


---

<div align="center">

**[🌐 Open the live application](https://dhanraksha-api.azurewebsites.net/)**


</div>

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

### Cosmos DB (Azure)

`STORAGE_BACKEND=cosmos` switches to Cosmos. **Nothing else changes** — the
Cosmos classes implement the same abstract interfaces, with identical method
signatures, verified by test.

```
Database: dhanraksha            400 RU/s SHARED by both containers
  ├── transactions              partition key: /risk_level
  └── cases                     partition key: /status
```

**Why shared throughput.** Per-container throughput reserves a minimum 400 RU/s
*each*, which would put the account at 800 RU/s. Sharing one 400 RU/s allocation
keeps the whole application inside the free tier's 1000 RU/s with headroom.

**Why `/risk_level` for transactions.** The dominant queries are "recent
transactions" and "filter by risk level", and this makes the filtered query
single-partition, which is the cheapest kind in RU terms. It gives only three
logical partitions, which is normally a warning sign since a logical partition
caps at 20 GB — but at roughly 2 KB per document that is about 10 million
transactions per risk band. At real volume the right key would be a composite
like `/yyyymm_risk`; that is noted in the code rather than implemented, because
at demo scale it would be over-engineering.

**Why `/status` for cases.** Analysts read "the open queue" far more than
anything else, so that view becomes single-partition. A status change moves the
document between partitions, which the repository handles as create-then-delete,
ordered so a failure leaves a recoverable duplicate rather than a lost case.

**Document shape** is identical to the SQLite row shape, so the same service
code reads both. Cosmos requires an `id`, set to the transaction or case ID.
Fields SQLite stored as JSON strings are native objects here.

**Analytics** are computed differently on purpose: SQLite pushes `GROUP BY` into
the engine, while the Cosmos repository pulls one small projection and groups in
Python. Six separate aggregate queries per dashboard load would burn RUs for no
benefit at this scale. Past tens of thousands of documents, the right move is a
materialised summary document maintained by the Function.

**What is still not stored:** no cardholder name, card number, merchant or
location — the dataset contains none and none is invented.

---

## Authentication

**Off by default.** With `AUTH_ENABLED=false` (the local default) every endpoint
is open, no tenant is needed, and the test suite runs clean. Turn it on only for
the Azure deployment.

### Roles

Defined as App Roles on the Entra app registration and assigned to users in
Enterprise applications.

| Role | Can |
|---|---|
| `USER` | Submit transactions for scoring |
| `ANALYST` | Everything USER can, plus all transactions, analytics and fraud cases |
| `ADMIN` | Everything ANALYST can, plus updating and resolving cases |

Roles are hierarchical: an ADMIN token satisfies a requirement for ANALYST.

### Endpoint protection

| Endpoint | Required role |
|---|---|
| `GET /health` | none — stays public so Azure's probe works |
| `GET /me` | none — returns the caller's identity |
| `GET /model-info` | none |
| `POST /predict` | `USER` |
| `GET /transactions`, `/transactions/{id}` | `ANALYST` |
| `GET /analytics` | `ANALYST` |
| `GET /cases`, `POST /cases` | `ANALYST` |
| `PATCH /cases/{id}` | `ADMIN` |

### How validation works

The caller sends `Authorization: Bearer <token>`. The API fetches the tenant's
public signing keys (JWKS, cached for an hour), verifies the RS256 signature,
checks audience, issuer and expiry, then reads the `roles` claim.

**The API needs no client secret** — it validates tokens, it does not issue
them. Nothing secret is stored for authentication at all.

> **Known gap.** The backend is complete and tested. The **frontend has no
> sign-in button** — there is no MSAL.js integration yet, so with
> `AUTH_ENABLED=true` the browser UI cannot obtain a token and its calls return
> 401. Test the protected API with Postman or the Azure CLI. Wiring MSAL.js into
> the frontend is Milestone 3 work. Leave `AUTH_ENABLED=false` for a UI demo.

---

## Monitoring

Application Insights collects:

- HTTP requests, latency and status codes (automatic)
- Dependency calls to Cosmos and Blob (automatic)
- Unhandled exceptions with stack traces, server-side only (automatic)
- One custom event per prediction: **latency, risk band, model version,
  decision**

**What is deliberately not sent:** transaction amounts, PCA feature values and
transaction IDs stay out of telemetry. Monitoring should not become a second,
less-protected copy of the data.

**Where to look:**

| View | Path | Shows |
|---|---|---|
| Live Metrics | App Insights → Live metrics | Real-time traffic, good for demos |
| Failures | App Insights → Failures | Errors grouped by type |
| Performance | App Insights → Performance | Latency per endpoint |
| Logs | App Insights → Logs | KQL queries |

Prediction latency query:

```kusto
traces
| where customDimensions has "dhanraksha.prediction.duration_ms"
| project timestamp,
          duration = customDimensions["dhanraksha.prediction.duration_ms"],
          risk = customDimensions["dhanraksha.prediction.risk_level"]
| order by timestamp desc
```

**Cost guard:** set a 0.5 GB/day cap at Log Analytics workspace → Usage and
estimated costs → Daily cap. Runaway log ingestion is the classic way to spend
money by accident.

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
| GET | `/me` | The caller's identity and roles | 200 |

When `AUTH_ENABLED=true`, protected endpoints return `401 UNAUTHORIZED` without
a valid token and `403 FORBIDDEN` when the token lacks the required role. See
[Authentication](#authentication) for the role matrix.

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

**120 tests, all passing**, in about 5 seconds. No Azure account required — the
Azure tests verify configuration, validation and interface conformance without
contacting Azure.

| File | Tests | Covers |
|---|---|---|
| `test_preprocessing.py` | 10 | Column order, that only Time/Amount are scaled, artifact round-trip, cleaning |
| `test_risk_engine.py` | 13 | Banding, additive-only scoring, the 0.25 cap, determinism, every rule |
| `test_validation.py` | 15 | Missing fields, negatives, out-of-range hours, NaN/inf, numeric strings |
| `test_model.py` | 7 | Real artifact loading, 30-feature contract, determinism, graceful degradation |
| `test_api.py` | 11 | Every endpoint, persistence round-trip, JSON errors, empty-store analytics |
| `test_transactions.py` | 7 | Ordering, pagination, filters, stored decision context |
| `test_cases.py` | 12 | Lifecycle, referential integrity, duplicate conflict, auto-creation |
| `test_azure_config.py` | 12 | Backend switching, config validation, secrets never in public output |
| `test_auth.py` | 9 | Role hierarchy, open when disabled, 401 shape when enabled |
| `test_deployment.py` | 15 | Frontend served by the API app, no hardcoded hostname, works with no dataset, package imports from a foreign working directory |

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

**Azure settings** (all optional; empty locally):

| Variable | Default | Purpose |
|---|---|---|
| `STORAGE_BACKEND` | `sqlite` | `sqlite` or `cosmos` — the whole database migration |
| `COSMOS_ENDPOINT` / `COSMOS_KEY` | empty | Cosmos connection |
| `STORAGE_CONNECTION_STRING` | empty | Blob Storage and the queue |
| `LOAD_ARTIFACTS_FROM_BLOB` | `false` | Download the model at startup |
| `ASYNC_PROCESSING_ENABLED` | `false` | Enqueue for the Function |
| `KEY_VAULT_URL` | empty | When set, secrets come from the vault first |
| `AUTH_ENABLED` | `false` | Entra ID token validation and role checks |
| `ENTRA_TENANT_ID` / `ENTRA_CLIENT_ID` | empty | Entra app registration |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | empty | Monitoring |
| `TELEMETRY_SAMPLE_RATE` | `1.0` | Fraction of telemetry sent |

Configuration is **validated at startup**. A misconfigured deployment logs a
readable message — `STORAGE_BACKEND=cosmos requires COSMOS_ENDPOINT` — rather
than failing with an SDK stack trace on the first request.

See [What I need to configure manually](#what-i-need-to-configure-manually) for
where each value comes from.

---

## Project structure

```
DhanRaksha/
├── backend/
│   ├── app.py                 application factory + service container
│   ├── config.py              environment-driven configuration + Key Vault
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
│   │   ├── base.py            abstract interfaces — the storage seam
│   │   ├── database.py        SQLite connection and schema
│   │   ├── sqlite_repository.py    local development
│   │   └── cosmos_repository.py    Azure — same interfaces
│   ├── auth/entra.py          Entra ID token validation + roles
│   └── azure_integration/
│       ├── key_vault.py       secret retrieval via managed identity
│       ├── blob_storage.py    model artifacts + reports
│       ├── queue_client.py    async handoff producer
│       └── telemetry.py       Application Insights
│   └── schemas/validators.py  input validation
├── ml/
│   ├── preprocessing.py       shared by training AND inference
│   ├── train.py               reproducible pipeline
│   ├── evaluate.py            metrics and threshold analysis
│   └── artifacts/             fraud_model.pkl · feature_pipeline.pkl
│                              model_metadata.json · sample_transactions.json
├── frontend/
│   ├── index.html             SPA shell
│   ├── css/dhanraksha.css     original design system, extracted
│   └── js/                    api.js · charts.js · app.js
├── functions/                 Azure Functions app
│   ├── function_app.py        queue trigger + daily timer + health
│   ├── host.json · requirements.txt
│   └── local.settings.json.example
├── scripts/
│   ├── deploy.ps1             Windows deployment to App Service
│   ├── azure_setup.sh         first-time resource creation (Linux/macOS)
│   └── upload_artifacts.py    publish a retrained model to Blob
├── tests/                     105 tests
├── docs/                      architecture · api · ml-pipeline · development
│                              deployment · azure-deployment · azure-cost-control
├── data/                      SQLite file; creditcard.csv goes here (gitignored)
├── Dockerfile · docker-compose.yml · startup.sh
├── requirements.txt           local
├── requirements-azure.txt     Azure extras for local Azure work
├── requirements-deploy.txt    what App Service installs
├── .env.example · .gitignore · pytest.ini
└── README.md
```

---

## Cost control

**Estimated monthly cost: about $0.05.** Every service sits inside a free tier.

| Service | Tier | Free allowance | Cost |
|---|---|---|---|
| App Service | F1 Free | 60 CPU-min/day, 1 GB RAM | $0.00 |
| Cosmos DB | Free tier | 1000 RU/s + 25 GB, account lifetime | $0.00 |
| Blob Storage | Standard LRS | 5 GB (student) | ~$0.05 |
| Functions | Consumption | 1M executions + 400k GB-s/month | $0.00 |
| Key Vault | Standard | $0.03 per 10k operations | ~$0.00 |
| App Insights | Workspace | 5 GB ingestion/month | $0.00 |
| Entra ID | Free | 50,000 objects | $0.00 |

```
Estimated Azure usage:  $0.15 / $100 credit
Project ceiling:        $50
Headroom:               $49.85
```

**The only realistic way this project spends money** is moving App Service from
F1 to B1 (~$13/month) if the free tier runs short of memory. Three months of B1
is about $40 — inside the $50 ceiling, but most of the headroom. Try one
gunicorn worker first.

**Two things to do before creating anything:**

1. **Budget alert:** Cost Management → Budgets → $20, alerts at 50/80/100%.
   Azure has **no automatic spend cap**.
2. **Tick "Apply Free Tier Discount" when creating Cosmos DB.** It cannot be
   enabled afterwards, and forgetting it turns a $0 line into roughly
   $23/month. This is the single most expensive available mistake.

Full detail, including what was rejected and why:
**[docs/azure-cost-control.md](docs/azure-cost-control.md)**

**To delete everything:**

```bash
./scripts/azure_setup.sh teardown
```

or Portal → Resource groups → `rg-dhanraksha` → Delete resource group. Note that
Key Vault soft-deletes (recoverable 90 days, name stays reserved) and the Entra
app registration lives outside the resource group — both need separate removal.

---

## Troubleshooting

**Local app will not start: `ModuleNotFoundError: No module named 'ml'`**
Run from the project root with `python -m backend.app`, not
`python backend/app.py`.

**Deployed app fails with `ModuleNotFoundError: No module named 'backend'`**
Fixed. The package is now built with forward-slash entry names and validated
before upload, and `startup.sh` anchors itself to the application root. Check a
package without uploading: `.\scripts\deploy.ps1 -CheckPackage`. Details in
[docs/deployment.md](docs/deployment.md).

**`ModuleNotFoundError: No module named 'azure'`**
You set an Azure variable without installing the extras:
`pip install -r requirements-azure.txt`. Local development with default settings
needs none of them.

**App Service returns 502**
Check Log stream. Usually a missing dependency or F1 memory pressure — try
`--workers=1` in `startup.sh`.

**`components.database.engine` still says `sqlite` on Azure**
`STORAGE_BACKEND` is not `cosmos`, or the App Service was not restarted after
the setting changed.

**Cosmos 401 Unauthorized**
The key is wrong or truncated. Re-copy the PRIMARY KEY; it is long and easy to
clip.

**Key Vault lookups fail**
Managed identity is off, or the **Key Vault Secrets User** role was not assigned
to it. Assignments take a few minutes. The app logs a warning and falls back to
environment variables rather than crashing.

**Function never fires**
Confirm `ASYNC_PROCESSING_ENABLED=true` on the App Service, that
`ASYNC_QUEUE_NAME` matches on both apps, and that both use the same storage
account. Check Function App → Functions → `process_transaction` → Monitor.

**Frontend shows 401 after enabling auth**
Expected. The frontend has no MSAL.js sign-in yet — see
[Authentication](#authentication). Set `AUTH_ENABLED=false` for a UI demo.

**First request after idle is very slow**
Cold start. F1 has no Always On, so the app sleeps and reloads the model on
wake.

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

### Deployment specific

**The Cosmos path is verified by interface conformance, not against live
Cosmos.** Tests prove both repositories implement identical method signatures
and that `aggregate()` returns the same shape from the same data, and the Cosmos
logic was exercised against a fake container. Running `.\scripts\deploy.ps1
-Verify` after deploying is what confirms it against the real account.

**No authentication is enabled in the deployment.** `AUTH_ENABLED=false`, so
anyone with the URL can score transactions and view the dashboard. That is a
deliberate trade-off for a demonstrable student project — the backend auth
layer exists and is tested, but the frontend has no sign-in, so enabling it
would make the UI unusable. Do not treat the public URL as private.

**The frontend has no sign-in.** Backend auth is complete; MSAL.js integration
is not.

**Demo samples are eight fixed rows.** Enough to show real fraud and real
legitimate traffic, including one fraud the model misses, but not a substitute
for the full dataset when evaluating.

**Cosmos analytics load every document.** `aggregate()` pulls a projection of
all transactions and groups in Python. Fine for a demo, wrong past tens of
thousands of documents, where a materialised summary maintained by the Function
is the right design.

**Cosmos partition keys are low-cardinality.** Three risk levels, five case
statuses. Appropriate at this scale, documented in the code as something to
revisit at volume.

**A case status change moves partitions.** Handled as create-then-delete. If the
delete fails, a duplicate remains — logged, and preferred over losing the case.

**F1 App Service may not hold the model comfortably.** scikit-learn plus pandas
plus the forest is 300–400 MB per worker against a 1 GB limit. Documented with
mitigations rather than discovered in production.

---

## Future work

The application is deployed and usable. Things deliberately left undone:

**Frontend sign-in.** Backend authentication (Entra ID token validation, three
roles) is complete and tested, but there is no MSAL.js sign-in button, so the
UI cannot obtain a token. `AUTH_ENABLED` is `false` in the deployment. Wiring
MSAL.js in is the natural next step.

**Behavioural signals.** The risk engine has carried an empty
`behavioural_signals` seam since the start, unused because the dataset is
anonymised. Real device, velocity or geography signals would plug in there
without changing the engine's contract.

**Materialised analytics.** The Cosmos `aggregate()` reads every document and
groups in Python. Fine for a demo, wrong past tens of thousands of documents,
where a summary document maintained by the Function is the right design.

**If a language model is ever added**, it will summarise cases for human
reviewers. It will never make the fraud decision — that stays with the
deterministic rules and the model.

## Credits

Dataset: Machine Learning Group, Université Libre de Bruxelles (MLG-ULB), via
Kaggle.
