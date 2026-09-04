# ══════════════════════════════════════════════════════════════════
# DhanRaksha 2.0 — single application image.
#
# Flask serves both the REST API and the static frontend, so one
# container is the whole stack. That also makes the Milestone 2 move to
# Azure App Service straightforward: the same image, one service.
# ══════════════════════════════════════════════════════════════════
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dependencies first so code changes don't invalidate the layer.
# Local/container runtime only. The Azure extras (requirements-azure.txt) are
# intentionally NOT installed here: this image is for local development and
# runs on SQLite. App Service installs both files during deployment.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY ml/ ./ml/
COPY frontend/ ./frontend/

# Writable location for the SQLite file; mounted as a volume in compose
# so scored transactions survive a container rebuild.
RUN mkdir -p /app/data && \
    adduser --disabled-password --gecos "" dhanraksha && \
    chown -R dhanraksha:dhanraksha /app
USER dhanraksha

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; \
      sys.exit(0 if urllib.request.urlopen('http://localhost:5000/api/v1/health').status==200 else 1)"

# Two workers is plenty for a local demo. Timeout is generous because the
# first request pays for lazy model loading.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "backend.app:app"]
