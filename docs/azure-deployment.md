# Azure deployment guide

Written for someone who has never used Azure. Every step says what you are
creating, why, what it costs, and exactly where to click.

**Do the steps in order. Do not create everything at once.** After each step,
check the running cost estimate at the bottom before continuing.

Everything here can also be done with the scripted equivalent:

```bash
./scripts/azure_setup.sh step1     # and so on
```

---

## Before you start

**1. Sign in to the portal:** <https://portal.azure.com>

**2. Find your Subscription ID** (you will need it, and it is not a secret):

> Portal → search "Subscriptions" → click your **Azure for Students**
> subscription → the **Subscription ID** is on the Overview page.

**3. Set a budget alert now, before creating anything.** This is the single
most important cost-control step:

> Portal → search "Cost Management" → **Budgets** → **+ Add**
> - Scope: your subscription
> - Name: `dhanraksha-budget`
> - Amount: **$20**
> - Alert conditions: 50%, 80%, 100% of budget
> - Alert recipients: your email

A budget does not stop spending, it emails you. Azure has no hard spend cap, so
the alert is your safety net.

**4. Optional but recommended — install the CLI:**
<https://learn.microsoft.com/cli/azure/install-azure-cli>

```bash
az login
az account set --subscription "<YOUR SUBSCRIPTION ID>"
```

---

## Step 1 — Resource group

**What it is.** A folder that holds related Azure resources. Deleting the group
deletes everything inside it, which makes cleanup a single action.

**Why DhanRaksha needs it.** Every Azure resource must live in one. It also
gives you a single place to see total project cost, and a single button to
remove everything when you are done.

**Cost: $0.** A resource group is free; only the resources inside it cost money.

**Create it:**

> Portal → search **Resource groups** → **+ Create**
> - Subscription: your Azure for Students subscription
> - Resource group: `rg-dhanraksha`
> - Region: **Central India** (closest to you; West Europe or East US also fine)
> - **Review + create** → **Create**

**Where to see it:** Portal → Resource groups → `rg-dhanraksha`

**How to delete it:** open the group → **Delete resource group** → type the name
to confirm. This removes every resource created in every step below.

> **Pick one region and use it for everything.** Resources in different regions
> pay egress charges to talk to each other, and it is the easiest way to
> accidentally spend money on this project.

---

## Step 2 — App Service

**What it is.** Managed web hosting. You give Azure your code; it runs it behind
an HTTPS URL with no server for you to patch.

**Why DhanRaksha needs it.** It is where the Flask API and the frontend actually
run. This replaces `python -m backend.app` on your laptop.

**How it connects.** It is the entry point of the whole architecture. It serves
`/api/v1/*` and the static frontend from one origin, exactly as it does locally.

**Cost: $0 on the F1 Free tier.** F1 gives 1 GB RAM, 1 GB storage and 60
CPU-minutes per day, shared infrastructure, no custom domain, no Always On.

> **The honest caveat about F1.** This app loads scikit-learn, pandas, numpy and
> a 4.3 MB Random Forest into memory — roughly 300–400 MB per worker. Two
> gunicorn workers may sit close to the 1 GB limit. If the app restarts
> repeatedly or returns 502s, the fix is either one worker (edit `startup.sh`)
> or the B1 tier at about **$13/month**. Try F1 first. See
> [azure-cost-control.md](azure-cost-control.md) before switching to B1.

**Create it:**

> Portal → search **App Services** → **+ Create** → **Web App**
> - Resource group: `rg-dhanraksha`
> - Name: `dhanraksha-<something-unique>` (this becomes your URL, and the name
>   is globally unique across all of Azure)
> - Publish: **Code**
> - Runtime stack: **Python 3.11**
> - Operating System: **Linux**
> - Region: same as your resource group
> - Pricing plan: click **Explore pricing plans** → **Free F1**
> - **Review + create** → **Create**

**Configure the startup command:**

> App Service → **Configuration** → **General settings**
> - Startup Command: `startup.sh`
> - **Save**

**Add the build setting:**

> App Service → **Settings** → **Environment variables** → **App settings**
> - `SCM_DO_BUILD_DURING_DEPLOYMENT` = `true`
> - **Apply**

