"""
Milestone 3 deployment guarantees.

These assert the properties that make the app usable from any device once
deployed: the frontend is served by the same app as the API, nothing points at
localhost in production, and no part of the running application depends on the
144 MB dataset.
"""

from __future__ import annotations

import json
import os
import re

from backend.config import BASE_DIR
from tests.conftest import requires_model

FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


# ── frontend is served by the API app ────────────────────────────────────
def test_frontend_is_served_from_the_same_origin_as_the_api(client):
    """One app serves both, so there is no CORS problem and no second deploy."""
    page = client.get("/")
    assert page.status_code == 200
    assert b"DhanRaksha" in page.data

    for asset in ("/css/dhanraksha.css", "/js/api.js", "/js/app.js", "/js/charts.js"):
        assert client.get(asset).status_code == 200, asset

    assert client.get("/api/v1/health").status_code in (200, 503)


# ── no localhost in production ───────────────────────────────────────────
def test_api_base_is_derived_from_the_page_origin():
    """
    The API base must come from window.location.origin.

    Hardcoding a hostname would break the moment the app is deployed, which is
    exactly the failure this milestone exists to prevent.
    """
    source = open(os.path.join(FRONTEND_DIR, "js", "api.js"), encoding="utf-8").read()
    assert "window.location.origin" in source


def test_localhost_only_appears_behind_the_file_protocol_check():
    """
    localhost may appear only inside the `file:` branch, which cannot run on
    an https:// page. Anywhere else it would be a production bug.
    """
    source = open(os.path.join(FRONTEND_DIR, "js", "api.js"), encoding="utf-8").read()
    api_base_block = source[source.index("const API_BASE"): source.index("class ApiError")]

    for line_number, line in enumerate(api_base_block.splitlines()):
        if "localhost" in line and not line.strip().startswith("*"):
            preceding = "\n".join(api_base_block.splitlines()[:line_number])
            assert 'protocol === "file:"' in preceding, (
                "localhost outside the file:// guard would break production"
            )


def test_no_hardcoded_azure_or_http_endpoints_in_the_frontend():
    """No baked-in hostname anywhere in the shipped frontend."""
    for folder, _, files in os.walk(FRONTEND_DIR):
        for filename in files:
            if not filename.endswith((".js", ".html")):
                continue
            path = os.path.join(folder, filename)
            source = open(path, encoding="utf-8").read()
            assert "azurewebsites.net" not in source, f"hardcoded Azure host in {filename}"
            # Only third-party CDN assets (fonts, Chart.js) may use an
            # absolute URL. Anything else would be an application endpoint
            # baked in at build time, which is what breaks on deployment.
            allowed_hosts = (
                "cdn.jsdelivr.net",
                "fonts.googleapis.com",
                "fonts.gstatic.com",
                "localhost:5000",
            )
            for url in re.findall(r'"https?://[^"]+"', source):
                assert any(host in url for host in allowed_hosts), (
                    f"unexpected absolute URL in {filename}: {url}"
                )


# ── the deployment does not need creditcard.csv ──────────────────────────
def test_sample_transactions_bundle_ships_with_the_project():
    """
    The bundle is what lets the demo work without the 144 MB dataset.
    """
    path = os.path.join(BASE_DIR, "ml", "artifacts", "sample_transactions.json")
    assert os.path.exists(path), "sample_transactions.json is missing"

    payload = json.load(open(path, encoding="utf-8"))
    samples = payload["samples"]
    assert len(samples) >= 4
    assert os.path.getsize(path) < 100_000, "bundle should stay small"

    labels = {sample["label"] for sample in samples}
    assert "known_fraud" in labels and "known_legitimate" in labels

    for sample in samples:
        assert "amount" in sample and "hour" in sample
        assert all(f"v{i}" in sample for i in range(1, 29))


@requires_model
def test_sample_endpoint_works_without_the_dataset(client, app):
    """With no creditcard.csv present, samples still come back."""
    app.extensions["dhanraksha"].config.dataset_path = "/nonexistent/creditcard.csv"

    response = client.get("/api/v1/sample-transactions")
    assert response.status_code == 200

    body = response.get_json()
    assert body["origin"] == "bundled"
    assert len(body["samples"]) >= 4


@requires_model
def test_a_bundled_sample_can_be_scored_end_to_end(client, app):
    """
    The full journey a visitor takes: load a sample, submit it, get a scored
    decision back, and find it persisted.
    """
    app.extensions["dhanraksha"].config.dataset_path = "/nonexistent/creditcard.csv"

    samples = client.get("/api/v1/sample-transactions").get_json()["samples"]
    fraud_sample = next(s for s in samples if s["label"] == "known_fraud")

    payload = {key: value for key, value in fraud_sample.items()
               if key not in ("label", "model_probability")}

    created = client.post("/api/v1/predict", json=payload)
    assert created.status_code == 201

    result = created.get_json()
    assert result["prediction"] in ("fraud", "legitimate")
    assert 0.0 <= result["fraud_probability"] <= 1.0

    stored = client.get(f"/api/v1/transactions/{result['transaction_id']}")
    assert stored.status_code == 200
    assert stored.get_json()["transaction"]["fraud_probability"] == result["fraud_probability"]


@requires_model
def test_prediction_never_touches_the_dataset(client, app, sample_payload):
    """
    Scoring depends on the model artifacts only. Pointing the dataset path at
    nothing must not affect a prediction.
    """
    app.extensions["dhanraksha"].config.dataset_path = "/nonexistent/creditcard.csv"
    assert client.post("/api/v1/predict", json=sample_payload).status_code == 201


