"""
Model service: owns the loaded artifacts and produces fraud probabilities.

Loading is lazy and failure-tolerant. If the artifacts are missing the app
still starts and /api/v1/health reports the degraded state, instead of the
process dying at import time (which is what the original app.py did in effect,
by printing an error and then returning 503 from every route).
"""

from __future__ import annotations

import json
import logging
import os
import threading

import joblib
import numpy as np

from backend.errors import ModelUnavailableError
from ml.preprocessing import FeaturePipeline, RawTransaction, feature_vector_as_dict

logger = logging.getLogger("dhanraksha.model")


class ModelService:
    def __init__(self, model_path: str, pipeline_path: str, metadata_path: str) -> None:
        self.model_path = model_path
        self.pipeline_path = pipeline_path
        self.metadata_path = metadata_path
        self._lock = threading.Lock()
        self.model = None
        self.pipeline: FeaturePipeline | None = None
        self.metadata: dict = {}
        self.load_error: str | None = None
        self.load()

    # --------------------------------------------------------------- loading
    def load(self) -> bool:
        with self._lock:
            try:
                if not os.path.exists(self.model_path):
                    raise FileNotFoundError("fraud_model.pkl is missing")
                if not os.path.exists(self.pipeline_path):
                    raise FileNotFoundError("feature_pipeline.pkl is missing")

                self.model = joblib.load(self.model_path)
                self.pipeline = FeaturePipeline.load(self.pipeline_path)
                self.metadata = {}
                if os.path.exists(self.metadata_path):
                    with open(self.metadata_path, encoding="utf-8") as handle:
                        self.metadata = json.load(handle)
                self.load_error = None
                logger.info(
                    "Model loaded (version=%s, features=%s)",
                    self.model_version,
                    getattr(self.model, "n_features_in_", "unknown"),
                )
                return True
            except Exception as exc:  # noqa: BLE001 - surfaced through /health
                self.model = None
                self.pipeline = None
                self.load_error = str(exc)
                logger.error("Model artifacts unavailable: %s", exc)
                return False

    @property
    def is_ready(self) -> bool:
        return self.model is not None and self.pipeline is not None

    @property
    def model_version(self) -> str:
        return str(self.metadata.get("model_version", "unknown"))

    @property
    def risk_reference(self) -> dict:
        return self.metadata.get("risk_reference", {}) or {}

    def _require_ready(self) -> None:
        if not self.is_ready:
            raise ModelUnavailableError(
                "The fraud model is not loaded. Train it with "
                "'python -m ml.train' and restart the service."
            )

    # ------------------------------------------------------------ prediction
    def predict_probability(self, raw: RawTransaction) -> tuple[float, dict[str, float]]:
        """Return (fraud_probability, labelled_scaled_feature_vector)."""
        self._require_ready()
        assert self.pipeline is not None  # for type checkers
        frame = self.pipeline.transform_transaction_frame(raw)
        probability = float(self.model.predict_proba(frame)[0][1])
        vector = frame.to_numpy(dtype=float)
        return probability, feature_vector_as_dict(np.asarray(vector).ravel().tolist())

    # ------------------------------------------------------------------ info
    def info(self) -> dict:
        metrics = (self.metadata.get("metrics") or {}).get("random_forest") or {}
        return {
            "model_version": self.model_version,
            "algorithm": self.metadata.get("algorithm", "RandomForestClassifier"),
            "loaded": self.is_ready,
            "load_error": self.load_error,
            "trained_at": self.metadata.get("trained_at"),
            "hyperparameters": self.metadata.get("hyperparameters", {}),
            "feature_count": int(getattr(self.model, "n_features_in_", 0) or 0),
            "feature_columns": self.metadata.get("feature_columns", []),
            "scaled_columns": self.metadata.get("scaled_columns", []),
            "dataset": self.metadata.get("dataset", {}),
            "resampling": self.metadata.get("resampling", {}),
            "test_set_metrics": metrics,
            "baseline_metrics": (self.metadata.get("metrics") or {}).get(
                "logistic_regression_baseline"
            ),
            "threshold_analysis": self.metadata.get("threshold_analysis", []),
            "feature_importances_top15": self.metadata.get(
                "feature_importances_top15", []
            ),
            "notes": self.metadata.get("notes"),
        }
