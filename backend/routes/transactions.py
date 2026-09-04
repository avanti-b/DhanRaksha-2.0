"""Transaction history endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.auth.entra import ROLE_ANALYST, require_role
from backend.schemas.validators import validate_list_query

bp = Blueprint("transactions", __name__)


@bp.get("/transactions")
@require_role(ROLE_ANALYST)
def list_transactions():
    container = current_app.extensions["dhanraksha"]
    query = validate_list_query(request.args, container.config.max_page_size)
    return jsonify(container.transaction_service.list(**query)), 200


@bp.get("/transactions/<transaction_id>")
@require_role(ROLE_ANALYST)
def get_transaction(transaction_id: str):
    container = current_app.extensions["dhanraksha"]
    transaction = container.transaction_service.get(transaction_id)
    case = container.case_service.cases.get_by_transaction(transaction_id)
    return jsonify({"transaction": transaction, "case": case}), 200
