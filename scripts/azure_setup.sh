#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════
# DhanRaksha 2.0 — Azure resource creation, one step at a time.
#
# This is the scripted equivalent of the portal walkthrough in
# docs/azure-deployment.md. It is written to be run STEP BY STEP, not
# end-to-end, so you can see and understand each resource before it exists.
#
#   ./scripts/azure_setup.sh step1     # resource group        $0
#   ./scripts/azure_setup.sh step2     # app service (F1 free) $0
#   ./scripts/azure_setup.sh step3     # cosmos db (free tier) $0
#   ./scripts/azure_setup.sh step4     # storage account       ~$0.05/mo
#   ./scripts/azure_setup.sh step5     # function app          $0
#   ./scripts/azure_setup.sh step6     # key vault             ~$0.00
#   ./scripts/azure_setup.sh step7     # application insights  $0
#   ./scripts/azure_setup.sh costs     # show current spend
#   ./scripts/azure_setup.sh teardown  # DELETE EVERYTHING
#
# Prerequisites:
#   az login
#   az account set --subscription "<YOUR SUBSCRIPTION NAME OR ID>"
# ══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── EDIT THESE TWO IF YOU WANT ──────────────────────────────────────────
RG="rg-dhanraksha"
LOCATION="centralindia"     # closest to you; westeurope/eastus also fine
# ────────────────────────────────────────────────────────────────────────

# Globally unique names. The random suffix avoids collisions with other
# Azure customers, since app and storage names share a global namespace.
SUFFIX="${DHANRAKSHA_SUFFIX:-$(echo $RANDOM | md5sum | head -c 6)}"
APP_PLAN="plan-dhanraksha"
APP_NAME="dhanraksha-${SUFFIX}"
COSMOS_NAME="cosmos-dhanraksha-${SUFFIX}"
STORAGE_NAME="stdhanraksha${SUFFIX}"
FUNC_NAME="func-dhanraksha-${SUFFIX}"
VAULT_NAME="kv-dhanraksha-${SUFFIX}"
INSIGHTS_NAME="appi-dhanraksha"

echo "Resource group: $RG   Region: $LOCATION   Suffix: $SUFFIX"
echo "Save this suffix: export DHANRAKSHA_SUFFIX=$SUFFIX"
echo

case "${1:-help}" in

# ══════════════════════════════════════════════════════════════════════
step1)
  echo ">>> STEP 1: Resource group (free — a group costs nothing)"
  az group create --name "$RG" --location "$LOCATION" --output table
  echo
  echo "See it: Portal -> Resource groups -> $RG"
  ;;

# ══════════════════════════════════════════════════════════════════════
step2)
  echo ">>> STEP 2: App Service on the F1 FREE tier"
  echo "    F1: 1 GB RAM, 60 CPU-minutes/day, no custom domain, no Always On."
  echo "    Cost: \$0. If the app runs out of memory, see the B1 note in"
  echo "    docs/azure-cost-control.md (~\$13/month) before switching."

  az appservice plan create \
    --name "$APP_PLAN" --resource-group "$RG" \
    --sku F1 --is-linux --location "$LOCATION" --output table

  az webapp create \
    --name "$APP_NAME" --resource-group "$RG" --plan "$APP_PLAN" \
    --runtime "PYTHON:3.11" --output table

  az webapp config set \
    --name "$APP_NAME" --resource-group "$RG" \
    --startup-file "startup.sh" --output none

  # Build dependencies on the server from requirements.txt during deployment.
  az webapp config appsettings set \
    --name "$APP_NAME" --resource-group "$RG" \
    --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true \
    --output none

  echo
  echo "App URL: https://${APP_NAME}.azurewebsites.net"
  echo "See it:  Portal -> App Services -> $APP_NAME"
  ;;

