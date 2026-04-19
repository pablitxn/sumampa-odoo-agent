"""Port for conversational purchase invoice workflows."""

from __future__ import annotations

from typing import Protocol

from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatMessageCommand,
    PurchaseChatResponse,
)


class PurchaseChatPort(Protocol):
    async def run_turn(self, command: PurchaseChatMessageCommand) -> PurchaseChatResponse:
        """Run one conversational turn for purchase invoice processing."""
