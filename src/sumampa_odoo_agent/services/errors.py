"""Service-level error contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ApplicationError(Exception):
    """Base error type used across services and API handlers."""

    message: str
    code: str = "application_error"
    details: dict[str, Any] = field(default_factory=dict)
    status_code: int = 500

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": self.__class__.__name__,
            "message": self.message,
            "code": self.code,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(ApplicationError):
    """Validation-level service error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "validation_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            details={} if details is None else details,
            status_code=400,
        )


class NotFoundError(ApplicationError):
    """Not-found service error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "not_found",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            details={} if details is None else details,
            status_code=404,
        )


class ConflictError(ApplicationError):
    """Conflict service error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "conflict",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            details={} if details is None else details,
            status_code=409,
        )


class ConfigurationError(ApplicationError):
    """Raised when the service is missing required runtime configuration."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "configuration_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            details={} if details is None else details,
            status_code=500,
        )


class TooManyRequestsError(ApplicationError):
    """Raised when the caller should retry later."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "too_many_requests",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            details={} if details is None else details,
            status_code=429,
        )


class UpstreamServiceError(ApplicationError):
    """Raised when an external dependency fails to complete the request."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "upstream_service_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            details={} if details is None else details,
            status_code=502,
        )
