"""Unit tests for agent service helpers."""

import httpx
from openai import RateLimitError

from sumampa_odoo_agent.integrations.agent.errors import _translate_agent_run_error
from sumampa_odoo_agent.integrations.agent.framework import _load_openai_chat_client
from sumampa_odoo_agent.services.errors import TooManyRequestsError


def test_load_openai_chat_client_handles_upstream_version_gap() -> None:
    client_cls = _load_openai_chat_client()
    assert client_cls.__name__ == "OpenAIChatClient"


def test_translate_agent_run_error_maps_rate_limit_to_application_error() -> None:
    from agent_framework.exceptions import ChatClientException

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(
        429,
        headers={"retry-after": "2.536"},
        request=request,
    )
    rate_limit_error = RateLimitError(
        "Rate limit reached for gpt-5.4-mini. Please try again in 2.536s.",
        response=response,
        body={},
    )

    try:
        raise ChatClientException("chat client failed", inner_exception=rate_limit_error) from rate_limit_error
    except ChatClientException as exc:
        translated = _translate_agent_run_error(exc, model="gpt-5.4-mini")

    assert isinstance(translated, TooManyRequestsError)
    assert translated.code == "agent_rate_limited"
    assert translated.details["provider"] == "openai"
    assert translated.details["model"] == "gpt-5.4-mini"
    assert translated.details["retry_after_seconds"] == 2.536
