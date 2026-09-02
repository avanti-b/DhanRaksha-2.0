"""POST /api/v1/predict - score a transaction end to end."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.schemas.validators import validate_prediction_payload

bp = Blueprint("prediction", __name__)


@bp.post("/predict")
def predict():
    payload = request.get_json(silent=True)
    validated = validate_prediction_payload(payload)
    result = current_app.extensions["dhanraksha"].fraud_service.predict(validated)
    return jsonify(result), 201
