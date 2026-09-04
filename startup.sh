#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════
# Azure App Service (Linux, Python) startup command.
#
# Set this as the Startup Command in the portal:
#   App Service -> Configuration -> General settings -> Startup Command
#   startup.sh
#
# ONE worker by default. scikit-learn + pandas + the Random Forest is roughly
# 300-400 MB resident, and the Free (F1) and Basic (B1) tiers give 1-1.75 GB.
# A second worker doubles that for no benefit on a demo workload and is the
# most common cause of restarts on the free tier.
#
# Override with GUNICORN_WORKERS in App Service application settings if you
# move to a larger plan.
#
# The timeout is generous because the first request after an idle period pays
# for loading the model.
# ══════════════════════════════════════════════════════════════════════════
set -e

# ── Make the application importable, whatever the working directory is ────
# gunicorn puts its own CWD on sys.path, so `backend.app:app` resolves only if
# gunicorn happens to start in the application root. On App Service that is not
# guaranteed, and when it is not, the worker dies with:
#     ModuleNotFoundError: No module named 'backend'
#
# Anchoring to this script's own location removes the assumption entirely:
# startup.sh sits in the application root, so APP_ROOT is the application root
# regardless of where the runtime invoked it from.
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_ROOT"
export PYTHONPATH="$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting DhanRaksha 2.0 on App Service..."
echo "App root:        $APP_ROOT"
echo "Storage backend: ${STORAGE_BACKEND:-sqlite}"
echo "Auth enabled:    ${AUTH_ENABLED:-false}"

# ── Fail loudly and usefully if the package did not arrive intact ─────────
# A deployment package can extract without a real `backend/` directory (for
# example when the zip was built on Windows with backslash separators in its
# entry names). Detect that here rather than letting gunicorn report a bare
# ModuleNotFoundError with no clue as to why.
if [ ! -f "$APP_ROOT/backend/app.py" ]; then
    echo "FATAL: $APP_ROOT/backend/app.py is missing." >&2
    echo "The deployment package did not extract correctly. Contents:" >&2
    ls -la "$APP_ROOT" >&2
    echo "Redeploy with: .\\scripts\\deploy.ps1 -Deploy" >&2
    exit 1
fi

exec gunicorn \
  --bind=0.0.0.0:${PORT:-8000} \
  --workers=${GUNICORN_WORKERS:-1} \
  --threads=2 \
  --timeout=180 \
  --access-logfile '-' \
  --error-logfile '-' \
  --chdir "$APP_ROOT" \
  backend.app:app
