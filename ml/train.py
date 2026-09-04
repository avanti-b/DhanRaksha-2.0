"""
DhanRaksha training pipeline.

    dataset -> validate/clean -> stratified split -> fit scaler on TRAIN ONLY
            -> SMOTE on TRAIN ONLY -> Random Forest -> evaluate on untouched
               test set -> save versioned artifacts

Run:
    python -m ml.train --data data/creditcard.csv --version rf-v1

Everything written to ml/artifacts/ is consumed at inference time by the Flask
backend, so training and serving share one preprocessing object.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

from ml.evaluate import evaluate_classifier, threshold_analysis
from ml.preprocessing import (
    FEATURE_COLUMNS,
    FeaturePipeline,
    clean_dataset,
    hour_from_time,
    load_dataset,
    split_features_target,
)

DEFAULT_DATA_PATH = os.environ.get("DHANRAKSHA_DATASET", "data/creditcard.csv")
ARTIFACT_DIR = os.environ.get("DHANRAKSHA_ARTIFACT_DIR", "ml/artifacts")
RANDOM_SEED = 42
TEST_SIZE = 0.2
# Training parallelism. -1 uses all cores; constrained environments can set
# TRAIN_N_JOBS=1 to avoid worker processes duplicating the resampled matrix.
N_JOBS = int(os.environ.get("TRAIN_N_JOBS", -1))


def _log(message: str) -> None:
    print(message, flush=True)


def build_risk_reference(df: pd.DataFrame) -> dict:
    """
    Derive risk-engine thresholds from the TRAINING data itself.

    These are measured percentiles, not invented numbers. The risk engine reads
    them at runtime so its rules stay tied to the data distribution.
    """
    amounts = df["Amount"].astype(float)
    hours = df["Time"].map(hour_from_time)
    fraud_mask = df["Class"] == 1

    per_hour = (
        pd.DataFrame({"hour": hours, "fraud": fraud_mask.astype(int)})
        .groupby("hour")["fraud"]
        .agg(["sum", "count"])
    )
    per_hour["rate"] = per_hour["sum"] / per_hour["count"]
    overall_rate = float(fraud_mask.mean())
    elevated_hours = sorted(
        int(h) for h, row in per_hour.iterrows() if row["rate"] > 2 * overall_rate
    )

    # PCA components with the strongest separation in this dataset. The bounds
    # are the 0.5th/99.5th percentile of the legitimate class, so "outside the
    # bound" literally means "outside the normal range of legitimate traffic".
    pca_bounds = {}
    for column in ["V14", "V17", "V12", "V10", "V4", "V11"]:
        legit = df.loc[~fraud_mask, column].astype(float)
        pca_bounds[column] = {
            "low": float(np.percentile(legit, 0.5)),
            "high": float(np.percentile(legit, 99.5)),
        }

    return {
        "derived_from": "training split of the Kaggle credit-card dataset",
        "amount_percentiles": {
            "p50": float(np.percentile(amounts, 50)),
            "p95": float(np.percentile(amounts, 95)),
            "p99": float(np.percentile(amounts, 99)),
            "p999": float(np.percentile(amounts, 99.9)),
            "max": float(amounts.max()),
        },
        "overall_fraud_rate": overall_rate,
        "fraud_rate_by_hour": {
            str(int(h)): float(row["rate"]) for h, row in per_hour.iterrows()
        },
        "elevated_risk_hours": elevated_hours,
        "pca_legit_bounds": pca_bounds,
    }


def train(
    data_path: str = DEFAULT_DATA_PATH,
    artifact_dir: str = ARTIFACT_DIR,
    model_version: str = "rf-v1",
    n_estimators: int = 100,
    max_depth: int | None = None,
    train_baseline: bool = True,
) -> dict:
    started = time.time()
    os.makedirs(artifact_dir, exist_ok=True)

    # ---------------------------------------------------------- 1. load/clean
    _log("[1/6] Loading dataset ...")
    df = load_dataset(data_path)
    df, clean_report = clean_dataset(df)
    _log(f"      {clean_report}")

    X, y = split_features_target(df)
    _log(f"      Features {X.shape} | fraud={int(y.sum())} legit={int((y == 0).sum())}")

    # ------------------------------------------------------------- 2. split
    _log("[2/6] Stratified train/test split (test set stays untouched) ...")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_SEED, stratify=y
    )
    _log(
        f"      train={len(X_train):,} (fraud {int(y_train.sum())}) | "
        f"test={len(X_test):,} (fraud {int(y_test.sum())})"
    )

    # -------------------------------------------------- 3. fit preprocessing
    _log("[3/6] Fitting preprocessing on TRAINING data only ...")
    pipeline = FeaturePipeline()
    X_train_scaled = pipeline.fit_transform(X_train)
    X_test_scaled = pipeline.transform(X_test)

    # ------------------------------------------------------------- 4. SMOTE
    _log("[4/6] SMOTE on the training split only ...")
    before = {"legit": int((y_train == 0).sum()), "fraud": int((y_train == 1).sum())}
    smote = SMOTE(random_state=RANDOM_SEED)
    X_train_res, y_train_res = smote.fit_resample(X_train_scaled, y_train)
    after = {
        "legit": int((y_train_res == 0).sum()),
        "fraud": int((y_train_res == 1).sum()),
    }
    _log(f"      before={before} after={after}")

    # ------------------------------------------------------------- 5. train
    _log(f"[5/6] Training RandomForest (n_estimators={n_estimators}) ...")
    rf = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        class_weight="balanced",
        random_state=RANDOM_SEED,
        n_jobs=N_JOBS,
    )
    rf.fit(X_train_res, y_train_res)

    rf_probabilities = rf.predict_proba(X_test_scaled)[:, 1]
    rf_metrics = evaluate_classifier(y_test.to_numpy(), rf_probabilities, threshold=0.5)
    _log(
        "      RF  "
        f"P={rf_metrics['precision']:.4f} R={rf_metrics['recall']:.4f} "
        f"F1={rf_metrics['f1_score']:.4f} ROC-AUC={rf_metrics['roc_auc']:.4f} "
        f"PR-AUC={rf_metrics['pr_auc']:.4f}"
    )

    baseline_metrics = None
    if train_baseline:
        _log("      Training LogisticRegression baseline ...")
        lr = LogisticRegression(
            max_iter=1000, class_weight="balanced", random_state=RANDOM_SEED
        )
        lr.fit(X_train_res, y_train_res)
        lr_probabilities = lr.predict_proba(X_test_scaled)[:, 1]
        baseline_metrics = evaluate_classifier(
            y_test.to_numpy(), lr_probabilities, threshold=0.5
        )
        _log(
            "      LR  "
            f"P={baseline_metrics['precision']:.4f} R={baseline_metrics['recall']:.4f} "
            f"F1={baseline_metrics['f1_score']:.4f} "
            f"ROC-AUC={baseline_metrics['roc_auc']:.4f}"
        )

    thresholds = threshold_analysis(y_test.to_numpy(), rf_probabilities)

    # --------------------------------------------------------- 6. artifacts
    _log("[6/6] Saving artifacts ...")
    model_path = os.path.join(artifact_dir, "fraud_model.pkl")
    pipeline_path = os.path.join(artifact_dir, "feature_pipeline.pkl")
    joblib.dump(rf, model_path, compress=3)
    pipeline.save(pipeline_path)

    importances = sorted(
        (
            {"feature": name, "importance": float(score)}
            for name, score in zip(FEATURE_COLUMNS, rf.feature_importances_)
        ),
        key=lambda item: item["importance"],
        reverse=True,
    )

    train_frame = X_train.copy()
    train_frame["Class"] = y_train.to_numpy()
    risk_reference = build_risk_reference(train_frame)

    metadata = {
        "model_version": model_version,
        "algorithm": "RandomForestClassifier",
        "hyperparameters": {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "class_weight": "balanced",
            "random_state": RANDOM_SEED,
            "min_samples_leaf": 1,
        },
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_duration_seconds": round(time.time() - started, 2),
        "python_version": platform.python_version(),
        "feature_columns": FEATURE_COLUMNS,
        "scaled_columns": pipeline.scaled_columns,
        "dataset": {
            "path": os.path.basename(data_path),
            "cleaning": clean_report,
            "total_rows": int(len(df)),
            "fraud_rows": int(y.sum()),
            "legitimate_rows": int((y == 0).sum()),
            "fraud_percentage": round(float(y.mean() * 100), 4),
            "test_size": TEST_SIZE,
            "random_seed": RANDOM_SEED,
        },
        "resampling": {
            "method": "SMOTE",
            "applied_to": "training split only",
            "before": before,
            "after": after,
        },
        "metrics": {
            "random_forest": rf_metrics,
            "logistic_regression_baseline": baseline_metrics,
        },
        "threshold_analysis": thresholds,
        "feature_importances_top15": importances[:15],
        "risk_reference": risk_reference,
        "notes": (
            "Metrics measured on the untouched stratified test split. SMOTE was "
            "never applied to the test data and the scaler was fitted on the "
            "training split only."
        ),
    }

    metadata_path = os.path.join(artifact_dir, "model_metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    _log(f"      model     -> {model_path}")
    _log(f"      pipeline  -> {pipeline_path}")
    _log(f"      metadata  -> {metadata_path}")
    _log(f"Done in {time.time() - started:.1f}s")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the DhanRaksha fraud model")
    parser.add_argument("--data", default=DEFAULT_DATA_PATH)
    parser.add_argument("--artifacts", default=ARTIFACT_DIR)
    parser.add_argument("--version", default="rf-v1")
    parser.add_argument("--n-estimators", type=int, default=100)
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--no-baseline", action="store_true")
    args = parser.parse_args()

    train(
        data_path=args.data,
        artifact_dir=args.artifacts,
        model_version=args.version,
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        train_baseline=not args.no_baseline,
    )


if __name__ == "__main__":
    main()
