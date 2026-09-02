"""Operational endpoints: health, model metadata, sample transactions."""

from __future__ import annotations

import os

import pandas as pd
from flask import Blueprint, current_app, jsonify

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

    status = "ok" if model_ready and database_ready else "degraded"
    body = {
        "status": status,
        "components": {
            "model": {
                "loaded": model_ready,
                "version": container.model_service.model_version,
                "error": container.model_service.load_error,
            },
            "database": {"connected": database_ready, "engine": "sqlite"},
        },
        "config": container.config.as_public_dict(),
        "api_version": "v1",
    }
    return jsonify(body), 200 if status == "ok" else 503


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
    Real rows from the source dataset, for populating the prediction form.

    These are genuine records from creditcard.csv, clearly labelled with their
    ground-truth class. They are a convenience for demonstrating the model, not
    synthetic data, and they are never written to the database unless the user
    actually submits them for scoring.
    """
    container = current_app.extensions["dhanraksha"]
    dataset_path = container.config.dataset_path
    if not os.path.exists(dataset_path):
        raise NotFoundError(
            "creditcard.csv is not available in this deployment. "
            "Place it in data/ to enable sample loading."
        )

    frame = pd.read_csv(dataset_path, nrows=60000)
    frauds = frame[frame["Class"] == 1].head(4)
    legit = frame[frame["Class"] == 0].head(4)

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
    samples += [to_sample(row, "known_legitimate") for _, row in legit.iterrows()]
    return jsonify({"samples": samples, "source": "creditcard.csv (ground truth)"}), 200
