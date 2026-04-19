"""Port for conversational assistance in purchase chat flows."""

from __future__ import annotations

from typing import Protocol

from sumampa_odoo_agent.application.requests.odoo import (
    ApplyPurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalResult,
)
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatReplyRequest,
    PurchaseChatTurnDecision,
)


class PurchaseChatAssistantPort(Protocol):
    async def decide(
        self,
        *,
        stage: str,
        user_message: str,
        proposal: PurchaseInvoiceProposalResult | None,
        last_apply_result: ApplyPurchaseInvoiceProposalResult | None,
    ) -> PurchaseChatTurnDecision:
        """Interpret the user turn and return the structured action to execute."""

    async def reply(
        self,
        request: PurchaseChatReplyRequest,
    ) -> str:
        """Render the next user-facing message from the structured conversation state."""
