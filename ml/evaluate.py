"""
Evaluation utilities for DhanRaksha.

Accuracy is deliberately not the headline metric: with a 0.17% fraud rate a
model that predicts "legitimate" for everything scores 99.8% accuracy and
catches nothing. Precision, recall, F1, ROC-AUC, PR-AUC and the raw
false-positive / false-negative counts are reported instead.

Can be run standalone against saved artifacts:
    python -m ml.evaluate --data data/creditcard.csv
"""

from __future__ import annotations

import argparse
import json
import os

import joblib
import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from ml.preprocessing import (
    FeaturePipeline,
    clean_dataset,
    load_dataset,
    split_features_target,
)

DEFAULT_THRESHOLDS = [0.30, 0.40, 0.50, 0.60, 0.70]


def evaluate_classifier(
    y_true: np.ndarray, y_probabilities: np.ndarray, threshold: float = 0.5
) -> dict:
    """Full metric set for one decision threshold."""
    y_true = np.asarray(y_true).astype(int)
    y_probabilities = np.asarray(y_probabilities, dtype=float)
    y_pred = (y_probabilities >= threshold).astype(int)

    matrix = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())

    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, y_probabilities)),
        "pr_auc": float(average_precision_score(y_true, y_probabilities)),
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "true_positives": tp,
        "support": {"legitimate": int((y_true == 0).sum()), "fraud": int(y_true.sum())},
    }


def threshold_analysis(
    y_true: np.ndarray,
    y_probabilities: np.ndarray,
    thresholds: list[float] | None = None,
) -> list[dict]:
    """
    Precision/recall/F1 across candidate decision thresholds.

    Lower threshold  -> more fraud caught, more legitimate customers flagged.
    Higher threshold -> fewer false alarms, more fraud slips through.
    The chosen operating point is a business decision, so the threshold is
    configuration (FRAUD_THRESHOLD), never a hardcoded 0.5 in the codebase.
    """
    rows = []
    for threshold in thresholds or DEFAULT_THRESHOLDS:
        metrics = evaluate_classifier(y_true, y_probabilities, threshold)
        rows.append(
            {
                "threshold": round(float(threshold), 2),
                "precision": round(metrics["precision"], 4),
                "recall": round(metrics["recall"], 4),
                "f1_score": round(metrics["f1_score"], 4),
                "false_positives": metrics["false_positives"],
                "false_negatives": metrics["false_negatives"],
            }
        )
    return rows


def evaluate_saved_model(
    data_path: str, artifact_dir: str = "ml/artifacts", threshold: float = 0.5
) -> dict:
    """Re-score the saved artifacts on the same held-out split used in training."""
    model = joblib.load(os.path.join(artifact_dir, "fraud_model.pkl"))
    pipeline = FeaturePipeline.load(os.path.join(artifact_dir, "feature_pipeline.pkl"))

    df, _ = clean_dataset(load_dataset(data_path))
    X, y = split_features_target(df)
    _, X_test, _, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    probabilities = model.predict_proba(pipeline.transform(X_test))[:, 1]

    return {
        "metrics": evaluate_classifier(y_test.to_numpy(), probabilities, threshold),
        "threshold_analysis": threshold_analysis(y_test.to_numpy(), probabilities),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate saved DhanRaksha artifacts")
    parser.add_argument("--data", default="data/creditcard.csv")
    parser.add_argument("--artifacts", default="ml/artifacts")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    report = evaluate_saved_model(args.data, args.artifacts, args.threshold)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
