# =========================================================================
#  DhanRaksha 2.0 - Milestone 3 deployment (Windows / PowerShell)
#
#  Deploys the Flask app AND the frontend together to the App Service that
#  already exists from Milestone 2. Creates NO new Azure resource.
#
#  HOW TO RUN (PowerShell, not CMD):
#
#      cd C:\path\to\DhanRaksha
#      az login
#      .\scripts\deploy.ps1 -Settings      # one time: configure app settings
#      .\scripts\deploy.ps1 -Deploy        # push the code
#      .\scripts\deploy.ps1 -Verify        # check it actually works
#
#  If PowerShell blocks the script, allow it for this session only:
#      Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# =========================================================================

param(
    [switch]$Settings,     # configure App Service application settings
    [switch]$Deploy,       # package and upload the application
    [switch]$Verify,       # smoke-test the deployed app
    [switch]$Logs,         # tail live logs
    [switch]$CheckPackage, # build the package and validate it WITHOUT uploading
    [switch]$All,          # Settings + Deploy + Verify

    # --- your existing Milestone 2 resources -----------------------------
    [string]$ResourceGroup = "DhanRaksha-RG",
    [string]$AppName       = "dhanraksha-api",
    [string]$CosmosAccount = "dhanraksha-cosmos",
    [string]$KeyVaultName  = "dhanraksha-kv"
)

$ErrorActionPreference = "Stop"
$AppUrl = "https://$AppName.azurewebsites.net"

