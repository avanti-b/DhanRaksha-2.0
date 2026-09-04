# Azure cost control

**Your budget: ~$100 Azure for Students credit.**
**Your ceiling for this project: $50.**
**Design target: under $5.**

This document exists because Azure has **no automatic spend cap**. Once you
cross a free limit, charges begin immediately and silently. Nothing throttles
you and nothing asks for confirmation.

---

## The estimate

Every service in this project was chosen for its free tier. Here is the whole
bill.

| Service | Tier chosen | Free allowance | This project uses | Monthly cost |
|---|---|---|---|---|
| Resource group | — | always free | 1 group | **$0.00** |
| App Service | **F1 Free** | 60 CPU-min/day, 1 GB RAM | a demo app | **$0.00** |
| Cosmos DB | **Free tier** | 1000 RU/s + 25 GB, account lifetime | 400 RU/s, <100 MB | **$0.00** |
| Blob Storage | Standard LRS Hot | 5 GB (student) | ~5 MB | **$0.05** |
| Storage Queue | Standard LRS | included above | a few thousand messages | **$0.00** |
| Azure Functions | **Consumption** | 1M executions + 400k GB-s/month | a few hundred executions | **$0.00** |
| Key Vault | Standard | — ($0.03/10k operations) | ~10 operations/restart | **$0.00** |
| Application Insights | Workspace-based | 5 GB ingestion/month | a few MB | **$0.00** |
| Microsoft Entra ID | Free | 50,000 objects | a handful of users | **$0.00** |
| | | | **Total** | **≈ $0.05/mo** |

**Three-month project total: well under $1.**

That is not a trick. Every allowance above is documented on Microsoft's own
pricing pages, and the architecture was sized to fit inside them rather than
sized first and priced afterwards.

---

## Running total

```
Estimated Azure usage:  $0.15 / $100 credit
Project ceiling:        $50
Headroom remaining:     $49.85
```

Update this after each billing period from
**Cost Management → Cost analysis**.

---

## The one decision that could cost real money

**App Service F1 → B1 is the only realistic way this project spends anything
meaningful.**

| Tier | RAM | Monthly | Always On | Notes |
|---|---|---|---|---|
| **F1 Free** | 1 GB | **$0.00** | No | 60 CPU-min/day; sleeps when idle |
| **B1 Basic** | 1.75 GB | **≈ $13** | Yes | No CPU quota, no cold starts |

**Why you might need B1.** The app loads scikit-learn, pandas, numpy and a
4.3 MB Random Forest — roughly 300–400 MB per gunicorn worker. Two workers can
press against F1's 1 GB limit, showing up as repeated restarts or 502s.

**Try these before paying:**

1. **Drop to one worker.** Edit `startup.sh`, change `--workers=2` to
   `--workers=1`. Halves memory. A demo does not need two.
2. **Accept cold starts.** F1 sleeps when idle, so the first request after a
   pause takes 10–30 seconds while the model loads. Annoying for a live demo,
   free the rest of the time.
3. **Only then consider B1.**

**If you do switch to B1:**

- 1 month = $13 → total ≈ $13. Comfortable.
- 3 months = $39 → total ≈ $40. Inside the $50 ceiling, but that is most of your
  headroom gone.
- **Stop the App Service when you are not demoing.** Portal → App Service →
  **Stop**. A stopped B1 plan still bills for the *plan*, so to truly stop
  paying you must delete the plan or scale it back to F1.
- Scale back down after your demo: App Service → **Scale up (App Service plan)**
  → **Free F1** → Apply.

**Ceiling check: even 3 months of B1 lands around $40, inside $50.** Anything
beyond that means something else went wrong — investigate before paying.

---

## What would blow the budget, and is therefore not used

These were considered and rejected. Recorded so the omissions read as decisions.

| Tempting option | Monthly | Why it is not here |
|---|---|---|
| Azure Kubernetes Service | $70+ | One Flask app does not need an orchestrator |
| Always-on VM (B2s) | $30+ | App Service does this for free |
| Azure ML managed endpoint | $100+ | Model loads in-process in ~1 second |
| Cosmos **without** the free-tier box ticked | $23+ | 400 RU/s at standard rates |
| Cosmos **autoscale** | $35+ | Minimum 1000 RU/s billed at autoscale rates |
| Cosmos with **per-container** throughput | $46+ | 400 RU/s × 2 containers, exceeding the free 1000 |
| Premium Functions | $150+ | Consumption is free at this volume |
| Event Hubs | $11+ | A Storage Queue does the same job for free |
| Azure OpenAI | usage-based | No LLM belongs in a fraud decision |
| Multi-region Cosmos | 2× everything | One region, one demo |
| Log Analytics without a daily cap | unbounded | A loop could ingest GBs overnight |

