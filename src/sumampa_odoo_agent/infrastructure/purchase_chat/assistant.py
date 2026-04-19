"""LLM-backed conversational planner for purchase chat flows."""

from __future__ import annotations

import os

from openai import AsyncOpenAI

from sumampa_odoo_agent.application.requests.purchase_chat import PurchaseChatPlannerDecision


class OpenAIPurchaseChatAssistant:
    def __init__(
        self,
        *,
        model: str,
        api_key_env_var: str,
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        self._api_key_env_var = api_key_env_var
        self._base_url = base_url
        self._client = client

    async def plan(
        self,
        *,
        stage: str,
        proposal_summary: str | None,
        user_message: str,
    ) -> PurchaseChatPlannerDecision:
        client = self._client or self._build_client()
        response = await client.responses.parse(
            model=self._model,
            text_format=PurchaseChatPlannerDecision,
            text={"verbosity": "low"},
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Sos un asistente conversacional de compras para Odoo y WhatsApp. "
                                "Podés charlar natural, pero no habilitás acciones peligrosas sin confirmación explícita. "
                                "Elegí un intent del schema y redactá assistant_message breve, cálido y operativo en español rioplatense. "
                                "Si el usuario saluda o hace small talk, respondé natural. "
                                "Si la etapa requiere confirmación, sólo devolvé confirm_invoice/confirm_stock/confirm_prices "
                                "cuando la intención sea inequívoca."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"Etapa actual: {stage}\n"
                                f"Resumen propuesta: {proposal_summary or 'sin propuesta activa'}\n"
                                f"Mensaje usuario: {user_message}"
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
                    if isinstance(parsed, PurchaseChatPlannerDecision):
                        return parsed
                    return PurchaseChatPlannerDecision.model_validate(parsed)
        raise RuntimeError("OpenAI no devolvió una decisión parseable para el purchase chat.")

    def _build_client(self) -> AsyncOpenAI:
        api_key = os.environ.get(self._api_key_env_var)
        if not api_key:
            raise RuntimeError(
                f"Missing API key in environment variable '{self._api_key_env_var}'"
            )
        return AsyncOpenAI(api_key=api_key, base_url=self._base_url)
