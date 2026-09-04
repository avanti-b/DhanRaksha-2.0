"""Operational endpoints: health, model metadata, sample transactions."""

from __future__ import annotations

import json
import os

from flask import Blueprint, current_app, jsonify

from backend.auth.entra import current_identity
from backend.errors import NotFoundError

bp = Blueprint("system", __name__)


@bp.get("/health")
def health():
    container = current_app.extensions["dhanraksha"]
    model_ready = container.model_service.is_ready
    try:
        container.transaction_service.repository.count()
        database_ready = True
    except Exception:  # noqa: BLE001 - reported, not raised
        database_ready = False

    config = container.config
    status = "ok" if model_ready and database_ready else "degraded"

    components = {
        "model": {
            "loaded": model_ready,
            "version": container.model_service.model_version,
            "source": "blob" if config.load_artifacts_from_blob else "image",
            "error": container.model_service.load_error,
        },
        "database": {
            "connected": database_ready,
            "engine": "cosmos" if config.uses_cosmos else "sqlite",
        },
        # Azure components report configured/not-configured rather than being
        # probed, so a health check costs no Azure calls and no RUs.
        "key_vault": {"configured": bool(config.key_vault_url)},
        "blob_storage": {"configured": config.blob_enabled},
        "async_queue": {
            "configured": config.async_processing_enabled,
            "queue": config.async_queue_name if config.async_processing_enabled else None,
        },
        "telemetry": {"configured": bool(config.appinsights_connection_string)},
        "authentication": {
            "enabled": config.auth_enabled,
            "provider": "microsoft-entra-id" if config.auth_enabled else None,
        },
    }

    body = {
        "status": status,
        "environment": config.env,
        "components": components,
        "config": config.as_public_dict(),
        "api_version": "v1",
    }
    return jsonify(body), 200 if status == "ok" else 503


@bp.get("/me")
def me():
    """
    The caller's identity and roles.

    The frontend uses this to decide which navigation items to show. With auth
    disabled it returns a local development identity holding every role.
    """
    return jsonify(current_identity()), 200


@bp.get("/model-info")
def model_info():
    container = current_app.extensions["dhanraksha"]
    info = container.model_service.info()
    info["risk_engine"] = container.risk_engine.describe()
    info["active_fraud_threshold"] = container.config.fraud_threshold
    return jsonify(info), 200


@bp.get("/sample-transactions")
def sample_transactions():
    """
    Real, labelled transactions used to populate the prediction form.

    Served from ml/artifacts/sample_transactions.json, a 6 KB bundle of eight
    rows copied verbatim from the Kaggle dataset with their true labels. This
    is why the deployed application does not need the 144 MB creditcard.csv:
    the demo works from the bundle, and scoring only ever needs the model.

    If the full dataset happens to be present locally it is used instead, which
    gives a wider variety of rows while developing.
    """
    container = current_app.extensions["dhanraksha"]

    dataset_path = container.config.dataset_path
    if os.path.exists(dataset_path):
        return jsonify(_samples_from_dataset(dataset_path)), 200

    bundle_path = os.path.join(container.config.artifact_dir, "sample_transactions.json")
    if os.path.exists(bundle_path):
        with open(bundle_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["origin"] = "bundled"
        return jsonify(payload), 200

    raise NotFoundError(
        "No sample transactions are available in this deployment. "
        "The prediction form still works: enter values manually."
    )


def _samples_from_dataset(dataset_path: str) -> dict:
    """Read labelled examples straight from the full dataset when present."""
    import pandas as pd

    frame = pd.read_csv(dataset_path, nrows=60000)
    frauds = frame[frame["Class"] == 1].head(4)
    legitimate = frame[frame["Class"] == 0].head(4)

    def to_sample(row, label: str) -> dict:
        sample = {
            "label": label,
            "amount": round(float(row["Amount"]), 2),
            "hour": int((float(row["Time"]) // 3600) % 24),
        }
        for index in range(1, 29):
            sample[f"v{index}"] = round(float(row[f"V{index}"]), 6)
        return sample

    samples = [to_sample(row, "known_fraud") for _, row in frauds.iterrows()]
    samples += [to_sample(row, "known_legitimate") for _, row in legitimate.iterrows()]
    return {
        "source": "creditcard.csv (ground truth)",
        "origin": "dataset",
        "count": len(samples),
        "samples": samples,
    }
