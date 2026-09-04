"""End-to-end API behaviour through the Flask test client."""

from __future__ import annotations

from tests.conftest import requires_model


def test_health_reports_components(client):
    response = client.get("/api/v1/health")
    body = response.get_json()
    assert response.status_code in (200, 503)
    assert "model" in body["components"]
    assert "database" in body["components"]
    assert body["api_version"] == "v1"


@requires_model
def test_model_info_returns_metrics_and_risk_config(client):
    response = client.get("/api/v1/model-info")
    body = response.get_json()
    assert response.status_code == 200
    assert body["loaded"] is True
    assert body["test_set_metrics"]["precision"] > 0
    assert body["risk_engine"]["risk_high_threshold"] > body["risk_engine"]["risk_medium_threshold"]


@requires_model
def test_predict_returns_a_full_decision(client, sample_payload):
    response = client.post("/api/v1/predict", json=sample_payload)
    body = response.get_json()
    assert response.status_code == 201
    assert body["transaction_id"].startswith("TXN-")
    assert body["prediction"] in ("fraud", "legitimate")
    assert 0.0 <= body["fraud_probability"] <= 1.0
    assert body["risk_level"] in ("LOW", "MEDIUM", "HIGH")
    assert body["model_version"]
    assert body["timestamp"]
    assert isinstance(body["risk_signals"], list)


@requires_model
def test_prediction_is_persisted_and_retrievable(client, sample_payload):
    created = client.post("/api/v1/predict", json=sample_payload).get_json()
    response = client.get(f"/api/v1/transactions/{created['transaction_id']}")
    body = response.get_json()
    assert response.status_code == 200
    assert body["transaction"]["transaction_id"] == created["transaction_id"]
    assert body["transaction"]["fraud_probability"] == created["fraud_probability"]


def test_unknown_transaction_returns_404(client):
    response = client.get("/api/v1/transactions/TXN-DOESNOTEXIST")
    assert response.status_code == 404
    assert response.get_json()["error"] == "NOT_FOUND"


def test_missing_fields_return_a_clean_validation_error(client):
    response = client.post("/api/v1/predict", json={"hour": 4})
    body = response.get_json()
    assert response.status_code == 400
    assert body["error"] == "VALIDATION_ERROR"
    assert "amount" in body["message"]
    assert "Traceback" not in str(body)


def test_invalid_values_return_400(client):
    assert client.post("/api/v1/predict", json={"amount": -5, "hour": 2}).status_code == 400
    assert client.post("/api/v1/predict", json={"amount": 10, "hour": 47}).status_code == 400
    assert client.post("/api/v1/predict", json={"amount": "x", "hour": 2}).status_code == 400


def test_empty_body_returns_400(client):
    assert client.post("/api/v1/predict", json=None).status_code == 400


def test_unknown_route_returns_json_not_html(client):
    response = client.get("/api/v1/nowhere")
    assert response.status_code == 404
    assert response.get_json()["error"] == "NOT_FOUND"


def test_analytics_on_an_empty_store_reports_zeros(client):
    body = client.get("/api/v1/analytics").get_json()
    assert body["totals"]["total_transactions"] == 0
    assert body["totals"]["fraud_rate_percent"] == 0.0
    assert body["recent_transactions"] == []


@requires_model
def test_analytics_reflects_persisted_predictions(client, sample_payload):
    for amount in (10.0, 250.0, 900.0):
        client.post("/api/v1/predict", json={**sample_payload, "amount": amount})
    body = client.get("/api/v1/analytics").get_json()
    assert body["totals"]["total_transactions"] == 3
    assert sum(body["risk_distribution"].values()) == 3
    assert body["amounts"]["average_amount"] > 0
    assert len(body["recent_transactions"]) == 3
