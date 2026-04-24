"""Error translation helpers for agent runtimes."""

from __future__ import annotations

import logging
import re

from openai import RateLimitError

from sumampa_odoo_agent.services.errors import TooManyRequestsError, UpstreamServiceError

AGENT_RATE_LIMITED_MESSAGE = "El modelo esta temporalmente saturado. Reintenta en unos segundos."
AGENT_UPSTREAM_FAILURE_MESSAGE = "El servicio del agente no pudo completar la solicitud."
_RATE_LIMIT_RETRY_AFTER_PATTERN = re.compile(
    r"Please try again in (?P<seconds>\d+(?:\.\d+)?)s",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


def _translate_agent_run_error(
    exc: Exception,
    *,
    model: str,
) -> TooManyRequestsError | UpstreamServiceError | None:
    rate_limit_error = _find_openai_rate_limit_error(exc)
    if rate_limit_error is not None:
        retry_after_seconds = _extract_retry_after_seconds(rate_limit_error)
        details: dict[str, object] = {
            "provider": "openai",
            "model": model,
        }
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds
        return TooManyRequestsError(
            AGENT_RATE_LIMITED_MESSAGE,
            code="agent_rate_limited",
            details=details,
        )

    if any(_is_chat_client_exception(error) for error in _exception_chain(exc)):
        return UpstreamServiceError(
            AGENT_UPSTREAM_FAILURE_MESSAGE,
            code="agent_upstream_failure",
            details={
                "provider": "openai",
                "model": model,
                "exception_type": exc.__class__.__name__,
            },
        )

    return None


def _is_chat_client_exception(error: BaseException) -> bool:
    try:
        from agent_framework.exceptions import ChatClientException
    except ModuleNotFoundError:  # pragma: no cover
        return error.__class__.__name__ == "ChatClientException"
    return isinstance(error, ChatClientException)


def _find_openai_rate_limit_error(exc: Exception) -> RateLimitError | None:
    for error in _exception_chain(exc):
        if isinstance(error, RateLimitError):
            return error
    return None


def _exception_chain(exc: BaseException) -> list[BaseException]:
    errors: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        errors.append(current)
        current = current.__cause__ or current.__context__
    return errors


def _extract_retry_after_seconds(rate_limit_error: RateLimitError) -> float | None:
    retry_after = getattr(getattr(rate_limit_error, "response", None), "headers", {}).get(
        "retry-after"
    )
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            logger.debug("Ignoring non-numeric retry-after header: %s", retry_after)

    match = _RATE_LIMIT_RETRY_AFTER_PATTERN.search(str(rate_limit_error))
    if match is None:
        return None
    return float(match.group("seconds"))
