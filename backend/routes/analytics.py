"""Analytics computed from persisted predictions."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from backend.auth.entra import ROLE_ANALYST, require_role

bp = Blueprint("analytics", __name__)


@bp.get("/analytics")
@require_role(ROLE_ANALYST)
def analytics():
    container = current_app.extensions["dhanraksha"]
    payload = container.transaction_service.analytics()
    payload["cases"] = container.case_service.summary()
    payload["model"] = {
        "model_version": container.model_service.model_version,
        "loaded": container.model_service.is_ready,
        "fraud_threshold": container.config.fraud_threshold,
    }
    return jsonify(payload), 200