This tells Azure to run `pip install -r requirements.txt` when you deploy.

**Deploy your code:**

```bash
./scripts/azure_setup.sh deploy
```

or manually:

```bash
zip -r deploy.zip . -x "*.git*" "venv/*" "*__pycache__*" \
  "data/creditcard.csv" "data/*.db*" ".env" "functions/*"
az webapp deploy --resource-group rg-dhanraksha \
  --name <YOUR-APP-NAME> --src-path deploy.zip --type zip
```

The first deployment takes several minutes because it installs scikit-learn.

**Your App Service URL:** `https://<YOUR-APP-NAME>.azurewebsites.net`

**Verify it:**

```bash
curl https://<YOUR-APP-NAME>.azurewebsites.net/api/v1/health
```

At this point the app runs on Azure but still uses SQLite on the container's
local disk. **That disk is wiped on every restart**, which is exactly why
Step 3 exists.

**Where to see it:** Portal → App Services → your app
**Logs:** App Service → **Log stream**
**To stop billing:** App Service → **Stop** (F1 is free anyway, so this only
matters if you move to B1). **To delete:** → **Delete**.

---

## Step 3 — Cosmos DB

**What it is.** A managed NoSQL document database. It stores JSON documents and
is billed by provisioned throughput (Request Units per second) plus storage.

**Why DhanRaksha needs it.** App Service has no durable disk — restart it and
your SQLite file is gone. Cosmos gives transactions and cases somewhere
permanent to live. This is the migration Milestone 1 was designed for.

**How it connects.** `STORAGE_BACKEND=cosmos` switches
`build_repositories()` from the SQLite classes to the Cosmos ones. Services,
routes and tests are unchanged.

**Cost: $0 with the free tier**, which gives the first **1000 RU/s and 25 GB
free for the lifetime of the account**. We provision 400 RU/s shared across both
containers, well inside that.

> **Two things to get right.** You may have only **one** free-tier Cosmos account
> per subscription, and you must tick the box **at creation time** — it cannot be
> enabled afterwards. If you miss it, delete the account and start again.

**Create it:**

> Portal → search **Azure Cosmos DB** → **+ Create**
> - Select **Azure Cosmos DB for NoSQL** → **Create**
> - Resource group: `rg-dhanraksha`
> - Account Name: `cosmos-dhanraksha-<unique>`
> - Location: same region
> - Capacity mode: **Provisioned throughput**
> - **Apply Free Tier Discount: Apply** ← the important one
> - **Review + create** → **Create** (takes 5–10 minutes)

**Create the database and containers:**

> Cosmos account → **Data Explorer** → **New Database**
> - Database id: `dhanraksha`
> - Tick **Provision throughput**, set **400** RU/s (Manual)
>
> Then **New Container** twice, both inside `dhanraksha`:
> - Container id `transactions`, Partition key `/risk_level`
> - Container id `cases`, Partition key `/status`
>
> Both should use the database's shared throughput — do **not** provision
> per-container throughput, or you will reserve 400 RU/s each and exceed the
> free allowance.

The application creates these itself on first start if you skip this, but doing
it here lets you confirm the throughput setting.

**Why those partition keys** is explained in
[`backend/repositories/cosmos_repository.py`](../backend/repositories/cosmos_repository.py)
and summarised in [architecture.md](architecture.md).

**Get your two values:**

| Value | Where |
|---|---|
| `COSMOS_ENDPOINT` | Cosmos account → **Overview** → **URI** |
| `COSMOS_KEY` | Cosmos account → **Settings** → **Keys** → **PRIMARY KEY** |

**Add them to App Service:**

> App Service → **Settings** → **Environment variables** → **App settings** →
> **+ Add** for each:
>
> - `STORAGE_BACKEND` = `cosmos`
> - `COSMOS_ENDPOINT` = your URI
> - `COSMOS_KEY` = your primary key *(temporary — Step 6 moves this to Key Vault)*
> - `COSMOS_DATABASE` = `dhanraksha`
>
> **Apply**, then **Restart** the App Service.

**Verify:**

```bash
curl https://<YOUR-APP-NAME>.azurewebsites.net/api/v1/health
# components.database.engine should now read "cosmos"
```