def test_dashboard_endpoints_work_without_the_dataset(client, app):
    app.extensions["dhanraksha"].config.dataset_path = "/nonexistent/creditcard.csv"
    for endpoint in ("/api/v1/analytics", "/api/v1/cases", "/api/v1/model-info"):
        assert client.get(endpoint).status_code == 200, endpoint


# ── deployment assets are present and coherent ───────────────────────────
def test_deployment_requirements_include_the_azure_sdks():
    """
    App Service installs from requirements.txt, and the deployed app runs on
    Cosmos, so the Azure-flavoured list must carry those SDKs.
    """
    source = open(os.path.join(BASE_DIR, "requirements-deploy.txt"), encoding="utf-8").read()
    for package in ("Flask", "scikit-learn", "azure-cosmos", "azure-identity", "gunicorn"):
        assert package in source, f"{package} missing from requirements-deploy.txt"


def test_startup_script_is_present_and_binds_the_azure_port():
    source = open(os.path.join(BASE_DIR, "startup.sh"), encoding="utf-8").read()
    assert "gunicorn" in source
    assert "${PORT:-8000}" in source
    assert "backend.app:app" in source


# ── the fix for "ModuleNotFoundError: No module named 'backend'" ─────────
#
# Two independent causes produced that error on App Service:
#   1. gunicorn started outside the application root, so `backend` was not on
#      sys.path.
#   2. The zip was built with backslash separators in its entry names, so
#      Linux extracted a file literally named "backend\app.py" and no
#      `backend` directory ever existed.
#
# These tests pin both fixes.

STARTUP_SH = os.path.join(BASE_DIR, "startup.sh")
DEPLOY_PS1 = os.path.join(BASE_DIR, "scripts", "deploy.ps1")


def test_startup_script_anchors_itself_to_the_application_root():
    """
    gunicorn puts its own CWD on sys.path, so `backend.app:app` only resolves
    if it starts in the application root. startup.sh must not assume that.
    """
    source = open(STARTUP_SH, encoding="utf-8").read()
    assert "APP_ROOT=" in source
    assert "BASH_SOURCE" in source, "APP_ROOT must derive from the script's own location"
    assert 'cd "$APP_ROOT"' in source
    assert "export PYTHONPATH=" in source
    assert "--chdir" in source


def test_startup_script_fails_loudly_on_a_broken_package():
    """A malformed package should say so, not emit a bare ModuleNotFoundError."""
    source = open(STARTUP_SH, encoding="utf-8").read()
    assert "backend/app.py" in source
    assert "FATAL" in source


def test_deploy_script_does_not_use_compress_archive_to_build_the_package():
    """
    Windows PowerShell 5.1's Compress-Archive writes Windows separators into
    entry names, which is what broke the deployment.
    """
    source = open(DEPLOY_PS1, encoding="utf-8").read()

    build_calls = [
        line for line in source.splitlines()
        if "Compress-Archive" in line and not line.strip().startswith("#")
    ]
    assert not build_calls, f"Compress-Archive is still used: {build_calls}"

    assert "New-DeploymentZip" in source
    assert "Test-PackageLayout" in source
    # Entry names must be normalised to forward slashes. The -replace operator
    # takes a regex, so '\\\\' there is one literal backslash; the .Replace()
    # string method with a single-quoted '\\\\' would be two, and would not match.
    assert "-replace" in source, "entry names must be normalised to '/'"
    assert "'/'" in source
    normalise = [line for line in source.splitlines() if "entryName" in line and "-replace" in line]
    assert normalise, "no entry-name normalisation found in New-DeploymentZip"


def test_a_correctly_built_package_imports_from_a_foreign_working_directory(tmp_path):
    """
    Build the package the way deploy.ps1 does, extract it, and import the app
    with ONLY the extracted directory on sys.path and the process running
    somewhere else entirely. This is the deployed condition.
    """
    import shutil
    import subprocess
    import sys
    import zipfile

    staging = tmp_path / "staging"
    staging.mkdir()

    for folder in ("backend", "ml"):
        shutil.copytree(
            os.path.join(BASE_DIR, folder),
            staging / folder,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    shutil.copytree(os.path.join(BASE_DIR, "frontend"), staging / "frontend")
    shutil.copy(STARTUP_SH, staging / "startup.sh")
    shutil.copy(
        os.path.join(BASE_DIR, "requirements-deploy.txt"), staging / "requirements.txt"
    )

    # Write the archive with forward slashes, as New-DeploymentZip does.
    archive = tmp_path / "package.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for folder, _, files in os.walk(staging):
            for filename in files:
                full = os.path.join(folder, filename)
                entry = os.path.relpath(full, staging).replace(os.sep, "/")
                bundle.write(full, entry)

    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert not [n for n in names if "\\" in n], "entry names must not contain '\\'"
        for required in ("startup.sh", "backend/app.py", "ml/preprocessing.py"):
            assert required in names, f"{required} missing from the package"

        extracted = tmp_path / "wwwroot"
        bundle.extractall(extracted)

    assert (extracted / "backend").is_dir(), "backend must extract as a directory"
    assert (extracted / "backend" / "app.py").is_file()

    # Import exactly as gunicorn does, from an unrelated working directory.
    result = subprocess.run(
        [sys.executable, "-c", "from backend.app import app; print(app.name)"],
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": str(extracted)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"import failed:\n{result.stderr[-1500:]}"
    assert "backend.app" in result.stdout
