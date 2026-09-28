"""Application error hierarchy and the JSON envelope every failure is rendered in.

Every error raised by the service layer is an ``AppError``. ``main.py`` installs a
single handler for it, so routers never build error responses by hand and the
response shape is identical across the whole API.
"""

from typing import Any


class AppError(Exception):
    """Base class for all expected (non-bug) failures."""

    status_code: int = 400
    code: str = "bad_request"
    message: str = "Request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            body["error"]["details"] = self.details
        return body


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Request conflicts with the current state of the resource."


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "Request failed validation."


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "Authentication credentials are missing or invalid."


class PermissionError_(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to perform this action."


class InvalidStateTransition(ConflictError):
    code = "invalid_state_transition"
