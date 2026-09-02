"""Fraud case management endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.errors import ValidationError

bp = Blueprint("cases", __name__)


def _service():
    return current_app.extensions["dhanraksha"].case_service


@bp.get("/cases")
def list_cases():
    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ValidationError("limit and offset must be integers.") from None
    status = request.args.get("status")
    return jsonify(_service().list(limit=limit, offset=offset, status=status)), 200


@bp.get("/cases/<case_id>")
def get_case(case_id: str):
    return jsonify(_service().get(case_id)), 200


@bp.post("/cases")
def create_case():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    return jsonify(_service().create(payload)), 201


@bp.patch("/cases/<case_id>")
def update_case(case_id: str):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    return jsonify(_service().update(case_id, payload)), 200