**Where to see your data:** Cosmos account → **Data Explorer** → `dhanraksha` →
`transactions` → **Items**

**Monitor spend:** Cosmos account → **Metrics** → chart **Total Request Units**.
Staying under 1000 RU/s means $0.

**To delete:** Cosmos account → **Delete account**.

---

## Step 4 — Blob Storage

**What it is.** Object storage for files, unrelated to the database. Cheap and
durable.

**Why DhanRaksha needs it, specifically two things:**

1. **Model artifacts (~4.3 MB).** With `LOAD_ARTIFACTS_FROM_BLOB=true`, App
   Service downloads the model at startup instead of using the copy baked into
   the deployment. That means you can retrain locally, upload, and restart —
   no redeploy.
2. **Daily reports (a few KB).** The scheduled Function in Step 5 writes a JSON
   summary here, giving an audit trail independent of the database.

It also holds the **queue** used for async processing in Step 5.

**What is deliberately NOT uploaded: `creditcard.csv`.** Training stays local,
so the cloud never needs the 144 MB dataset. Uploading it would add storage and
egress cost for zero benefit.

**Cost: about $0.05/month.** Hot LRS storage is roughly $0.018/GB/month and this
project stores well under 50 MB. Student subscriptions also include a 5 GB
allowance.

**Create it:**

> Portal → search **Storage accounts** → **+ Create**
> - Resource group: `rg-dhanraksha`
> - Storage account name: `stdhanraksha<unique>` (lowercase letters and digits
>   only, 3–24 characters)
> - Region: same region
> - Performance: **Standard**
> - Redundancy: **Locally-redundant storage (LRS)** ← the cheapest
> - **Review + create** → **Create**

**Create two containers and one queue:**

> Storage account → **Data storage** → **Containers** → **+ Container**
> - `model-artifacts` (private access)
> - `reports` (private access)
>
> Storage account → **Data storage** → **Queues** → **+ Queue**
> - `transaction-queue`

**Get the connection string:**

> Storage account → **Security + networking** → **Access keys** → **key1** →
> **Connection string** → **Show** → copy

**Upload your model:**

Put the connection string in your local `.env` as
`STORAGE_CONNECTION_STRING=...`, then:

```bash
pip install -r requirements-azure.txt
python scripts/upload_artifacts.py
```

**Add to App Service:**

> - `STORAGE_CONNECTION_STRING` = your connection string *(Step 6 moves this to Key Vault)*
> - `LOAD_ARTIFACTS_FROM_BLOB` = `true`
>
> **Apply** → **Restart**

**Verify:** `/api/v1/health` → `components.model.source` should read `blob`.

**Where to see it:** Storage account → **Containers** → `model-artifacts`
**To delete:** Storage account → **Delete**.

---

## Step 5 — Azure Functions

**What it is.** Serverless compute. Small functions that run in response to
events and scale to zero when idle.

**Why DhanRaksha needs it.** The synchronous API returns a scored decision in
about 20 ms and should stay that way. Work that does not need to block the
caller belongs here.

**How it connects:**

```
POST /api/v1/predict → score → persist → enqueue
                                            ↓
                            Function (queue trigger)
                                            ↓
                        enrichment written back to Cosmos
```

Two functions, deliberately only two:

| Function | Trigger | Does |
|---|---|---|
| `process_transaction` | queue message | Adds review priority (P1/P2/P3) and an SLA due date to the stored transaction |
| `daily_report` | timer, 06:00 UTC | Writes a JSON day summary to Blob Storage |

> **The Function does not decide fraud.** It annotates a decision the API
> already made. Scoring stays with the model and the risk engine so there is one
> source of truth.

**Cost: $0.** The Consumption plan includes a monthly free grant of **1,000,000
executions and 400,000 GB-s per subscription**. This produces one execution per
prediction plus one per day. The Function App reuses the Step 4 storage account,
so it adds no new storage cost.

**Create it:**

> Portal → search **Function App** → **+ Create** → **Consumption** hosting plan
> - Resource group: `rg-dhanraksha`
> - Function App name: `func-dhanraksha-<unique>`
> - Runtime stack: **Python**, Version **3.11**
> - Region: same region
> - Operating System: **Linux**
> - Storage account: **select the one from Step 4** (do not create a new one)
> - **Review + create** → **Create**