function Write-Step($text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Assert-AzCli {
    try { az account show --output none 2>$null }
    catch { throw "Not signed in. Run: az login" }
    $sub = az account show --query name -o tsv
    Write-Host "Subscription: $sub" -ForegroundColor DarkGray
}

# =========================================================================
#  SETTINGS - point the deployed app at your existing Azure resources
# =========================================================================
function Set-AppSettings {
    Write-Step "Configuring App Service settings"
    Assert-AzCli

    # The Cosmos endpoint is read from the account itself, so there is nothing
    # to copy by hand and no key ever appears in this script. The Cosmos KEY is
    # NOT set here: it lives in Key Vault, which the app reads using the
    # managed identity you set up in Milestone 2.
    Write-Host "Reading the Cosmos endpoint..." -ForegroundColor DarkGray
    $cosmosEndpoint = az cosmosdb show `
        --name $CosmosAccount --resource-group $ResourceGroup `
        --query documentEndpoint -o tsv

    $vaultUrl = "https://$KeyVaultName.vault.azure.net/"

    Write-Host "Applying settings..." -ForegroundColor DarkGray
    az webapp config appsettings set `
        --name $AppName --resource-group $ResourceGroup `
        --settings `
            APP_ENV=production `
            STORAGE_BACKEND=cosmos `
            COSMOS_ENDPOINT=$cosmosEndpoint `
            COSMOS_DATABASE=dhanraksha `
            COSMOS_TRANSACTIONS_CONTAINER=transactions `
            COSMOS_CASES_CONTAINER=cases `
            KEY_VAULT_URL=$vaultUrl `
            BLOB_ARTIFACTS_CONTAINER=dhanraksha-data `
            BLOB_REPORTS_CONTAINER=dhanraksha-data `
            ASYNC_QUEUE_NAME=fraud-alerts `
            AUTH_ENABLED=false `
            GUNICORN_WORKERS=1 `
            SCM_DO_BUILD_DURING_DEPLOYMENT=true `
            WEBSITES_CONTAINER_START_TIME_LIMIT=600 `
            CORS_ORIGINS=$AppUrl `
        --output none

    # Serves the frontend and the API from one process, so there is no second
    # service to deploy and no cross-origin configuration to get wrong.
    Write-Host "Setting the startup command..." -ForegroundColor DarkGray
    az webapp config set `
        --name $AppName --resource-group $ResourceGroup `
        --startup-file "startup.sh" `
        --output none

    # Lets Azure restart the app automatically if it stops responding.
    az webapp update `
        --name $AppName --resource-group $ResourceGroup `
        --set siteConfig.healthCheckPath="/api/v1/health" `
        --output none 2>$null

    Write-Host "Settings applied." -ForegroundColor Green
    Write-Host ""
    Write-Host "NOTE: the Cosmos key is not set here on purpose." -ForegroundColor Yellow
    Write-Host "The app reads it from Key Vault. Confirm the secret exists:" -ForegroundColor Yellow
    Write-Host "  az keyvault secret show --vault-name $KeyVaultName --name cosmos-key --query name" -ForegroundColor Yellow
    Write-Host "If it does not, create it (run this yourself, with your real key):" -ForegroundColor Yellow
    Write-Host "  az keyvault secret set --vault-name $KeyVaultName --name cosmos-key --value `"<COSMOS PRIMARY KEY>`"" -ForegroundColor Yellow
}

# =========================================================================
#  ZIP BUILDER
#
#  Compress-Archive is NOT used here, deliberately.
#
#  Windows PowerShell 5.1's Compress-Archive writes entry names using the
#  Windows separator, so "backend\app.py" is stored literally. Linux extracts
#  that as a single FILE named "backend\app.py" at the top level instead of a
#  "backend" directory, and Python then reports:
#
#      ModuleNotFoundError: No module named 'backend'
#
#  startup.sh still runs, because its name contains no separator - which is
#  exactly the confusing symptom this produces.
#
#  Writing entries by hand with forward slashes makes the package correct on
#  every PowerShell version.
# =========================================================================
function New-DeploymentZip {
    param([string]$SourceDir, [string]$ZipPath)

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

    $archive = [System.IO.Compression.ZipFile]::Open(
        $ZipPath, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        $root  = (Resolve-Path $SourceDir).Path.TrimEnd([System.IO.Path]::DirectorySeparatorChar)
        $files = Get-ChildItem $SourceDir -Recurse -File

        foreach ($file in $files) {
            # Relative path with forward slashes, which is what the ZIP
            # specification requires and what Linux expects.
            # -replace takes a regex, where \\ means one literal backslash.
            # (The .Replace('\\','/') string method would NOT work here: a
            #  single-quoted '\\' in PowerShell is TWO literal backslashes.)
            $entryName = $file.FullName.Substring($root.Length + 1) -replace '\\', '/'

            $entry  = $archive.CreateEntry($entryName,
                        [System.IO.Compression.CompressionLevel]::Optimal)
            $source = [System.IO.File]::OpenRead($file.FullName)
            try {
                $target = $entry.Open()
                try { $source.CopyTo($target) } finally { $target.Dispose() }
            } finally { $source.Dispose() }
        }
        Write-Host "Packaged $($files.Count) files" -ForegroundColor DarkGray
    } finally {
        $archive.Dispose()
    }
}

# =========================================================================
#  PACKAGE CHECK - verify the zip before uploading it
#
#  Catches a malformed package locally, in a second, instead of after a
#  ten-minute build followed by a worker that will not boot.
# =========================================================================
function Test-PackageLayout {
    param([string]$ZipPath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $names = $archive.Entries | ForEach-Object { $_.FullName }

        $backslashed = $names | Where-Object { $_ -like "*\*" }
        if ($backslashed) {
            throw ("Package entries contain backslashes, which Linux will not " +
                   "treat as directories. First offender: " + $backslashed[0])
        }

        # Files gunicorn must be able to import once the package is extracted.
        $required = @(
            "startup.sh",
            "backend/__init__.py",
            "backend/app.py",
            "ml/__init__.py",
            "ml/preprocessing.py",
            "ml/artifacts/fraud_model.pkl",
            "ml/artifacts/feature_pipeline.pkl",
            "frontend/index.html",
            "requirements.txt"
        )
        $missing = $required | Where-Object { $names -notcontains $_ }
        if ($missing) {
            throw "Package is missing required files: $($missing -join ', ')"
        }

        # Nothing that should never leave your machine.
        $forbidden = $names | Where-Object {
            $_ -eq ".env" -or $_ -like "*creditcard.csv" -or $_ -like "*.db"
        }
        if ($forbidden) {
            throw "Package contains files that must not ship: $($forbidden -join ', ')"
        }

        Write-Host "Package layout verified ($($names.Count) entries)" -ForegroundColor Green
    } finally {
        $archive.Dispose()
    }
}

# =========================================================================
#  DEPLOY - stage a clean copy and zip-deploy it
# =========================================================================
function New-StagingFolder {
    $root    = Split-Path -Parent $PSScriptRoot
    $staging = Join-Path $env:TEMP "dhanraksha-deploy"

    if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
    New-Item -ItemType Directory -Path $staging | Out-Null

    # Only what the running application needs. The dataset, the test suite,
    # the training pipeline's extra deps, local databases and .env are all
    # left out - smaller upload, faster build, no secrets in the package.
    Write-Host "Staging application files..." -ForegroundColor DarkGray
    foreach ($item in @("backend", "frontend", "ml")) {
        Copy-Item (Join-Path $root $item) $staging -Recurse -Force
    }
    Copy-Item (Join-Path $root "startup.sh") $staging -Force

    # Azure's build step reads a file named exactly "requirements.txt", so the
    # Azure-flavoured list is copied over it inside the staging folder only.
    # The real requirements.txt in your repository is untouched.
    Copy-Item (Join-Path $root "requirements-deploy.txt") `
              (Join-Path $staging "requirements.txt") -Force

    # Strip anything that should never ship.
    Get-ChildItem $staging -Recurse -Force -Include `
        "__pycache__", "*.pyc", ".env", "*.db", "*.db-wal", "*.db-shm", "creditcard.csv" |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    $csv = Join-Path $staging "data\creditcard.csv"
    if (Test-Path $csv) { Remove-Item $csv -Force }

    $sizeMb = [math]::Round(((Get-ChildItem $staging -Recurse -File |
                Measure-Object Length -Sum).Sum / 1MB), 2)
    Write-Host "Staged $sizeMb MB" -ForegroundColor DarkGray

    return $staging
}

# Build the package and validate it, without uploading. Useful for confirming
# a packaging fix in seconds rather than after a ten-minute deploy.
function Build-PackageOnly {
    Write-Step "Building and validating the deployment package"

    $staging = New-StagingFolder
    $zipPath = Join-Path $env:TEMP "dhanraksha-deploy.zip"

    New-DeploymentZip -SourceDir $staging -ZipPath $zipPath
    Test-PackageLayout -ZipPath $zipPath

    Write-Host ""
    Write-Host "Package is valid: $zipPath" -ForegroundColor Green
    Write-Host "Nothing was uploaded. Run -Deploy when ready." -ForegroundColor DarkGray
    Remove-Item $staging -Recurse -Force
}

function Publish-App {
    Write-Step "Deploying to $AppName"
    Assert-AzCli

    $staging = New-StagingFolder
    $zipPath = Join-Path $env:TEMP "dhanraksha-deploy.zip"

    Write-Host "Creating the deployment package..." -ForegroundColor DarkGray
    New-DeploymentZip -SourceDir $staging -ZipPath $zipPath
    Test-PackageLayout -ZipPath $zipPath

    Write-Host "Uploading (the first deploy takes several minutes - it builds scikit-learn)..." `
        -ForegroundColor DarkGray
    az webapp deploy `
        --resource-group $ResourceGroup --name $AppName `
        --src-path $zipPath --type zip --async false

    Remove-Item $staging -Recurse -Force
    Remove-Item $zipPath -Force

    Write-Host "Deployed." -ForegroundColor Green
    Write-Host "Frontend and API: $AppUrl" -ForegroundColor Green
}

# =========================================================================
#  VERIFY - prove the deployment actually works, not just that it uploaded
# =========================================================================
function Test-Deployment {
    Write-Step "Verifying $AppUrl"

    Write-Host "Waiting for the app to warm up..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 20

    $failed = 0

    # 1. health
    try {
        $health = Invoke-RestMethod "$AppUrl/api/v1/health" -TimeoutSec 120
        Write-Host "[ok]   health: $($health.status)" -ForegroundColor Green
        Write-Host "       database : $($health.components.database.engine)"
        Write-Host "       model    : loaded=$($health.components.model.loaded) version=$($health.components.model.version)"

        if ($health.components.database.engine -ne "cosmos") {
            Write-Host "[warn] not using Cosmos - run .\scripts\deploy.ps1 -Settings" -ForegroundColor Yellow
            $failed++
        }
        if (-not $health.components.model.loaded) {
            Write-Host "[FAIL] model did not load: $($health.components.model.error)" -ForegroundColor Red
            $failed++
        }
    } catch {
        Write-Host "[FAIL] health check: $_" -ForegroundColor Red
        $failed++
    }

    # 2. frontend
    try {
        $page = Invoke-WebRequest $AppUrl -TimeoutSec 60
        if ($page.StatusCode -eq 200 -and $page.Content -match "DhanRaksha") {
            Write-Host "[ok]   frontend loads over HTTPS" -ForegroundColor Green
        } else {
            Write-Host "[FAIL] frontend did not return the expected page" -ForegroundColor Red
            $failed++
        }
    } catch {
        Write-Host "[FAIL] frontend: $_" -ForegroundColor Red
        $failed++
    }

    # 3. end-to-end prediction on a real fraud row
    try {
        $body = @{
            amount = 529.0; hour = 0
            v1 = -3.043541; v2 = -3.157307; v3 = 1.088463;  v4 = 2.288644
            v5 = 1.359805;  v6 = -1.064823; v7 = 0.325574;  v8 = -0.067794
            v9 = -0.270953; v10 = -0.838587; v11 = -0.414575; v12 = -0.503141
            v13 = 0.676502; v14 = -1.692029; v15 = 2.000635; v16 = 0.66678
            v17 = 0.599717; v18 = 1.725321; v19 = 0.283345; v20 = 2.102339
            v21 = 0.661696; v22 = 0.435477; v23 = 1.375966; v24 = -0.293803
            v25 = 0.279798; v26 = -0.145362; v27 = -0.252773; v28 = 0.035764
        } | ConvertTo-Json

        $result = Invoke-RestMethod "$AppUrl/api/v1/predict" -Method Post `
                    -Body $body -ContentType "application/json" -TimeoutSec 120
        Write-Host "[ok]   prediction: $($result.prediction) / $($result.risk_level) / p=$($result.fraud_probability)" -ForegroundColor Green
        Write-Host "       transaction: $($result.transaction_id)"

        # 4. persistence in Cosmos
        Start-Sleep -Seconds 2
        $stored = Invoke-RestMethod "$AppUrl/api/v1/transactions/$($result.transaction_id)" -TimeoutSec 60
        if ($stored.transaction.transaction_id -eq $result.transaction_id) {
            Write-Host "[ok]   persisted and read back from Cosmos DB" -ForegroundColor Green
        } else {
            Write-Host "[FAIL] transaction was not retrievable" -ForegroundColor Red
            $failed++
        }
    } catch {
        Write-Host "[FAIL] prediction round trip: $_" -ForegroundColor Red
        $failed++
    }

    # 5. analytics + cases
    foreach ($endpoint in @("analytics", "cases", "model-info", "sample-transactions")) {
        try {
            Invoke-RestMethod "$AppUrl/api/v1/$endpoint" -TimeoutSec 60 | Out-Null
            Write-Host "[ok]   /$endpoint" -ForegroundColor Green
        } catch {
            Write-Host "[FAIL] /$endpoint : $_" -ForegroundColor Red
            $failed++
        }
    }

    Write-Host ""
    if ($failed -eq 0) {
        Write-Host "All checks passed. Open $AppUrl on any device." -ForegroundColor Green
    } else {
        Write-Host "$failed check(s) failed. Inspect the logs:" -ForegroundColor Red
        Write-Host "  .\scripts\deploy.ps1 -Logs" -ForegroundColor Red
    }
}

function Show-Logs {
    Write-Step "Live log stream (Ctrl+C to stop)"
    az webapp log tail --name $AppName --resource-group $ResourceGroup
}

# =========================================================================
if ($CheckPackage) { Build-PackageOnly; return }
if ($All)      { Set-AppSettings; Publish-App; Test-Deployment; return }
if ($Settings) { Set-AppSettings }
if ($Deploy)   { Publish-App }
if ($Verify)   { Test-Deployment }
if ($Logs)     { Show-Logs }

if (-not ($Settings -or $Deploy -or $Verify -or $Logs -or $All -or $CheckPackage)) {
    Write-Host @"
DhanRaksha 2.0 - Milestone 3 deployment

  .\scripts\deploy.ps1 -Settings   Configure App Service settings (run once)
  .\scripts\deploy.ps1 -Deploy     Package and upload the application
  .\scripts\deploy.ps1 -Verify     Smoke-test the deployed application
  .\scripts\deploy.ps1 -Logs       Tail live logs
  .\scripts\deploy.ps1 -CheckPackage  Build and validate the package, no upload
  .\scripts\deploy.ps1 -All        Settings, then Deploy, then Verify

Target: $AppUrl
Creates no new Azure resource.
"@
}
