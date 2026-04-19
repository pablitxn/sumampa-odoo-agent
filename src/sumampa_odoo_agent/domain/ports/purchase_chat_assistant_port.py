"""Port for conversational assistance in purchase chat flows."""

from __future__ import annotations

from typing import Protocol

from sumampa_odoo_agent.application.requests.purchase_chat import PurchaseChatPlannerDecision


class PurchaseChatAssistantPort(Protocol):
    async def plan(
        self,
        *,
        stage: str,
        proposal_summary: str | None,
        user_message: str,
    ) -> PurchaseChatPlannerDecision:
        """Interpret the user turn and craft a natural assistant reply."""
