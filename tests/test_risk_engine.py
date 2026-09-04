"""The risk engine must be deterministic, explainable and additive-only."""

from __future__ import annotations

from backend.services.risk_engine import HIGH, LOW, MEDIUM, RiskEngine

REFERENCE = {
    "derived_from": "test fixture",
    "amount_percentiles": {"p99": 1000.0, "p999": 3000.0},
    "elevated_risk_hours": [2, 3],
    "pca_legit_bounds": {"V14": {"low": -3.0, "high": 2.5}},
}


def engine() -> RiskEngine:
    return RiskEngine(high_threshold=0.70, medium_threshold=0.40, reference=REFERENCE)


def test_low_probability_ordinary_transaction_is_low_risk():
    result = engine().assess(model_probability=0.01, amount=25.0, hour=14)
    assert result.risk_level == LOW
    assert result.signals == []


def test_high_probability_is_high_risk():
    result = engine().assess(model_probability=0.95, amount=25.0, hour=14)
    assert result.risk_level == HIGH
    assert "high_model_probability" in result.signals


def test_mid_probability_is_medium_risk():
    result = engine().assess(model_probability=0.45, amount=25.0, hour=14)
    assert result.risk_level == MEDIUM
    assert "elevated_model_probability" in result.signals


def test_rules_add_risk_and_can_escalate_the_band():
    quiet = engine().assess(model_probability=0.38, amount=25.0, hour=14)
    noisy = engine().assess(model_probability=0.38, amount=5000.0, hour=3)
    assert quiet.risk_level == LOW
    assert noisy.risk_level == MEDIUM
    assert noisy.risk_score > quiet.risk_score


def test_rule_contribution_is_capped():
    result = engine().assess(
        model_probability=0.5, amount=9999.0, hour=2, v_features={"V14": -20.0}
    )
    assert result.risk_score <= 0.5 + 0.25 + 1e-9


def test_score_never_falls_below_the_model_probability():
    result = engine().assess(model_probability=0.62, amount=1.0, hour=12)
    assert result.risk_score >= 0.62


def test_pca_outside_legitimate_range_is_flagged():
    result = engine().assess(
        model_probability=0.1, amount=25.0, hour=14, v_features={"V14": -9.0}
    )
    assert "anomalous_pca_components" in result.signals


def test_pca_inside_legitimate_range_is_not_flagged():
    result = engine().assess(
        model_probability=0.1, amount=25.0, hour=14, v_features={"V14": 1.0}
    )
    assert "anomalous_pca_components" not in result.signals


def test_zero_amount_probe_is_flagged():
    result = engine().assess(model_probability=0.1, amount=0.0, hour=14)
    assert "zero_amount_probe" in result.signals


def test_assessment_is_deterministic():
    first = engine().assess(0.55, 1500.0, 3, {"V14": -4.0})
    second = engine().assess(0.55, 1500.0, 3, {"V14": -4.0})
    assert first.to_dict() == second.to_dict()


def test_every_signal_has_an_explanation():
    result = engine().assess(0.9, 5000.0, 2, {"V14": -8.0})
    assert len(result.triggered_rules) == len(result.signals)
    for rule in result.triggered_rules:
        assert rule["description"]
    assert "Risk classified HIGH" in result.explanation


def test_behavioural_signals_are_optional_and_absent_by_default():
    without = engine().assess(0.2, 25.0, 14)
    with_signals = engine().assess(0.2, 25.0, 14, behavioural_signals={"new_device": True})
    assert "unrecognised_device" not in without.signals
    assert "unrecognised_device" in with_signals.signals


def test_probability_is_clamped_to_unit_interval():
    assert engine().assess(1.9, 10.0, 12).model_probability == 1.0
    assert engine().assess(-0.4, 10.0, 12).model_probability == 0.0
