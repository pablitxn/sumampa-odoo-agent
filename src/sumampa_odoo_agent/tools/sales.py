"""Sales demo tools available to the agent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from sumampa_odoo_agent.services.contracts import SalesBridgePort

SalesToolCallable = Callable[..., Awaitable[dict[str, Any]]]


def build_sales_agent_tools(bridge: SalesBridgePort) -> list[Any]:
    return [
        _read_lead_state_tool(bridge),
        _read_reader_output_tool(bridge),
        _read_transcript_tool(bridge),
        _execute_sales_tool(bridge),
        _add_private_note_tool(bridge),
        _send_public_message_tool(bridge),
    ]


def _read_lead_state_tool(bridge: SalesBridgePort) -> SalesToolCallable:
    async def read_lead_state() -> dict[str, Any]:
        """Read the current sales lead, payment, subscription, and follow-up state."""
        return await bridge.read_lead_state()

    return read_lead_state


def _read_reader_output_tool(bridge: SalesBridgePort) -> SalesToolCallable:
    async def read_sales_reader_output(
        name: Annotated[
            str,
            "Reader output name such as account_summary, offer_catalog, or last_odoo_order",
        ],
    ) -> dict[str, Any]:
        """Read a scenario-backed sales data source without mutating state."""
        return await bridge.read_reader_output(name)

    return read_sales_reader_output


def _read_transcript_tool(bridge: SalesBridgePort) -> SalesToolCallable:
    async def read_sales_transcript() -> dict[str, Any]:
        """Read the current conversation transcript for this demo session."""
        return await bridge.read_transcript()

    return read_sales_transcript


def _execute_sales_tool(bridge: SalesBridgePort) -> SalesToolCallable:
    async def execute_sales_tool(
        action: Annotated[
            str,
            (
                "Allowed actions: record_opt_out, request_human_review, set_interest_tags, "
                "update_lead_commercial_state, schedule_followup, disable_followup, "
                "set_contact_role, set_control_state, mark_activation_link_sent, "
                "mark_payment_received"
            ),
        ],
        arguments: Annotated[
            dict[str, Any],
            "Action arguments. Keep writes explicit, small, and grounded in the user message.",
        ],
    ) -> dict[str, Any]:
        """Execute an auditable write-safe sales action against local mock state."""
        return await bridge.execute_sales_tool(action, arguments)

    return execute_sales_tool


def _add_private_note_tool(bridge: SalesBridgePort) -> SalesToolCallable:
    async def add_private_note(
        note: Annotated[str, "Internal Chatwoot-style note for the sales team"],
    ) -> dict[str, Any]:
        """Add a private note to the mock Chatwoot conversation."""
        return await bridge.add_private_note(note)

    return add_private_note


def _send_public_message_tool(bridge: SalesBridgePort) -> SalesToolCallable:
    async def send_public_message(
        text: Annotated[str, "WhatsApp message text that should be sent to the lead"],
    ) -> dict[str, Any]:
        """Capture an outbound WhatsApp-style public message without calling Evolution."""
        return await bridge.send_public_message(text)

    return send_public_message
