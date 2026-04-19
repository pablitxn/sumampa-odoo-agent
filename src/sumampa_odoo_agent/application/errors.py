"""Application-level error contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sumampa_odoo_agent.application.message_specs import render_message


@dataclass(slots=True)
class ApplicationError(Exception):
    """Base error type used across application and adapters."""

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
    """Validation-level application error."""

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
    """Not found application error."""

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
    """Conflict application error."""

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


class DisabledModuleError(NotFoundError):
    """Raised when trying to use a disabled module endpoint/tool."""

    def __init__(self, module_name: str) -> None:
        super().__init__(
            render_message("runtime.json", "module_disabled", module_name=module_name),
            code="module_disabled",
            details={"module": module_name},
        )