# ══════════════════════════════════════════════════════════════════════
step3)
  echo ">>> STEP 3: Cosmos DB with FREE TIER enabled"
  echo "    Free tier: first 1000 RU/s + 25 GB free for the account lifetime."
  echo "    Only ONE free-tier Cosmos account is allowed per subscription."
  echo "    We provision 400 RU/s shared across both containers, so this"
  echo "    stays entirely inside the free allowance. Cost: \$0."

  az cosmosdb create \
    --name "$COSMOS_NAME" --resource-group "$RG" \
    --locations regionName="$LOCATION" failoverPriority=0 \
    --enable-free-tier true \
    --default-consistency-level Session \
    --output table

  # The application creates the database and containers itself on first start,
  # but creating them here means the free-tier throughput is set explicitly.
  az cosmosdb sql database create \
    --account-name "$COSMOS_NAME" --resource-group "$RG" \
    --name dhanraksha --throughput 400 --output none

  az cosmosdb sql container create \
    --account-name "$COSMOS_NAME" --resource-group "$RG" \
    --database-name dhanraksha --name transactions \
    --partition-key-path "/risk_level" --output none

  az cosmosdb sql container create \
    --account-name "$COSMOS_NAME" --resource-group "$RG" \
    --database-name dhanraksha --name cases \
    --partition-key-path "/status" --output none

  echo
  echo "COSMOS_ENDPOINT:"
  az cosmosdb show --name "$COSMOS_NAME" --resource-group "$RG" \
    --query documentEndpoint -o tsv
  echo
  echo "Get the key with:"
  echo "  az cosmosdb keys list --name $COSMOS_NAME --resource-group $RG --query primaryMasterKey -o tsv"
  echo "See it: Portal -> Azure Cosmos DB -> $COSMOS_NAME -> Data Explorer"
  ;;

# ══════════════════════════════════════════════════════════════════════
step4)
  echo ">>> STEP 4: Storage account (blobs + the async queue)"
  echo "    Standard LRS, Hot tier. Holds ~4.3 MB of model artifacts and a few"
  echo "    KB of reports. Cost: roughly \$0.05/month at this size."

  az storage account create \
    --name "$STORAGE_NAME" --resource-group "$RG" \
    --location "$LOCATION" --sku Standard_LRS --kind StorageV2 \
    --min-tls-version TLS1_2 --allow-blob-public-access false \
    --output table

  CONN=$(az storage account show-connection-string \
    --name "$STORAGE_NAME" --resource-group "$RG" --query connectionString -o tsv)

  az storage container create --name model-artifacts --connection-string "$CONN" --output none
  az storage container create --name reports        --connection-string "$CONN" --output none
  az storage queue create     --name transaction-queue --connection-string "$CONN" --output none

  echo
  echo "Containers 'model-artifacts' and 'reports' and queue 'transaction-queue' created."
  echo "Get the connection string (do NOT paste it into chat):"
  echo "  az storage account show-connection-string --name $STORAGE_NAME --resource-group $RG --query connectionString -o tsv"
  echo "See it: Portal -> Storage accounts -> $STORAGE_NAME -> Containers"
  ;;

# ══════════════════════════════════════════════════════════════════════
step5)
  echo ">>> STEP 5: Function App on the CONSUMPTION plan"
  echo "    Free grant: 1,000,000 executions + 400,000 GB-s per month."
  echo "    This app runs one execution per prediction plus one per day."
  echo "    Cost: \$0 within the grant."

  az functionapp create \
    --name "$FUNC_NAME" --resource-group "$RG" \
    --storage-account "$STORAGE_NAME" \
    --consumption-plan-location "$LOCATION" \
    --runtime python --runtime-version 3.11 \
    --functions-version 4 --os-type Linux \
    --output table

  echo
  echo "Deploy the code with:"
  echo "  cd functions && func azure functionapp publish $FUNC_NAME"
  echo "See it: Portal -> Function App -> $FUNC_NAME -> Functions"
  ;;

