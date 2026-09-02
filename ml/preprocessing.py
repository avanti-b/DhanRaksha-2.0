"""
Shared preprocessing for DhanRaksha.

This module is the single source of truth for how a transaction becomes a
feature vector. Both `ml/train.py` and the Flask inference path import it, so
training-time and serving-time preprocessing can never drift apart.

Column contract (Kaggle Credit Card Fraud dataset):
    [Time, V1 ... V28, Amount]  -> 30 columns, in this exact order.

Scaling rule (inherited from the original DhanRaksha project and kept):
    Only Time and Amount are standardised. V1-V28 are PCA components that are
    already centred/scaled by the dataset authors and must not be re-scaled.

Difference from the original project: the StandardScaler is now fitted on the
TRAINING SPLIT ONLY. The original `train_model.py` fitted it on the full frame
before `train_test_split`, which leaks test-set statistics into training.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

V_COLUMNS: list[str] = [f"V{i}" for i in range(1, 29)]
FEATURE_COLUMNS: list[str] = ["Time", *V_COLUMNS, "Amount"]
SCALED_COLUMNS: list[str] = ["Time", "Amount"]
TARGET_COLUMN = "Class"

SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400


class PreprocessingError(ValueError):
    """Raised when an input cannot be turned into a valid feature vector."""


@dataclass(frozen=True)
class RawTransaction:
    """A transaction as it arrives from the API, before scaling."""

    amount: float
    hour: int
    v_features: dict[str, float]

    @property
    def time_seconds(self) -> float:
        """
        Approximate the dataset's `Time` column from an hour-of-day.

        The dataset's Time is "seconds elapsed since the first transaction"
        spanning two days (0 - 172792). The API accepts an hour-of-day because
        that is what a human can meaningfully supply, so hour is mapped onto
        the first day. This approximation is documented in docs/ml-pipeline.md
        and is applied identically at training time when replaying dataset rows.
        """
        return float(self.hour) * SECONDS_PER_HOUR


class FeaturePipeline:
    """
    Fit/transform wrapper around the StandardScaler plus column ordering.

    Persisted as a single artifact so the backend loads exactly the object that
    was fitted during training.
    """

    def __init__(self, scaler: StandardScaler | None = None) -> None:
        self.scaler = scaler or StandardScaler()
        self.feature_columns = list(FEATURE_COLUMNS)
        self.scaled_columns = list(SCALED_COLUMNS)
        self._fitted = scaler is not None

    # ------------------------------------------------------------------ fit
    def fit(self, X_train: pd.DataFrame) -> "FeaturePipeline":
        """Fit the scaler on the TRAINING split only."""
        _require_columns(X_train)
        self.scaler.fit(X_train[self.scaled_columns])
        self._fitted = True
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Scale Time/Amount, leave V1-V28 untouched, enforce column order."""
        if not self._fitted:
            raise PreprocessingError("FeaturePipeline has not been fitted.")
        _require_columns(X)
        out = X[self.feature_columns].copy()
        out[self.scaled_columns] = self.scaler.transform(out[self.scaled_columns])
        return out

    def fit_transform(self, X_train: pd.DataFrame) -> pd.DataFrame:
        return self.fit(X_train).transform(X_train)

    # ------------------------------------------------------------ inference
    def transform_transaction_frame(self, raw: RawTransaction) -> pd.DataFrame:
        """
        Turn a single API transaction into a 1-row model-ready DataFrame.

        A DataFrame rather than a bare array so the column names reach the
        estimator; scikit-learn warns when a model fitted on named columns is
        asked to predict on an anonymous array.
        """
        row = {"Time": raw.time_seconds, "Amount": float(raw.amount)}
        for name in V_COLUMNS:
            row[name] = float(raw.v_features.get(name, 0.0))
        frame = pd.DataFrame([row], columns=self.feature_columns)
        return self.transform(frame)

    def transform_transaction(self, raw: RawTransaction) -> np.ndarray:
        """Same as transform_transaction_frame, as a (1, 30) array."""
        return self.transform_transaction_frame(raw).to_numpy(dtype=float)

    # ---------------------------------------------------------- persistence
    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        joblib.dump(
            {
                "scaler": self.scaler,
                "feature_columns": self.feature_columns,
                "scaled_columns": self.scaled_columns,
            },
            path,
        )
        return path

    @classmethod
    def load(cls, path: str) -> "FeaturePipeline":
        payload = joblib.load(path)
        if isinstance(payload, StandardScaler):
            # Backwards compatibility with the original project's scaler.pkl,
            # which stored a bare 2-column StandardScaler.
            pipeline = cls(scaler=payload)
        else:
            pipeline = cls(scaler=payload["scaler"])
            pipeline.feature_columns = list(payload["feature_columns"])
            pipeline.scaled_columns = list(payload["scaled_columns"])
        pipeline._fitted = True
        return pipeline


def _require_columns(frame: pd.DataFrame) -> None:
    missing = [c for c in FEATURE_COLUMNS if c not in frame.columns]
    if missing:
        raise PreprocessingError(f"Missing feature columns: {missing}")


# --------------------------------------------------------------- dataset IO
def load_dataset(path: str) -> pd.DataFrame:
    """Load and validate the raw Kaggle CSV."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Dataset not found at '{path}'. Download creditcard.csv from "
            "https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud"
        )
    df = pd.read_csv(path)
    expected = set(FEATURE_COLUMNS + [TARGET_COLUMN])
    missing = expected - set(df.columns)
    if missing:
        raise PreprocessingError(f"Dataset is missing columns: {sorted(missing)}")
    return df


def clean_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Drop null rows and exact duplicates. Returns the frame and a report."""
    before = len(df)
    null_rows = int(df.isnull().any(axis=1).sum())
    df = df.dropna()
    after_nulls = len(df)
    df = df.drop_duplicates()
    after_dupes = len(df)
    report = {
        "rows_in": before,
        "rows_with_nulls_dropped": null_rows,
        "duplicate_rows_dropped": after_nulls - after_dupes,
        "rows_out": after_dupes,
    }
    return df.reset_index(drop=True), report


def split_features_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    return df[FEATURE_COLUMNS].copy(), df[TARGET_COLUMN].astype(int).copy()


def hour_from_time(time_seconds: float) -> int:
    """Dataset Time (seconds) -> hour of day. Used for EDA and rule thresholds."""
    return int((float(time_seconds) // SECONDS_PER_HOUR) % 24)


def coerce_v_features(payload: Mapping[str, Any]) -> dict[str, float]:
    """
    Accept `v1`/`V1` style keys from an API payload and normalise to `V1`.

    Absent components default to 0.0, which is the mean of a PCA component.
    """
    features: dict[str, float] = {}
    for index in range(1, 29):
        name = f"V{index}"
        value = payload.get(name, payload.get(f"v{index}", 0.0))
        features[name] = float(value if value is not None else 0.0)
    return features


def feature_vector_as_dict(vector: Sequence[float]) -> dict[str, float]:
    """Label a raw 30-length vector with its column names (for storage/debug)."""
    if len(vector) != len(FEATURE_COLUMNS):
        raise PreprocessingError(
            f"Expected {len(FEATURE_COLUMNS)} features, received {len(vector)}."
        )
    return {name: float(value) for name, value in zip(FEATURE_COLUMNS, vector)}
