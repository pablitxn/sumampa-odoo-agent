"""Conversational purchase invoice workflow service."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from sumampa_odoo_agent.application.requests.odoo import (
    ApplyPurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalResult,
)
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatContext,
    PurchaseChatMessageCommand,
    PurchaseChatResponse,
)
from sumampa_odoo_agent.application.use_cases import (
    AnalyzePurchaseInvoiceInput,
    ApplyPurchaseChatResolutionInput,
    ConfirmPriceUpdatesInput,
    ConfirmPurchaseInvoiceInput,
    ConfirmStockReceiptInput,
    PurchaseChatResolutionUseCase,
    PurchaseChatWorkflowUseCases,
    proposal_summary,
    response_after_invoice_analysis,
    response_after_resolution,
    response_awaiting_invoice,
    response_completed_existing_flow,
    response_invoice_applied,
    response_invoice_blocked,
    response_invoice_rejected,
    response_invoice_runtime_error,
    response_missing_context,
    response_price_applied,
    response_price_blocked,
    response_price_rejected,
    response_price_runtime_error,
    response_stock_applied,
    response_stock_blocked,
    response_stock_rejected,
    response_stock_runtime_error,
)
from sumampa_odoo_agent.domain.ports.odoo_port import OdooPort
from sumampa_odoo_agent.domain.ports.purchase_chat_assistant_port import (
    PurchaseChatAssistantPort,
)


@dataclass(slots=True)
class PurchaseChatSession:
    session_id: str
    stage: str = "awaiting_invoice"
    proposal: PurchaseInvoiceProposalResult | None = None
    bill_result: ApplyPurchaseInvoiceProposalResult | None = None
    stock_result: ApplyPurchaseInvoiceProposalResult | None = None
    price_result: ApplyPurchaseInvoiceProposalResult | None = None
    context: PurchaseChatContext = field(
        default_factory=lambda: PurchaseChatContext(
            create_stock_receipt=False,
            markup_percentage=30.0,
        )
    )


class PurchaseChatService:
    def __init__(
        self,
        odoo: OdooPort,
        assistant: PurchaseChatAssistantPort,
        workflow_use_cases: PurchaseChatWorkflowUseCases | None = None,
        resolution_use_case: PurchaseChatResolutionUseCase | None = None,
    ) -> None:
        self._odoo = odoo
        self._assistant = assistant
        self._workflow_use_cases = workflow_use_cases or PurchaseChatWorkflowUseCases(odoo)
        self._resolution_use_case = resolution_use_case or PurchaseChatResolutionUseCase(
            self._workflow_use_cases
        )
        self._sessions: dict[str, PurchaseChatSession] = {}

    async def run_turn(self, command: PurchaseChatMessageCommand) -> PurchaseChatResponse:
        session = self._get_session(command.session_id)
        session.context = _merge_context(session.context, command.context)
        message = command.message.strip()

        if command.attachments:
            session.proposal = await self._workflow_use_cases.analyze_purchase_invoice(
                AnalyzePurchaseInvoiceInput(
                    attachments=command.attachments,
                    supplier_name=session.context.supplier_name,
                    supplier_vat=session.context.supplier_vat,
                    markup_percentage=session.context.markup_percentage or 30.0,
                )
            )
            session.bill_result = None
            session.stock_result = None
            session.price_result = None
            _sync_context_from_proposal(session)
            response = response_after_invoice_analysis(
                session_id=session.session_id,
                proposal=session.proposal,
            )
            session.stage = response.stage
            return response

        if session.stage == "awaiting_invoice":
            decision = await self._assistant.plan(
                stage=session.stage,
                proposal_summary=None,
                user_message=message,
            )
            return response_awaiting_invoice(
                session_id=session.session_id,
                assistant_message=decision.assistant_message,
            )

        if session.proposal is None:
            session.stage = "awaiting_invoice"
            return response_missing_context(session_id=session.session_id)

        if session.stage == "awaiting_resolution":
            return await self._handle_resolution_turn(session, message)

        decision = await self._assistant.plan(
            stage=session.stage,
            proposal_summary=proposal_summary(session.proposal),
            user_message=message,
        )

        if session.stage == "awaiting_invoice_confirmation":
            if decision.intent in {"reject_invoice", "reset"}:
                session.stage = "awaiting_invoice"
                session.proposal = None
                return response_invoice_rejected(
                    session_id=session.session_id,
                    assistant_message=decision.assistant_message,
                )
            if decision.intent == "confirm_invoice":
                try:
                    bill_result = await self._workflow_use_cases.confirm_purchase_invoice(
                        ConfirmPurchaseInvoiceInput(
                            supplier_id=session.context.supplier_id,
                            journal_id=session.context.journal_id,
                            proposal=session.proposal,
                        )
                    )
                except RuntimeError as exc:
                    return response_invoice_runtime_error(
                        session_id=session.session_id,
                        proposal=session.proposal,
                        exc=exc,
                    )
                if not bill_result.applied:
                    return response_invoice_blocked(
                        session_id=session.session_id,
                        proposal=session.proposal,
                        result=bill_result,
                    )
                session.bill_result = bill_result
                response = response_invoice_applied(
                    session_id=session.session_id,
                    proposal=session.proposal,
                    result=bill_result,
                    assistant_message=decision.assistant_message,
                    create_stock_receipt=bool(session.context.create_stock_receipt),
                )
                session.stage = response.stage
                return response
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_invoice_confirmation",
                assistant_message=decision.assistant_message,
                proposal=session.proposal,
            )

        if session.stage == "awaiting_stock_confirmation":
            if decision.intent == "confirm_stock":
                try:
                    stock_result = await self._workflow_use_cases.confirm_stock_receipt(
                        ConfirmStockReceiptInput(
                            supplier_id=session.context.supplier_id,
                            journal_id=session.context.journal_id,
                            proposal=session.proposal,
                            picking_type_id=session.context.picking_type_id,
                            location_id=session.context.location_id,
                            location_dest_id=session.context.location_dest_id,
                        )
                    )
                except RuntimeError as exc:
                    return response_stock_runtime_error(
                        session_id=session.session_id,
                        proposal=session.proposal,
                        last_apply_result=session.bill_result,
                        exc=exc,
                    )
                if not stock_result.applied:
                    return response_stock_blocked(
                        session_id=session.session_id,
                        proposal=session.proposal,
                        result=stock_result,
                    )
                session.stock_result = stock_result
                response = response_stock_applied(
                    session_id=session.session_id,
                    proposal=session.proposal,
                    result=stock_result,
                    assistant_message=decision.assistant_message,
                )
                session.stage = response.stage
                return response
            if decision.intent in {"reject_stock", "reset"}:
                response = response_stock_rejected(
                    session_id=session.session_id,
                    proposal=session.proposal,
                    assistant_message=decision.assistant_message,
                    last_apply_result=session.bill_result,
                )
                session.stage = response.stage
                return response
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_stock_confirmation",
                assistant_message=decision.assistant_message,
                proposal=session.proposal,
                last_apply_result=session.bill_result,
            )

        if session.stage == "awaiting_price_confirmation":
            if decision.intent == "confirm_prices":
                try:
                    price_result = await self._workflow_use_cases.confirm_price_updates(
                        ConfirmPriceUpdatesInput(
                            supplier_id=session.context.supplier_id,
                            journal_id=session.context.journal_id,
                            proposal=session.proposal,
                        )
                    )
                except RuntimeError as exc:
                    return response_price_runtime_error(
                        session_id=session.session_id,
                        proposal=session.proposal,
                        last_apply_result=session.bill_result,
                        exc=exc,
                    )
                if not price_result.applied:
                    return response_price_blocked(
                        session_id=session.session_id,
                        proposal=session.proposal,
                        result=price_result,
                    )
                session.price_result = price_result
                response = response_price_applied(
                    session_id=session.session_id,
                    proposal=session.proposal,
                    result=price_result,
                    assistant_message=decision.assistant_message,
                )
                session.stage = response.stage
                return response
            if decision.intent in {"reject_prices", "reset"}:
                response = response_price_rejected(
                    session_id=session.session_id,
                    proposal=session.proposal,
                    assistant_message=decision.assistant_message,
                    last_apply_result=session.stock_result or session.bill_result,
                )
                session.stage = response.stage
                return response
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_price_confirmation",
                assistant_message=decision.assistant_message,
                proposal=session.proposal,
                last_apply_result=session.stock_result or session.bill_result,
            )

        return response_completed_existing_flow(
            session_id=session.session_id,
            proposal=session.proposal,
            last_apply_result=session.price_result or session.stock_result or session.bill_result,
        )

    async def _handle_resolution_turn(
        self,
        session: PurchaseChatSession,
        message: str,
    ) -> PurchaseChatResponse:
        proposal = session.proposal
        assert proposal is not None

        resolution = await self._resolution_use_case.apply(
            ApplyPurchaseChatResolutionInput(
                proposal=proposal,
                message=message,
            )
        )
        if resolution.reset_requested:
            session.stage = "awaiting_invoice"
            session.proposal = None
            return response_after_resolution(
                session_id=session.session_id,
                proposal=proposal,
                resolution=resolution,
            )
        _sync_context_from_proposal(session)
        response = response_after_resolution(
            session_id=session.session_id,
            proposal=proposal,
            resolution=resolution,
        )
        session.stage = response.stage
        return response

    def _get_session(self, session_id: str | None) -> PurchaseChatSession:
        resolved = session_id or str(uuid4())
        session = self._sessions.get(resolved)
        if session is None:
            session = PurchaseChatSession(session_id=resolved)
            self._sessions[resolved] = session
        return session
def _merge_context(
    current: PurchaseChatContext,
    incoming: PurchaseChatContext,
) -> PurchaseChatContext:
    merged = current.model_copy(deep=True)
    for field_name in ("supplier_id", "journal_id", "picking_type_id", "location_id", "location_dest_id"):
        value = getattr(incoming, field_name)
        if value is not None:
            setattr(merged, field_name, value)

    if incoming.create_stock_receipt is not None:
        merged.create_stock_receipt = incoming.create_stock_receipt
    if incoming.markup_percentage is not None:
        merged.markup_percentage = incoming.markup_percentage

    if incoming.supplier_name and incoming.supplier_name.strip():
        merged.supplier_name = incoming.supplier_name.strip()
    if incoming.supplier_vat and incoming.supplier_vat.strip():
        merged.supplier_vat = incoming.supplier_vat.strip()
    return merged


def _sync_context_from_proposal(session: PurchaseChatSession) -> None:
    proposal = session.proposal
    if proposal is None or proposal.supplier_resolution is None:
        return
    if session.context.supplier_id is None and proposal.supplier_resolution.selected_partner_id is not None:
        session.context.supplier_id = proposal.supplier_resolution.selected_partner_id
