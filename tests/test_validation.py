"""Input validation rejects malformed requests before anything else runs."""

from __future__ import annotations

import pytest

from backend.errors import ValidationError
from backend.schemas.validators import validate_list_query, validate_prediction_payload


def base(**overrides) -> dict:
    payload = {"amount": 100.0, "hour": 12}
    payload.update(overrides)
    return payload


def test_valid_payload_is_normalised():
    result = validate_prediction_payload(base(v1=1.25))
    assert result["amount"] == 100.0
    assert result["hour"] == 12
    assert result["v_features"]["V1"] == 1.25
    assert result["v_features"]["V28"] == 0.0
    assert result["v_features_supplied"] == 1


@pytest.mark.parametrize("payload", [None, [], "amount=5", 42])
def test_non_object_bodies_are_rejected(payload):
    with pytest.raises(ValidationError):
        validate_prediction_payload(payload)


def test_missing_required_fields_are_named():
    with pytest.raises(ValidationError) as excinfo:
        validate_prediction_payload({"hour": 3})
    assert "amount" in str(excinfo.value)


def test_negative_amount_is_rejected():
    with pytest.raises(ValidationError, match="non-negative"):
        validate_prediction_payload(base(amount=-1))


def test_absurd_amount_is_rejected():
    with pytest.raises(ValidationError):
        validate_prediction_payload(base(amount=10_000_000))


@pytest.mark.parametrize("hour", [-1, 24, 99, 12.5])
def test_out_of_range_hours_are_rejected(hour):
    with pytest.raises(ValidationError):
        validate_prediction_payload(base(hour=hour))


@pytest.mark.parametrize("amount", ["abc", None, True, float("nan"), float("inf")])
def test_non_numeric_amounts_are_rejected(amount):
    with pytest.raises(ValidationError):
        validate_prediction_payload(base(amount=amount))


def test_numeric_strings_are_accepted():
    result = validate_prediction_payload({"amount": "250.50", "hour": "8"})
    assert result["amount"] == 250.50
    assert result["hour"] == 8


def test_implausible_pca_component_is_rejected():
    with pytest.raises(ValidationError, match="plausible range"):
        validate_prediction_payload(base(v14=5000))


def test_behavioural_signals_must_be_an_object():
    with pytest.raises(ValidationError):
        validate_prediction_payload(base(behavioural_signals="new_device"))


def test_list_query_defaults():
    query = validate_list_query({})
    assert query["limit"] == 50
    assert query["offset"] == 0
    assert query["risk_level"] is None


def test_list_query_rejects_bad_values():
    with pytest.raises(ValidationError):
        validate_list_query({"limit": "many"})
    with pytest.raises(ValidationError):
        validate_list_query({"limit": 5000})
    with pytest.raises(ValidationError):
        validate_list_query({"offset": -3})
    with pytest.raises(ValidationError):
        validate_list_query({"risk_level": "CRITICAL"})
    with pytest.raises(ValidationError):
        validate_list_query({"prediction": "maybe"})


def test_list_query_normalises_case():
    query = validate_list_query({"risk_level": "high", "prediction": "FRAUD"})
    assert query["risk_level"] == "HIGH"
    assert query["prediction"] == "fraud"
