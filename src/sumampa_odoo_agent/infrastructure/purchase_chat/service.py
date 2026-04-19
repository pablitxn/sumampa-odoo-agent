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
    PurchaseChatReplyRequest,
    PurchaseChatResponse,
)
from sumampa_odoo_agent.application.use_cases import (
    AnalyzePurchaseInvoiceInput,
    ApplyPurchaseInvoiceHumanReviewInput,
    ConfirmPriceUpdatesInput,
    ConfirmPurchaseInvoiceInput,
    ConfirmStockReceiptInput,
    PurchaseInvoiceActionsUseCase,
    PurchaseInvoiceHumanReviewUseCase,
)
from sumampa_odoo_agent.domain.ports.odoo_port import OdooPort
from sumampa_odoo_agent.domain.ports.purchase_chat_assistant_port import (
    PurchaseChatAssistantPort,
)
from sumampa_odoo_agent.domain.ports.session_store_port import SessionStorePort
from sumampa_odoo_agent.infrastructure.db.session_store import InMemorySessionStore

PURCHASE_CHAT_SESSION_NAMESPACE = "purchase-chat"


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

    def to_payload(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "stage": self.stage,
            "proposal": self.proposal.model_dump(mode="json") if self.proposal is not None else None,
            "bill_result": self.bill_result.model_dump(mode="json") if self.bill_result is not None else None,
            "stock_result": self.stock_result.model_dump(mode="json") if self.stock_result is not None else None,
            "price_result": self.price_result.model_dump(mode="json") if self.price_result is not None else None,
            "context": self.context.model_dump(mode="json"),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> PurchaseChatSession:
        return cls(
            session_id=str(payload["session_id"]),
            stage=str(payload.get("stage", "awaiting_invoice")),
            proposal=_validate_optional_model(PurchaseInvoiceProposalResult, payload.get("proposal")),
            bill_result=_validate_optional_model(ApplyPurchaseInvoiceProposalResult, payload.get("bill_result")),
            stock_result=_validate_optional_model(ApplyPurchaseInvoiceProposalResult, payload.get("stock_result")),
            price_result=_validate_optional_model(ApplyPurchaseInvoiceProposalResult, payload.get("price_result")),
            context=PurchaseChatContext.model_validate(payload.get("context") or {}),
        )


class PurchaseChatService:
    def __init__(
        self,
        odoo: OdooPort,
        assistant: PurchaseChatAssistantPort,
        invoice_actions: PurchaseInvoiceActionsUseCase | None = None,
        human_review_use_case: PurchaseInvoiceHumanReviewUseCase | None = None,
        session_store: SessionStorePort | None = None,
    ) -> None:
        self._odoo = odoo
        self._assistant = assistant
        self._invoice_actions = invoice_actions or PurchaseInvoiceActionsUseCase(odoo)
        self._human_review_use_case = human_review_use_case or PurchaseInvoiceHumanReviewUseCase(
            self._invoice_actions
        )
        self._session_store = session_store or InMemorySessionStore()

    async def run_turn(self, command: PurchaseChatMessageCommand) -> PurchaseChatResponse:
        session = await self._get_session(command.session_id)
        session.context = _merge_context(session.context, command.context)
        message = command.message.strip()

        if command.attachments:
            proposal = await self._invoice_actions.analyze_purchase_invoice(
                AnalyzePurchaseInvoiceInput(
                    attachments=command.attachments,
                    supplier_name=session.context.supplier_name,
                    supplier_vat=session.context.supplier_vat,
                    markup_percentage=session.context.markup_percentage or 30.0,
                )
            )
            session.proposal = proposal
            session.bill_result = None
            session.stock_result = None
            session.price_result = None
            _sync_context_from_proposal(session)
            stage = (
                "awaiting_resolution"
                if proposal.needs_user_resolution
                else "awaiting_invoice_confirmation"
            )
            return await self._persist_and_return(
                session,
                await self._reply_response(
                    session_id=session.session_id,
                    stage=stage,
                    event=(
                        "analysis_requires_resolution"
                        if proposal.needs_user_resolution
                        else "analysis_ready_for_invoice_confirmation"
                    ),
                    user_message=message,
                    proposal=session.proposal,
                ),
            )

        if session.stage == "awaiting_invoice":
            return await self._persist_and_return(
                session,
                await self._reply_response(
                    session_id=session.session_id,
                    stage="awaiting_invoice",
                    event="awaiting_invoice",
                    user_message=message,
                ),
            )

        if session.proposal is None:
            session.stage = "awaiting_invoice"
            return await self._persist_and_return(
                session,
                await self._reply_response(
                    session_id=session.session_id,
                    stage="awaiting_invoice",
                    event="missing_context",
                    user_message=message,
                ),
            )

        if session.stage == "awaiting_resolution":
            return await self._handle_resolution_turn(session, message)

        decision = await self._assistant.decide(
            stage=session.stage,
            user_message=message,
            proposal=session.proposal,
            last_apply_result=_current_last_apply_result(session),
        )

        if session.stage == "awaiting_invoice_confirmation":
            if decision.action in {"reject_invoice", "reset"}:
                session.stage = "awaiting_invoice"
                session.proposal = None
                return await self._persist_and_return(
                    session,
                    await self._reply_response(
                        session_id=session.session_id,
                        stage="awaiting_invoice",
                        event="invoice_rejected",
                        user_message=message,
                    ),
                )
            if decision.action == "confirm_invoice":
                try:
                    bill_result = await self._invoice_actions.confirm_purchase_invoice(
                        ConfirmPurchaseInvoiceInput(
                            supplier_id=session.context.supplier_id,
                            journal_id=session.context.journal_id,
                            proposal=session.proposal,
                        )
                    )
                except RuntimeError as exc:
                    return await self._persist_and_return(
                        session,
                        await self._reply_response(
                            session_id=session.session_id,
                            stage="awaiting_invoice_confirmation",
                            event="invoice_runtime_error",
                            user_message=message,
                            proposal=session.proposal,
                            details={"error_message": str(exc)},
                        ),
                    )
                if not bill_result.applied:
                    return await self._persist_and_return(
                        session,
                        await self._reply_response(
                            session_id=session.session_id,
                            stage="awaiting_invoice_confirmation",
                            event="invoice_blocked",
                            user_message=message,
                            proposal=session.proposal,
                            last_apply_result=bill_result,
                        ),
                    )
                session.bill_result = bill_result
                return await self._persist_and_return(
                    session,
                    await self._reply_response(
                        session_id=session.session_id,
                        stage=(
                            "awaiting_stock_confirmation"
                            if bool(session.context.create_stock_receipt)
                            else "awaiting_price_confirmation"
                        ),
                        event="invoice_applied",
                        user_message=message,
                        proposal=session.proposal,
                        last_apply_result=bill_result,
                        details={
                            "create_stock_receipt": bool(session.context.create_stock_receipt),
                        },
                    ),
                )
            return await self._persist_and_return(
                session,
                await self._reply_response(
                    session_id=session.session_id,
                    stage="awaiting_invoice_confirmation",
                    event="awaiting_invoice_confirmation",
                    user_message=message,
                    proposal=session.proposal,
                ),
            )

        if session.stage == "awaiting_stock_confirmation":
            if decision.action == "confirm_stock":
                try:
                    stock_result = await self._invoice_actions.confirm_stock_receipt(
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
                    return await self._persist_and_return(
                        session,
                        await self._reply_response(
                            session_id=session.session_id,
                            stage="awaiting_stock_confirmation",
                            event="stock_runtime_error",
                            user_message=message,
                            proposal=session.proposal,
                            last_apply_result=session.bill_result,
                            details={"error_message": str(exc)},
                        ),
                    )
                if not stock_result.applied:
                    return await self._persist_and_return(
                        session,
                        await self._reply_response(
                            session_id=session.session_id,
                            stage="awaiting_stock_confirmation",
                            event="stock_blocked",
                            user_message=message,
                            proposal=session.proposal,
                            last_apply_result=stock_result,
                        ),
                    )
                session.stock_result = stock_result
                return await self._persist_and_return(
                    session,
                    await self._reply_response(
                        session_id=session.session_id,
                        stage="awaiting_price_confirmation",
                        event="stock_applied",
                        user_message=message,
                        proposal=session.proposal,
                        last_apply_result=stock_result,
                    ),
                )
            if decision.action in {"reject_stock", "reset"}:
                return await self._persist_and_return(
                    session,
                    await self._reply_response(
                        session_id=session.session_id,
                        stage="awaiting_price_confirmation",
                        event="stock_rejected",
                        user_message=message,
                        proposal=session.proposal,
                        last_apply_result=session.bill_result,
                    ),
                )
            return await self._persist_and_return(
                session,
                await self._reply_response(
                    session_id=session.session_id,
                    stage="awaiting_stock_confirmation",
                    event="awaiting_stock_confirmation",
                    user_message=message,
                    proposal=session.proposal,
                    last_apply_result=session.bill_result,
                ),
            )

        if session.stage == "awaiting_price_confirmation":
            if decision.action == "confirm_prices":
                try:
                    price_result = await self._invoice_actions.confirm_price_updates(
                        ConfirmPriceUpdatesInput(
                            supplier_id=session.context.supplier_id,
                            journal_id=session.context.journal_id,
                            proposal=session.proposal,
                        )
                    )
                except RuntimeError as exc:
                    return await self._persist_and_return(
                        session,
                        await self._reply_response(
                            session_id=session.session_id,
                            stage="awaiting_price_confirmation",
                            event="price_runtime_error",
                            user_message=message,
                            proposal=session.proposal,
                            last_apply_result=session.bill_result,
                            details={"error_message": str(exc)},
                        ),
                    )
                if not price_result.applied:
                    return await self._persist_and_return(
                        session,
                        await self._reply_response(
                            session_id=session.session_id,
                            stage="awaiting_price_confirmation",
                            event="price_blocked",
                            user_message=message,
                            proposal=session.proposal,
                            last_apply_result=price_result,
                        ),
                    )
                session.price_result = price_result
                return await self._persist_and_return(
                    session,
                    await self._reply_response(
                        session_id=session.session_id,
                        stage="completed",
                        event="price_applied",
                        user_message=message,
                        proposal=session.proposal,
                        last_apply_result=price_result,
                    ),
                )
            if decision.action in {"reject_prices", "reset"}:
                return await self._persist_and_return(
                    session,
                    await self._reply_response(
                        session_id=session.session_id,
                        stage="completed",
                        event="price_rejected",
                        user_message=message,
                        proposal=session.proposal,
                        last_apply_result=session.stock_result or session.bill_result,
                    ),
                )
            return await self._persist_and_return(
                session,
                await self._reply_response(
                    session_id=session.session_id,
                    stage="awaiting_price_confirmation",
                    event="awaiting_price_confirmation",
                    user_message=message,
                    proposal=session.proposal,
                    last_apply_result=session.stock_result or session.bill_result,
                ),
            )

        return await self._persist_and_return(
            session,
            await self._reply_response(
                session_id=session.session_id,
                stage="completed",
                event="completed_existing_flow",
                user_message=message,
                proposal=session.proposal,
                last_apply_result=session.price_result or session.stock_result or session.bill_result,
            ),
        )

    async def _handle_resolution_turn(
        self,
        session: PurchaseChatSession,
        message: str,
    ) -> PurchaseChatResponse:
        proposal = session.proposal
        assert proposal is not None

        decision = await self._assistant.decide(
            stage=session.stage,
            user_message=message,
            proposal=proposal,
            last_apply_result=_current_last_apply_result(session),
        )
        if decision.action == "reset":
            session.stage = "awaiting_invoice"
            session.proposal = None
            return await self._persist_and_return(
                session,
                await self._reply_response(
                    session_id=session.session_id,
                    stage="awaiting_invoice",
                    event="resolution_reset",
                    user_message=message,
                ),
            )
        if decision.action == "review_resolution" and decision.resolution is not None:
            resolution = await self._human_review_use_case.apply(
                ApplyPurchaseInvoiceHumanReviewInput(
                    proposal=proposal,
                    resolution=decision.resolution,
                )
            )
            _sync_context_from_proposal(session)
            if resolution.error_message is not None:
                return await self._persist_and_return(
                    session,
                    await self._reply_response(
                        session_id=session.session_id,
                        stage="awaiting_resolution",
                        event="resolution_error",
                        user_message=message,
                        proposal=proposal,
                        details={"error_message": resolution.error_message},
                    ),
                )
            if resolution.ready_for_confirmation:
                return await self._persist_and_return(
                    session,
                    await self._reply_response(
                        session_id=session.session_id,
                        stage="awaiting_invoice_confirmation",
                        event="resolution_ready_for_invoice_confirmation",
                        user_message=message,
                        proposal=proposal,
                        details={
                            "changed": resolution.changed,
                            "created_summary": resolution.created_summary,
                        },
                    ),
                )
            event = (
                "resolution_blocked"
                if resolution.has_blockers
                else "resolution_updated"
            )
            return await self._persist_and_return(
                session,
                await self._reply_response(
                    session_id=session.session_id,
                    stage="awaiting_resolution",
                    event=event,
                    user_message=message,
                    proposal=proposal,
                    details={
                        "changed": resolution.changed,
                        "created_summary": resolution.created_summary,
                        "has_blockers": resolution.has_blockers,
                    },
                ),
            )
        return await self._persist_and_return(
            session,
            await self._reply_response(
                session_id=session.session_id,
                stage="awaiting_resolution",
                event="awaiting_resolution",
                user_message=message,
                proposal=proposal,
            ),
        )

    async def _get_session(self, session_id: str | None) -> PurchaseChatSession:
        resolved = session_id or str(uuid4())
        payload = await self._session_store.load(
            namespace=PURCHASE_CHAT_SESSION_NAMESPACE,
            session_id=resolved,
        )
        if payload is None:
            return PurchaseChatSession(session_id=resolved)
        return PurchaseChatSession.from_payload(payload)

    async def _persist_and_return(
        self,
        session: PurchaseChatSession,
        response: PurchaseChatResponse,
    ) -> PurchaseChatResponse:
        session.stage = response.stage
        await self._session_store.save(
            namespace=PURCHASE_CHAT_SESSION_NAMESPACE,
            session_id=session.session_id,
            payload=session.to_payload(),
        )
        return response

    async def _reply_response(
        self,
        *,
        session_id: str,
        stage: str,
        event: str,
        user_message: str,
        proposal: PurchaseInvoiceProposalResult | None = None,
        last_apply_result: ApplyPurchaseInvoiceProposalResult | None = None,
        details: dict[str, object] | None = None,
    ) -> PurchaseChatResponse:
        reply_details = _reply_details(
            stage=stage,
            proposal=proposal,
            last_apply_result=last_apply_result,
            explicit_details=details,
        )
        assistant_message = await self._assistant.reply(
            PurchaseChatReplyRequest(
                stage=stage,
                event=event,
                user_message=user_message,
                proposal=proposal,
                last_apply_result=last_apply_result,
                details=reply_details,
            )
        )
        return PurchaseChatResponse(
            session_id=session_id,
            stage=stage,
            assistant_message=assistant_message,
            proposal=proposal,
            last_apply_result=last_apply_result,
        )


def _validate_optional_model(model: type[PurchaseInvoiceProposalResult] | type[ApplyPurchaseInvoiceProposalResult], payload: object) -> PurchaseInvoiceProposalResult | ApplyPurchaseInvoiceProposalResult | None:
    if payload is None:
        return None
    return model.model_validate(payload)


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


def _current_last_apply_result(
    session: PurchaseChatSession,
) -> ApplyPurchaseInvoiceProposalResult | None:
    return session.price_result or session.stock_result or session.bill_result


def _reply_details(
    *,
    stage: str,
    proposal: PurchaseInvoiceProposalResult | None,
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None,
    explicit_details: dict[str, object] | None,
) -> dict[str, object]:
    pending_line_numbers = (
        [
            line.line_number
            for line in proposal.lines
            if line.product_resolution.status not in {"exact", "manual"}
        ]
        if proposal is not None
        else []
    )
    supplier_resolution_status = (
        proposal.supplier_resolution.status
        if proposal is not None and proposal.supplier_resolution is not None
        else None
    )
    details: dict[str, object] = {
        "has_active_proposal": proposal is not None,
        "should_not_request_invoice_again": proposal is not None and stage != "awaiting_invoice",
        "supplier_resolution_status": supplier_resolution_status,
        "pending_line_numbers": pending_line_numbers,
        "pending_line_count": len(pending_line_numbers),
        "odoo_mode": proposal.mode if proposal is not None else None,
        "last_operation_applied": (
            last_apply_result.applied if last_apply_result is not None else None
        ),
    }
    if explicit_details:
        details.update(explicit_details)
    return details
