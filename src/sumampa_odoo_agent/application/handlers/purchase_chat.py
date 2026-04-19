"""Handlers for conversational purchase invoice flows."""

from __future__ import annotations

from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatMessageCommand,
    PurchaseChatResponse,
)
from sumampa_odoo_agent.domain.ports.purchase_chat_port import PurchaseChatPort


class PurchaseChatMessageCommandHandler:
    def __init__(self, service: PurchaseChatPort) -> None:
        self._service = service

    async def handle(self, request: PurchaseChatMessageCommand) -> PurchaseChatResponse:
        return await self._service.run_turn(request)
