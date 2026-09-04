"""
Error types and Flask handlers.

All failures leave the API as a JSON body of the shape:

    {"error": "VALIDATION_ERROR", "message": "Amount must be a non-negative number."}

Internal exceptions are logged server-side and returned as a generic
INTERNAL_ERROR, so stack traces and file paths never reach the client.
"""

from __future__ import annotations

import logging
import uuid

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

logger = logging.getLogger("dhanraksha")


class ApiError(Exception):
    """Base class for errors that are safe to show to a caller."""

    code = "API_ERROR"
    status = 400

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_response(self) -> tuple[dict, int]:
        body: dict = {"error": self.code, "message": self.message}
        if self.details:
            body["details"] = self.details
        return body, self.status


class ValidationError(ApiError):
    code = "VALIDATION_ERROR"
    status = 400


class NotFoundError(ApiError):
    code = "NOT_FOUND"
    status = 404


class ConflictError(ApiError):
    code = "CONFLICT"
    status = 409


class ModelUnavailableError(ApiError):
    code = "MODEL_UNAVAILABLE"
    status = 503


class StorageError(ApiError):
    code = "STORAGE_ERROR"
    status = 500


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        body, status = exc.to_response()
        return jsonify(body), status

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc: HTTPException):
        code = {
            400: "BAD_REQUEST",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            415: "UNSUPPORTED_MEDIA_TYPE",
        }.get(exc.code or 500, "HTTP_ERROR")
        return (
            jsonify({"error": code, "message": exc.description}),
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        incident = uuid.uuid4().hex[:12]
        logger.exception("Unhandled error [incident=%s]", incident)
        return (
            jsonify(
                {
                    "error": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred. Please try again.",
                    "incident_id": incident,
                }
            ),
            500,
        )