**The single most expensive mistake available to you** is forgetting the
**Apply Free Tier Discount** box when creating Cosmos DB. It cannot be enabled
afterwards — you would have to delete the account and recreate it — and it turns
a $0 line item into roughly $23/month.

---

## Guardrails to set up now

### 1. Budget alert — do this first

> Portal → **Cost Management** → **Budgets** → **+ Add**
> - Scope: your subscription
> - Amount: **$20**
> - Alerts at **50%**, **80%**, **100%**
> - Recipient: your email

$20 rather than $50 deliberately: it fires long before the ceiling, while you
still have room to react.

A budget **alerts**, it does not **stop**. Azure will keep spending past it.

### 2. Cap Application Insights ingestion

> Log Analytics workspace → **Usage and estimated costs** → **Daily cap** →
> **0.5 GB/day**

Log ingestion is the classic runaway cost: an error loop can produce gigabytes
overnight. The cap makes that impossible.

### 3. Watch the Cosmos RU chart

> Cosmos account → **Metrics** → Metric: **Total Request Units**

Stay under 1000 RU/s and Cosmos is free. If provisioned throughput ever reads
above 400, something changed the setting.

### 4. Check spend weekly

> Portal → **Cost Management** → **Cost analysis** → Scope: `rg-dhanraksha`
> → Group by: **Service name**

Any non-zero line you cannot explain is worth thirty seconds of investigation.

---

## Everyday cost hygiene

- **One region for everything.** Cross-region traffic is billed. Same region =
  free internal traffic.
- **Do not upload `creditcard.csv`.** It is 144 MB, training is local, and the
  cloud has no use for it. This alone avoids storage plus repeated egress.
- **Do not load-test.** A script hammering `/predict` burns Cosmos RUs,
  Function executions and Insights ingestion simultaneously. Demo with tens of
  requests, not thousands.
- **Delete failed experiments immediately.** A half-created Cosmos account with
  standard throughput bills whether you use it or not.
- **Check for orphans before you finish.** Deleted a VM but left its disk?
  Portal → **All resources**, sorted by type, catches leftovers.

---

## Stopping and deleting

### Pause without losing data

| Resource | How | Still billed? |
|---|---|---|
| App Service | Portal → App Service → **Stop** | F1: no. B1: yes, the *plan* bills |
| Function App | Portal → Function App → **Stop** | No |
| Cosmos DB | Cannot be stopped | Free tier: $0 regardless |
| Storage | Cannot be stopped | ~$0.05/mo regardless |

### Reduce to near zero, keep the data

1. App Service → **Scale up** → **Free F1**
2. Function App → **Stop**
3. Log Analytics → daily cap **0.1 GB**

Leaves you at roughly $0.05/month with everything recoverable.

### Delete everything

```bash
./scripts/azure_setup.sh teardown
```

or:

> Portal → **Resource groups** → `rg-dhanraksha` → **Delete resource group** →
> type the name → **Delete**

This removes every resource from every step. **All transactions and cases in
Cosmos are permanently lost.** Export anything you need first:

> Cosmos → **Data Explorer** → container → **Items** → select → **Download**

Two things survive a group delete and are worth knowing about:

- **Key Vault soft-delete.** The vault is recoverable for 90 days and its name
  stays reserved. To fully remove it:
  `az keyvault purge --name <vault-name>`
- **Entra app registration.** It lives in the directory, not the resource group.
  Delete separately: Entra ID → App registrations → your app → **Delete**.

**After deleting, confirm billing stopped:** Cost Management → Cost analysis →
the next day should show no new charges.

---

## If you approach the ceiling

Stop creating resources and work through this list in order:

1. **Cost analysis, grouped by service.** Find what is actually charging. Do not
   guess.
2. **Is Cosmos free tier actually on?** Cosmos → Overview. If it says the
   discount is not applied, that is almost certainly your bill. Export your
   data, delete the account, recreate it with the box ticked.
3. **Is App Service on B1?** Scale it back to F1.
4. **Is Insights ingesting heavily?** Check for an error loop; set the daily cap.
5. **Are there resources you forgot?** All resources → sort by type.
6. **Still unexplained?** Delete the resource group. Redeploying takes about
   thirty minutes from these docs, and your code, model and configuration are
   all in the repository.

Nothing in this project is precious enough to be worth an unexplained bill. The
whole environment is reproducible from `scripts/azure_setup.sh`.
