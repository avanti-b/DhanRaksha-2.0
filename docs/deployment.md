# Deploying DhanRaksha (Milestone 3)

Goal: one public HTTPS URL that anyone can open, on any device, with nothing
installed.

**This creates no new Azure resource.** It deploys to the App Service you
already made in Milestone 2 and reuses everything else.

---

## Why there is no separate frontend service

The Flask app already serves the frontend. `backend/app.py` has two routes at
the bottom that return `frontend/index.html` and its assets, and the JavaScript
calls the API at `/api/v1` on whatever origin the page came from.

So one deployment gives you both:

```
https://dhanraksha-api.azurewebsites.net/          → the dashboard
https://dhanraksha-api.azurewebsites.net/api/v1/*  → the API
```

Adding Static Web Apps or a second App Service would mean a second deployment,
a cross-origin setup, and a hostname baked into the frontend at build time.
Same origin avoids all three, and costs nothing extra.

---

## Before you start

Open **PowerShell** (not Command Prompt) in the project folder.

**1. Install the Azure CLI** if you have not already:
<https://aka.ms/installazurecliwindows>

**2. Sign in:**

```powershell
az login
```

**3. If PowerShell refuses to run the script**, allow it for this window only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**4. Confirm the Cosmos key is in Key Vault.** The app reads it from there
using the managed identity you set up in Milestone 2, which is why the key
never appears in any file or script:

```powershell
az keyvault secret show --vault-name dhanraksha-kv --name cosmos-key --query name
```

If that errors, create it (run this yourself, with your real key — never paste
it into a chat or a file):

```powershell
$key = az cosmosdb keys list --name dhanraksha-cosmos --resource-group DhanRaksha-RG --query primaryMasterKey -o tsv
az keyvault secret set --vault-name dhanraksha-kv --name cosmos-key --value $key
```

---

## Deploy

Three commands.

### 1. Configure the app settings (once)

```powershell
.\scripts\deploy.ps1 -Settings
```

Points the App Service at your existing resources: Cosmos as the storage
backend, your Key Vault for secrets, the `startup.sh` command, one gunicorn
worker, and a health-check path. It reads the Cosmos endpoint from the account
itself, so there is nothing for you to copy.

### 2. Deploy the code

```powershell
.\scripts\deploy.ps1 -Deploy
```

Stages a clean copy of `backend/`, `frontend/`, `ml/` and `startup.sh`, swaps in
the Azure requirements list, strips caches and any local database, zips it and
uploads.

**The first deploy takes 5–10 minutes** because Azure builds scikit-learn,
pandas and numpy. Later deploys are faster.

### 3. Verify

```powershell
.\scripts\deploy.ps1 -Verify
```

Checks health, that the frontend loads, that a real fraud row scores correctly
end to end, that the result persists in Cosmos and reads back, and that
analytics, cases, model-info and samples all respond.

All three at once:

```powershell
.\scripts\deploy.ps1 -All
```

---

## Your URLs

| | URL |
|---|---|
| **Frontend** | `https://dhanraksha-api.azurewebsites.net/` |
| **API** | `https://dhanraksha-api.azurewebsites.net/api/v1` |
| Health | `https://dhanraksha-api.azurewebsites.net/api/v1/health` |

Open the frontend URL on your phone to confirm. No install, no Python, no
dataset.

---

## If something goes wrong

**Watch the logs:**

```powershell
.\scripts\deploy.ps1 -Logs
```

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'backend'` | Broken package layout, or gunicorn started outside the app root | Both are fixed. Validate before uploading: `.\scripts\deploy.ps1 -CheckPackage`, then redeploy |
| 502 / "Application Error" | App still building, or out of memory | Wait 5 min; check logs; confirm `GUNICORN_WORKERS=1` |
| `health` shows `engine: sqlite` | Settings not applied or app not restarted | Re-run `-Settings`, then `az webapp restart --name dhanraksha-api --resource-group DhanRaksha-RG` |
| `model.loaded: false` | `ml/artifacts/` missing from the package | Confirm the `.pkl` files are committed, redeploy |
| Cosmos 401 | `cosmos-key` secret missing or wrong | Recreate the Key Vault secret (above) |
| First request very slow | Cold start on a free/shared plan | Expected. The app sleeps when idle and reloads the model on wake |
| Frontend loads, API calls fail | Rare — check the browser console | The API is same-origin, so this usually means the app crashed; check logs |

**Restart the app:**

```powershell
az webapp restart --name dhanraksha-api --resource-group DhanRaksha-RG
```

---

## About `ModuleNotFoundError: No module named 'backend'`

This appeared on the first deployment and has two independent causes, both now
fixed.

**1. The package extracted without a `backend` directory.** Windows PowerShell
5.1's `Compress-Archive` writes entry names using the Windows separator, so
`backend\app.py` is stored literally. Linux extracts that as a single *file*
named `backend\app.py` at the top level — no `backend` directory ever exists,
so Python cannot import it. `startup.sh` still ran, because its name contains
no separator, which is what made the symptom confusing.

`scripts/deploy.ps1` no longer uses `Compress-Archive`. It writes entries
itself with forward slashes, and `Test-PackageLayout` rejects any package
containing a backslash or missing a required file before anything is uploaded.

**2. gunicorn started outside the application root.** gunicorn puts its own
working directory on `sys.path`, so `backend.app:app` only resolves if it
starts in the right place. `startup.sh` now derives `APP_ROOT` from its own
location, changes into it, exports `PYTHONPATH`, and passes `--chdir`. It also
checks that `backend/app.py` exists and prints a directory listing if not,
instead of leaving you with a bare import error.

Validate a package without uploading:

```powershell
.\scripts\deploy.ps1 -CheckPackage
```

---

## Redeploying after a change

```powershell
.\scripts\deploy.ps1 -Deploy
```

Settings persist, so `-Settings` is only needed if configuration changes.

**After retraining the model**, the new `.pkl` files are picked up by the next
deploy automatically, because `ml/artifacts/` is part of the package.

---

## Cost

This milestone adds **no new resource and no new cost**. Everything runs on the
Milestone 2 resources, all of which sit inside free tiers.

Check your plan's tier — if it is Free (F1) you are paying nothing for compute:

```powershell
az appservice plan show --name DhanRaksha-Plan --resource-group DhanRaksha-RG --query sku.name -o tsv
```

If it returns `B1`, that is about $13/month. To drop to free:

```powershell
az appservice plan update --name DhanRaksha-Plan --resource-group DhanRaksha-RG --sku F1
```

F1 gives 1 GB RAM and 60 CPU-minutes/day, and the app is configured for one
worker to fit. The trade-off is cold starts after idle periods.

See [azure-cost-control.md](azure-cost-control.md) for the full picture.

---

## Stopping and deleting

**Pause** (keeps everything, frees the compute):

```powershell
az webapp stop --name dhanraksha-api --resource-group DhanRaksha-RG
az webapp start --name dhanraksha-api --resource-group DhanRaksha-RG
```

**Delete everything** — irreversible, removes all stored transactions and cases:

```powershell
az group delete --name DhanRaksha-RG --yes
```

Key Vault soft-deletes for 90 days and keeps its name reserved; purge it
separately with `az keyvault purge --name dhanraksha-kv` if you need to reuse
the name.