# ══════════════════════════════════════════════════════════════════════
step6)
  echo ">>> STEP 6: Key Vault + managed identity"
  echo "    Standard tier: \$0.03 per 10,000 operations. This app reads a"
  echo "    handful of secrets at startup and caches them. Cost: ~\$0.00."

  az keyvault create \
    --name "$VAULT_NAME" --resource-group "$RG" --location "$LOCATION" \
    --enable-rbac-authorization true --output table

  echo "Enabling managed identity on the App Service..."
  PRINCIPAL=$(az webapp identity assign \
    --name "$APP_NAME" --resource-group "$RG" --query principalId -o tsv)

  VAULT_ID=$(az keyvault show --name "$VAULT_NAME" --resource-group "$RG" --query id -o tsv)

  echo "Granting the app read access to secrets..."
  az role assignment create \
    --role "Key Vault Secrets User" \
    --assignee "$PRINCIPAL" --scope "$VAULT_ID" --output none

  echo
  echo "Vault URL: https://${VAULT_NAME}.vault.azure.net/"
  echo
  echo "Now store your secrets (run these yourself, with your real values):"
  echo "  az keyvault secret set --vault-name $VAULT_NAME --name cosmos-key --value '<COSMOS PRIMARY KEY>'"
  echo "  az keyvault secret set --vault-name $VAULT_NAME --name storage-connection-string --value '<CONNECTION STRING>'"
  echo "  az keyvault secret set --vault-name $VAULT_NAME --name secret-key --value \"\$(python -c 'import secrets;print(secrets.token_hex(32))')\""
  echo "See it: Portal -> Key vaults -> $VAULT_NAME -> Objects -> Secrets"
  ;;

# ══════════════════════════════════════════════════════════════════════
step7)
  echo ">>> STEP 7: Application Insights"
  echo "    First 5 GB of ingestion per month is free. This app sends"
  echo "    kilobytes per request. Cost: \$0."

  az monitor app-insights component create \
    --app "$INSIGHTS_NAME" --location "$LOCATION" \
    --resource-group "$RG" --application-type web \
    --retention-time 30 --output table

  echo
  echo "Connection string:"
  az monitor app-insights component show \
    --app "$INSIGHTS_NAME" --resource-group "$RG" \
    --query connectionString -o tsv
  echo
  echo "See it: Portal -> Application Insights -> $INSIGHTS_NAME -> Live metrics"
  ;;

# ══════════════════════════════════════════════════════════════════════
deploy)
  echo ">>> Deploying the Flask app to App Service"
  echo "Packaging (excluding dataset, venv, caches, .env)..."
  cd "$(dirname "$0")/.."
  rm -f /tmp/dhanraksha-deploy.zip
  zip -r /tmp/dhanraksha-deploy.zip . \
    -x "*.git*" "venv/*" "*__pycache__*" "*.pyc" ".pytest_cache/*" \
       "data/creditcard.csv" "data/*.db*" ".env" "functions/*" "docs/*" > /dev/null
  az webapp deploy --resource-group "$RG" --name "$APP_NAME" \
    --src-path /tmp/dhanraksha-deploy.zip --type zip
  echo "Deployed: https://${APP_NAME}.azurewebsites.net"
  ;;

# ══════════════════════════════════════════════════════════════════════
costs)
  echo ">>> Current month spend for $RG"
  az consumption usage list --output table 2>/dev/null || \
    echo "Use the portal instead: Cost Management + Billing -> Cost analysis"
  echo
  echo "Set a budget alert: Portal -> Cost Management -> Budgets -> Add"
  echo "Recommended: \$20 budget with alerts at 50%, 80% and 100%."
  ;;

# ══════════════════════════════════════════════════════════════════════
teardown)
  echo ">>> DELETING the entire resource group '$RG'"
  echo "    This removes every resource and all stored data. Irreversible."
  read -p "    Type the resource group name to confirm: " CONFIRM
  if [ "$CONFIRM" = "$RG" ]; then
    az group delete --name "$RG" --yes --no-wait
    echo "Deletion started. Billing stops as resources are removed."
  else
    echo "Cancelled."
  fi
  ;;

*)
  sed -n '2,28p' "$0"
  ;;
esac
