"""Model loading and inference against the real saved artifacts."""

from __future__ import annotations

import pytest

from backend.errors import ModelUnavailableError
from backend.services.model_service import ModelService
from ml.preprocessing import RawTransaction
from tests.conftest import requires_model


@requires_model
def test_model_loads_and_reports_ready(container):
    assert container.model_service.is_ready
    assert container.model_service.load_error is None


@requires_model
def test_model_expects_thirty_features(container):
    assert container.model_service.model.n_features_in_ == 30


@requires_model
def test_probability_is_a_real_number_in_range(container):
    raw = RawTransaction(amount=75.0, hour=10, v_features={f"V{i}": 0.0 for i in range(1, 29)})
    probability, features = container.model_service.predict_probability(raw)
    assert 0.0 <= probability <= 1.0
    assert len(features) == 30


@requires_model
def test_prediction_is_deterministic(container):
    raw = RawTransaction(amount=75.0, hour=10, v_features={"V14": -3.0})
    first, _ = container.model_service.predict_probability(raw)
    second, _ = container.model_service.predict_probability(raw)
    assert first == second


@requires_model
def test_metadata_records_train_only_smote(container):
    resampling = container.model_service.metadata["resampling"]
    assert resampling["method"] == "SMOTE"
    assert "training" in resampling["applied_to"]


@requires_model
def test_model_info_exposes_measured_metrics(container):
    info = container.model_service.info()
    metrics = info["test_set_metrics"]
    for key in ("precision", "recall", "f1_score", "roc_auc", "pr_auc"):
        assert 0.0 <= metrics[key] <= 1.0
    assert info["threshold_analysis"]


def test_missing_artifacts_degrade_instead_of_crashing(tmp_path):
    service = ModelService(
        model_path=str(tmp_path / "nope.pkl"),
        pipeline_path=str(tmp_path / "nope2.pkl"),
        metadata_path=str(tmp_path / "nope3.json"),
    )
    assert not service.is_ready
    assert service.load_error
    with pytest.raises(ModelUnavailableError):
        service.predict_probability(RawTransaction(amount=1.0, hour=1, v_features={}))
