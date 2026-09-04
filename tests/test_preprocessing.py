"""Preprocessing must behave identically at training and inference time."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.preprocessing import (
    FEATURE_COLUMNS,
    FeaturePipeline,
    PreprocessingError,
    RawTransaction,
    clean_dataset,
    coerce_v_features,
    feature_vector_as_dict,
    hour_from_time,
)


def _frame(rows: int = 20) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    data = {"Time": rng.uniform(0, 172_000, rows), "Amount": rng.uniform(0, 500, rows)}
    for column in FEATURE_COLUMNS:
        if column not in data:
            data[column] = rng.normal(0, 1, rows)
    return pd.DataFrame(data)[FEATURE_COLUMNS]


def test_feature_order_is_time_then_v_then_amount():
    assert FEATURE_COLUMNS[0] == "Time"
    assert FEATURE_COLUMNS[-1] == "Amount"
    assert FEATURE_COLUMNS[1:29] == [f"V{i}" for i in range(1, 29)]
    assert len(FEATURE_COLUMNS) == 30


def test_only_time_and_amount_are_scaled():
    frame = _frame()
    pipeline = FeaturePipeline()
    transformed = pipeline.fit_transform(frame)
    # PCA components must pass through untouched.
    for column in [f"V{i}" for i in range(1, 29)]:
        assert np.allclose(transformed[column], frame[column])
    # Time and Amount must have been standardised.
    assert not np.allclose(transformed["Time"], frame["Time"])
    assert pytest.approx(0.0, abs=1e-9) == transformed["Amount"].mean()


def test_transform_before_fit_raises():
    with pytest.raises(PreprocessingError):
        FeaturePipeline().transform(_frame())


def test_missing_columns_are_rejected():
    pipeline = FeaturePipeline().fit(_frame())
    with pytest.raises(PreprocessingError):
        pipeline.transform(_frame().drop(columns=["V5"]))


def test_pipeline_roundtrips_through_disk(tmp_path):
    frame = _frame()
    pipeline = FeaturePipeline().fit(frame)
    path = pipeline.save(str(tmp_path / "pipeline.pkl"))
    reloaded = FeaturePipeline.load(path)
    assert np.allclose(pipeline.transform(frame), reloaded.transform(frame))


def test_single_transaction_produces_one_row_of_thirty():
    pipeline = FeaturePipeline().fit(_frame())
    raw = RawTransaction(amount=100.0, hour=3, v_features={"V1": 1.5})
    vector = pipeline.transform_transaction(raw)
    assert vector.shape == (1, 30)
    # An unsupplied component defaults to the mean of a centred component.
    assert vector[0][2] == 0.0


def test_clean_dataset_removes_duplicates():
    frame = _frame(5)
    doubled = pd.concat([frame, frame], ignore_index=True)
    doubled["Class"] = 0
    cleaned, report = clean_dataset(doubled)
    assert report["duplicate_rows_dropped"] == 5
    assert len(cleaned) == 5


def test_coerce_accepts_both_key_casings():
    features = coerce_v_features({"v1": 2.0, "V2": -1.0})
    assert features["V1"] == 2.0
    assert features["V2"] == -1.0
    assert features["V28"] == 0.0


def test_hour_from_time_wraps_across_days():
    assert hour_from_time(0) == 0
    assert hour_from_time(3600 * 5) == 5
    assert hour_from_time(3600 * 26) == 2


def test_feature_vector_as_dict_rejects_wrong_length():
    with pytest.raises(PreprocessingError):
        feature_vector_as_dict([0.0, 1.0])
