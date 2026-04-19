"""LLM-backed conversational planner for purchase chat flows."""

from __future__ import annotations

import os

from openai import AsyncOpenAI

from sumampa_odoo_agent.application.requests.purchase_chat import PurchaseChatPlannerDecision


class StubPurchaseChatAssistant:
    async def plan(
        self,
        *,
        stage: str,
        proposal_summary: str | None,
        user_message: str,
    ) -> PurchaseChatPlannerDecision:
        normalized = _normalize_text(user_message)
        if any(token in normalized for token in ("hola", "buenas", "como va", "qué onda", "que onda")):
            return PurchaseChatPlannerDecision(
                intent="greet",
                assistant_message=(
                    "Todo bien. Cuando quieras subime una factura y la revisamos paso a paso antes de tocar Odoo."
                ),
            )
        if stage == "awaiting_invoice_confirmation" and _looks_positive(normalized):
            return PurchaseChatPlannerDecision(
                intent="confirm_invoice",
                assistant_message="Perfecto. Confirmo que querés cargar la factura.",
            )
        if stage == "awaiting_invoice_confirmation" and _looks_negative(normalized):
            return PurchaseChatPlannerDecision(
                intent="reject_invoice",
                assistant_message="Bien, no cargo la factura todavía.",
            )
        if stage == "awaiting_stock_confirmation" and _looks_positive(normalized):
            return PurchaseChatPlannerDecision(
                intent="confirm_stock",
                assistant_message="Perfecto. Avanzo con la recepción de stock.",
            )
        if stage == "awaiting_stock_confirmation" and _looks_negative(normalized):
            return PurchaseChatPlannerDecision(
                intent="reject_stock",
                assistant_message="Listo. Dejo la factura cargada y no genero recepción por ahora.",
            )
        if stage == "awaiting_price_confirmation" and _looks_positive(normalized):
            return PurchaseChatPlannerDecision(
                intent="confirm_prices",
                assistant_message="Perfecto. Avanzo con la actualización de precios.",
            )
        if stage == "awaiting_price_confirmation" and _looks_negative(normalized):
            return PurchaseChatPlannerDecision(
                intent="reject_prices",
                assistant_message="Listo. Dejo la factura cargada y no actualizo precios.",
            )
        return PurchaseChatPlannerDecision(
            intent="other" if stage != "awaiting_invoice" else "await_invoice",
            assistant_message=(
                "Contame qué necesitás y, cuando tengas la factura, adjuntala así la proceso."
                if stage == "awaiting_invoice"
                else "Te sigo. Si querés avanzar, confirmame explícitamente el siguiente paso."
            ),
        )


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


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().replace(",", " ").replace(".", " ").split())


def _looks_positive(normalized: str) -> bool:
    return any(
        token in normalized
        for token in (
            "si",
            "sí",
            "confirmo",
            "confirmar",
            "cargar factura",
            "actualizar precios",
            "dale",
            "ok",
            "mandale",
            "avanza",
        )
    )


def _looks_negative(normalized: str) -> bool:
    return any(
        token in normalized
        for token in ("no", "revisar", "corregir", "todavia no", "todavía no", "por ahora no")
    )
