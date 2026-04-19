"""LLM-backed conversational assistant for purchase chat flows."""

from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from sumampa_odoo_agent.application.llm_specs import load_llm_spec
from sumampa_odoo_agent.application.requests.odoo import (
    ApplyPurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalResult,
)
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatReply,
    PurchaseChatReplyRequest,
    PurchaseChatTurnDecision,
)


class OpenAIPurchaseChatAssistant:
    def __init__(
        self,
        *,
        model: str,
        api_key_env_var: str,
        base_url: str | None = None,
        decide_system_spec: str = "purchase_chat/decide_system.md",
        reply_system_spec: str = "purchase_chat/reply_system.md",
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        self._api_key_env_var = api_key_env_var
        self._base_url = base_url
        self._decide_system_spec = decide_system_spec
        self._reply_system_spec = reply_system_spec
        self._client = client

    async def decide(
        self,
        *,
        stage: str,
        user_message: str,
        proposal: PurchaseInvoiceProposalResult | None,
        last_apply_result: ApplyPurchaseInvoiceProposalResult | None,
    ) -> PurchaseChatTurnDecision:
        client = self._client or self._build_client()
        response = await client.responses.parse(
            model=self._model,
            text_format=PurchaseChatTurnDecision,
            text={"verbosity": "low"},
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": load_llm_spec(self._decide_system_spec),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": _decision_context_json(
                                stage=stage,
                                user_message=user_message,
                                proposal=proposal,
                                last_apply_result=last_apply_result,
                            ),
                        }
                    ],
                },
            ],
        )
        for output in getattr(response, "output", []):
            if getattr(output, "type", None) != "message":
                continue
            for content in getattr(output, "content", []):
                parsed = getattr(content, "parsed", None)
                if parsed is not None:
                    if isinstance(parsed, PurchaseChatTurnDecision):
                        return parsed
                    return PurchaseChatTurnDecision.model_validate(parsed)
        raise RuntimeError("OpenAI no devolvió una decisión parseable para el purchase chat.")

    async def reply(
        self,
        request: PurchaseChatReplyRequest,
    ) -> str:
        client = self._client or self._build_client()
        response = await client.responses.parse(
            model=self._model,
            text_format=PurchaseChatReply,
            text={"verbosity": "low"},
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": load_llm_spec(self._reply_system_spec),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": request.model_dump_json(exclude_none=True, indent=2),
                        }
                    ],
                },
            ],
        )
        for output in getattr(response, "output", []):
            if getattr(output, "type", None) != "message":
                continue
            for content in getattr(output, "content", []):
                parsed = getattr(content, "parsed", None)
                if parsed is not None:
                    if isinstance(parsed, PurchaseChatReply):
                        return parsed.assistant_message
                    return PurchaseChatReply.model_validate(parsed).assistant_message
        raise RuntimeError("OpenAI no devolvió un reply parseable para el purchase chat.")

    def _build_client(self) -> AsyncOpenAI:
        api_key = os.environ.get(self._api_key_env_var)
        if not api_key:
            raise RuntimeError(
                f"Missing API key in environment variable '{self._api_key_env_var}'"
            )
        return AsyncOpenAI(api_key=api_key, base_url=self._base_url)


def _decision_context_json(
    *,
    stage: str,
    user_message: str,
    proposal: PurchaseInvoiceProposalResult | None,
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None,
) -> str:
    return json.dumps(
        {
            "stage": stage,
            "user_message": user_message,
            "proposal": proposal.model_dump(mode="json") if proposal is not None else None,
            "last_apply_result": (
                last_apply_result.model_dump(mode="json")
                if last_apply_result is not None
                else None
            ),
        },
        ensure_ascii=False,
        indent=2,
    )