**Configure it:**

> Function App → **Settings** → **Environment variables** → **App settings**:
> - `COSMOS_ENDPOINT` = your Cosmos URI
> - `COSMOS_KEY` = your Cosmos primary key
> - `COSMOS_DATABASE` = `dhanraksha`
> - `COSMOS_TRANSACTIONS_CONTAINER` = `transactions`
> - `ASYNC_QUEUE_NAME` = `transaction-queue`
> - `BLOB_REPORTS_CONTAINER` = `reports`

**Deploy the Function code:**

Install the Core Tools (<https://learn.microsoft.com/azure/azure-functions/functions-run-local>), then:

```bash
cd functions
func azure functionapp publish <YOUR-FUNCTION-APP-NAME>
```

**Turn on the async handoff in App Service:**

> - `ASYNC_PROCESSING_ENABLED` = `true`
>
> **Apply** → **Restart**

**Verify:**

```bash
curl https://<YOUR-FUNCTION-APP-NAME>.azurewebsites.net/api/health
```

Then POST a prediction to the App Service; the response includes
`"queued_for_async_processing": true`. Within a few seconds the transaction
document in Cosmos gains an `async_processing` block.

**Where to see it:** Function App → **Functions** → click a function →
**Monitor** (invocation history and logs)
**To delete:** Function App → **Delete**.

---

## Step 6 — Key Vault

**What it is.** A managed secret store. Access is controlled by Azure identity
rather than by who can read a configuration page.

**Why DhanRaksha needs it.** Right now your Cosmos key and storage connection
string sit in App Settings as readable text. Anyone with portal read access on
the subscription can see them. Key Vault holds the value; App Service
authenticates with a **managed identity**, which means the app has no credential
of its own to leak.

**How it connects.** `config.secret()` checks Key Vault first for every
sensitive setting when `KEY_VAULT_URL` is set, and falls back to environment
variables otherwise. Locally the vault is never contacted.

**Cost: effectively $0.** Standard tier is about $0.03 per 10,000 operations.
The app reads four secrets at startup and caches them.

**Create it:**

> Portal → search **Key vaults** → **+ Create**
> - Resource group: `rg-dhanraksha`
> - Key vault name: `kv-dhanraksha-<unique>`
> - Region: same region
> - Pricing tier: **Standard**
> - Access configuration: **Azure role-based access control (RBAC)**
> - **Review + create** → **Create**

**Give yourself permission to add secrets:**

> Key vault → **Access control (IAM)** → **+ Add** → **Add role assignment**
> - Role: **Key Vault Secrets Officer**
> - Members: **User, group, or service principal** → select your own account
> - **Review + assign**

**Add the secrets** (names must match exactly — the app derives them by
lowercasing the env var and replacing `_` with `-`):

> Key vault → **Objects** → **Secrets** → **+ Generate/Import**

| Secret name | Value |
|---|---|
| `cosmos-key` | Cosmos primary key |
| `storage-connection-string` | Storage connection string |
| `secret-key` | Run `python -c "import secrets; print(secrets.token_hex(32))"` |
| `applicationinsights-connection-string` | From Step 7 |

**Give the App Service a managed identity:**

> App Service → **Settings** → **Identity** → **System assigned** → Status
> **On** → **Save** → **Yes**

**Grant that identity read access:**

> Key vault → **Access control (IAM)** → **+ Add** → **Add role assignment**
> - Role: **Key Vault Secrets User**
> - Members: **Managed identity** → **App Service** → select your app
> - **Review + assign**

**Point the app at the vault:**

> App Service → **Environment variables**:
> - `KEY_VAULT_URL` = `https://<your-vault>.vault.azure.net/`
>
> Then **delete** the now-redundant plain-text settings: `COSMOS_KEY`,
> `STORAGE_CONNECTION_STRING`, `SECRET_KEY`.
>
> **Apply** → **Restart**

**Verify:** `/api/v1/health` → `config.key_vault_enabled` is `true` and the app
still reaches Cosmos. If a lookup fails the app logs a warning and falls back to
environment variables rather than crashing — check **Log stream**.

**Where to see it:** Key vault → **Objects** → **Secrets**
**To delete:** Key vault → **Delete** (note: soft-delete keeps it recoverable
for 90 days by default).

---

## Step 7 — Application Insights

**What it is.** Application monitoring: request counts, latency, dependency
calls, exceptions, and custom metrics, with dashboards and a query language.

**Why DhanRaksha needs it.** On App Service there is no terminal to watch.
Insights is how you see that predictions are being served, how long scoring
takes, and what failed overnight.

**What is tracked** — kept deliberately narrow:

- HTTP requests and their latency (automatic)
- Outbound calls to Cosmos and Blob (automatic)
- Unhandled exceptions (automatic)
- One custom event per prediction: **latency, risk band, model version,
  decision**. No amounts, no PCA features, no transaction IDs.

**Cost: $0.** The first 5 GB of ingestion per month is free and this app sends
kilobytes per request. `TELEMETRY_SAMPLE_RATE` lets you send a fraction if you
ever load-test.

**Create it:**

> Portal → search **Application Insights** → **+ Create**
> - Resource group: `rg-dhanraksha`
> - Name: `appi-dhanraksha`
> - Region: same region
> - Resource mode: **Workspace-based** (a Log Analytics workspace is created
>   with it; its own free allowance is 5 GB/month)
> - **Review + create** → **Create**

**Connect it:**

> Application Insights → **Overview** → copy the **Connection String**
>
> Add it as the Key Vault secret `applicationinsights-connection-string`
> (preferred), or as the App Setting
> `APPLICATIONINSIGHTS_CONNECTION_STRING`. Then **Restart** the App Service.

Add the same connection string to the **Function App** settings so Function
failures are captured too.

**Where to look:**

| View | Path | Shows |
|---|---|---|
| Live Metrics | Insights → **Live metrics** | Real-time requests, useful during a demo |
| Failures | Insights → **Failures** | Every error, grouped |
| Performance | Insights → **Performance** | Latency per endpoint |
| Logs | Insights → **Logs** | Custom queries |

A query for prediction latency:

```kusto
traces
| where customDimensions has "dhanraksha.prediction.duration_ms"
| project timestamp,
          duration = customDimensions["dhanraksha.prediction.duration_ms"],
          risk = customDimensions["dhanraksha.prediction.risk_level"]
| order by timestamp desc
```

**Cap ingestion so it can never surprise you:**

> Log Analytics workspace → **Usage and estimated costs** → **Daily cap** →
> set **0.5 GB/day**

**To delete:** Application Insights → **Delete**, and delete the Log Analytics
workspace too.

---

## Step 8 — Microsoft Entra ID

**What it is.** Microsoft's identity service. It authenticates users and issues
signed JWT tokens carrying their assigned roles.

**Why DhanRaksha needs it.** Your App Service URL is public. Without
authentication, anyone who finds it can score transactions and modify fraud
cases.

**How it connects.** The API validates incoming tokens against your tenant's
public keys and reads the `roles` claim. Route decorators enforce which roles
reach which endpoint. The API only *validates* tokens — it never issues them —
so **it needs no client secret**.

**Roles:**

| Role | Can |
|---|---|
| `USER` | Submit transactions for scoring |
| `ANALYST` | Everything USER can, plus view all transactions, analytics and cases |
| `ADMIN` | Everything ANALYST can, plus resolve and update cases |

**Cost: $0.** Entra ID Free covers this and is included with every subscription.

**Register the application:**

> Portal → search **Microsoft Entra ID** → **App registrations** → **+ New registration**
> - Name: `DhanRaksha`
> - Supported account types: **Accounts in this organizational directory only**
> - Redirect URI: **Single-page application (SPA)** →
>   `https://<YOUR-APP-NAME>.azurewebsites.net`
> - **Register**

**Copy two values from the Overview page:**

| Value | Where |
|---|---|
| `ENTRA_TENANT_ID` | **Directory (tenant) ID** |
| `ENTRA_CLIENT_ID` | **Application (client) ID** |

Neither is secret — both are safe in App Settings.

**Define the three roles:**

> App registration → **App roles** → **+ Create app role**, three times:
>
> | Display name | Allowed member types | Value | Description |
> |---|---|---|---|
> | Fraud User | Users/Groups | `USER` | Can submit transactions |
> | Fraud Analyst | Users/Groups | `ANALYST` | Can view transactions, analytics and cases |
> | Fraud Admin | Users/Groups | `ADMIN` | Can review and resolve cases |

**Assign roles to people:**

> Portal → **Microsoft Entra ID** → **Enterprise applications** → `DhanRaksha`
> → **Users and groups** → **+ Add user/group** → pick a user → pick a role →
> **Assign**
>
> Assign yourself **ADMIN** first, or you will lock yourself out of the case
> endpoints.

**Expose the API scope:**

> App registration → **Expose an API** → **Add** next to Application ID URI →
> accept `api://<client-id>` → **Save**
> → **+ Add a scope**: name `access_as_user`, admin consent display name
> "Access DhanRaksha", **Add scope**

**Turn it on:**

> App Service → **Environment variables**:
> - `AUTH_ENABLED` = `true`
> - `ENTRA_TENANT_ID` = your tenant ID
> - `ENTRA_CLIENT_ID` = your client ID
> - `CORS_ORIGINS` = `https://<YOUR-APP-NAME>.azurewebsites.net`
>
> **Apply** → **Restart**

**Verify:**

```bash
curl https://<YOUR-APP-NAME>.azurewebsites.net/api/v1/analytics
# expect 401 UNAUTHORIZED
curl https://<YOUR-APP-NAME>.azurewebsites.net/api/v1/health
# expect 200 — health stays public so Azure's probe works
```

> **Known gap, stated plainly.** The backend validates tokens and enforces
> roles, and that is fully implemented and tested. The frontend does **not** yet
> have a sign-in button — it has no MSAL.js integration, so with
> `AUTH_ENABLED=true` the browser UI cannot obtain a token and its API calls
> will return 401. Test the protected API with a token from Postman or the Azure
> CLI. Wiring MSAL.js into the frontend is a Milestone 3 task. Leave
> `AUTH_ENABLED=false` if you need the UI working for a demo.

---

## Running cost estimate

| Step | Resource | Tier | Monthly | Notes |
|---|---|---|---|---|
| 1 | Resource group | — | **$0.00** | Free |
| 2 | App Service | F1 Free | **$0.00** | B1 fallback ≈ $13/mo |
| 3 | Cosmos DB | Free tier | **$0.00** | 400 of 1000 free RU/s |
| 4 | Storage | Standard LRS | **$0.05** | ~5 MB stored |
| 5 | Functions | Consumption | **$0.00** | Inside the free grant |
| 6 | Key Vault | Standard | **$0.00** | A few operations |
| 7 | App Insights | Workspace | **$0.00** | Inside 5 GB free |
| 8 | Entra ID | Free | **$0.00** | Included |
| | | **Total** | **≈ $0.05/mo** | |

**Projected total for a 3-month project: well under $1** on the F1 tier, or
**about $40** if you switch to B1 App Service for all three months.

Your ceiling is $50. Both paths stay inside it, but B1 for three months uses
most of the headroom — see [azure-cost-control.md](azure-cost-control.md).

---

## Troubleshooting

**App Service returns 502 / Application Error**
Check **Log stream**. Usually a missing dependency or memory pressure on F1. Try
one gunicorn worker in `startup.sh`.

**`components.database.engine` still says `sqlite`**
`STORAGE_BACKEND` is not set to `cosmos`, or the App Service was not restarted
after the setting changed.

**Cosmos 401 Unauthorized**
The key is wrong or truncated. Re-copy the **PRIMARY KEY** — it is long and easy
to clip.

**Key Vault lookups fail**
Managed identity is off, or the **Key Vault Secrets User** role was not assigned
to it. Role assignments can take a few minutes to take effect. The app falls
back to environment variables meanwhile.

**Function never fires**
Confirm `ASYNC_PROCESSING_ENABLED=true` on the App Service, that
`ASYNC_QUEUE_NAME` matches on both apps, and that both point at the same storage
account. Check Function App → Functions → `process_transaction` → **Monitor**.

**Everything is slow on the first request**
Cold start. F1 has no Always On, so the app sleeps when idle and pays for model
loading on the next request. Expected on the free tier.
