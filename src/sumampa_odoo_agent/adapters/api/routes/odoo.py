"""API routes for Odoo operations."""

from __future__ import annotations

import base64
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from sumampa_odoo_agent.adapters.dependencies import ContainerDep
from sumampa_odoo_agent.application.message_specs import render_message
from sumampa_odoo_agent.application.requests.agent import RunAgentCommand
from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
    ApplyPurchaseInvoiceProposalResult,
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
    InvoiceAttachment,
    OdooOperationResult,
    OdooSearchResult,
    OdooValidationResult,
    PurchaseInvoiceProposalResult,
    SearchJournalsQuery,
    SearchLocationsQuery,
    SearchPartnersQuery,
    SearchPickingTypesQuery,
    SearchProductsQuery,
    SearchTaxesQuery,
    ValidateArgentinaInvoiceDraftQuery,
    ValidateDeliveryDraftQuery,
    ValidateInvoiceDraftQuery,
)
from sumampa_odoo_agent.application.requests.purchase_workflow import (
    PurchaseWorkflowContext,
    PurchaseWorkflowResponse,
)

router = APIRouter(prefix="/api/v1/odoo", tags=["odoo"])


@router.get("/partners/search", response_model=OdooSearchResult)
async def search_partners(
    query: str,
    limit: int = 10,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> OdooSearchResult:
    request = SearchPartnersQuery(query=query, limit=limit)
    return await container.query_bus.dispatch(request)


@router.get("/products/search", response_model=OdooSearchResult)
async def search_products(
    query: str,
    limit: int = 10,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> OdooSearchResult:
    request = SearchProductsQuery(query=query, limit=limit)
    return await container.query_bus.dispatch(request)


@router.get("/journals/search", response_model=OdooSearchResult)
async def search_journals(
    query: str,
    limit: int = 10,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> OdooSearchResult:
    request = SearchJournalsQuery(query=query, limit=limit)
    return await container.query_bus.dispatch(request)


@router.get("/taxes/search", response_model=OdooSearchResult)
async def search_taxes(
    query: str,
    limit: int = 10,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> OdooSearchResult:
    request = SearchTaxesQuery(query=query, limit=limit)
    return await container.query_bus.dispatch(request)


@router.get("/picking-types/search", response_model=OdooSearchResult)
async def search_picking_types(
    query: str,
    limit: int = 10,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> OdooSearchResult:
    request = SearchPickingTypesQuery(query=query, limit=limit)
    return await container.query_bus.dispatch(request)


@router.get("/locations/search", response_model=OdooSearchResult)
async def search_locations(
    query: str,
    limit: int = 10,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> OdooSearchResult:
    request = SearchLocationsQuery(query=query, limit=limit)
    return await container.query_bus.dispatch(request)


@router.get("/invoices/validate", response_model=OdooValidationResult)
async def validate_invoice_draft(
    partner_id: int | None = None,
    journal_id: int | None = None,
    move_type: str = "out_invoice",
    line_count: int = 0,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> OdooValidationResult:
    request = ValidateInvoiceDraftQuery(
        partner_id=partner_id,
        journal_id=journal_id,
        move_type=move_type,
        line_count=line_count,
    )
    return await container.query_bus.dispatch(request)


@router.get("/invoices/validate-argentina", response_model=OdooValidationResult)
async def validate_argentina_invoice_draft(
    emitter_vat: str | None = None,
    emitter_taxpayer_type: str | None = None,
    point_of_sale: int | None = None,
    wsfe_service: str = "wsfev1",
    document_letter: str | None = None,
    partner_name: str | None = None,
    partner_vat: str | None = None,
    partner_doc_type: str | None = None,
    partner_taxpayer_type: str | None = None,
    line_count: int = 0,
    email_to: str | None = None,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> OdooValidationResult:
    request = ValidateArgentinaInvoiceDraftQuery(
        emitter_vat=emitter_vat,
        emitter_taxpayer_type=emitter_taxpayer_type,
        point_of_sale=point_of_sale,
        wsfe_service=wsfe_service,
        document_letter=document_letter,
        partner_name=partner_name,
        partner_vat=partner_vat,
        partner_doc_type=partner_doc_type,
        partner_taxpayer_type=partner_taxpayer_type,
        line_count=line_count,
        email_to=email_to,
    )
    return await container.query_bus.dispatch(request)


@router.get("/deliveries/validate", response_model=OdooValidationResult)
async def validate_delivery_draft(
    partner_id: int | None = None,
    picking_type_id: int | None = None,
    location_id: int | None = None,
    location_dest_id: int | None = None,
    move_count: int = 0,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> OdooValidationResult:
    request = ValidateDeliveryDraftQuery(
        partner_id=partner_id,
        picking_type_id=picking_type_id,
        location_id=location_id,
        location_dest_id=location_dest_id,
        move_count=move_count,
    )
    return await container.query_bus.dispatch(request)


@router.post("/purchase-invoices/proposals", response_model=PurchaseInvoiceProposalResult)
async def analyze_purchase_invoice(
    invoice_images: Annotated[list[UploadFile] | None, File()] = None,
    invoice_image: Annotated[UploadFile | None, File()] = None,
    supplier_name: Annotated[str | None, Form()] = None,
    supplier_vat: Annotated[str | None, Form()] = None,
    markup_percentage: Annotated[float, Form()] = 30.0,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> PurchaseInvoiceProposalResult:
    attachments = await _read_invoice_attachments(
        invoice_images=invoice_images,
        invoice_image=invoice_image,
        required=True,
    )
    request = AnalyzePurchaseInvoiceCommand(
        attachments=attachments,
        supplier_name=supplier_name,
        supplier_vat=supplier_vat,
        markup_percentage=markup_percentage,
    )
    return await container.command_bus.dispatch(request)


@router.post("/purchase-invoices/apply", response_model=ApplyPurchaseInvoiceProposalResult)
async def apply_purchase_invoice_proposal(
    command: ApplyPurchaseInvoiceProposalCommand,
    container: ContainerDep,
) -> ApplyPurchaseInvoiceProposalResult:
    return await container.command_bus.dispatch(command)


@router.post("/purchase-chat/messages", response_model=PurchaseWorkflowResponse)
async def purchase_chat_message(
    message: Annotated[str, Form()] = "",
    session_id: Annotated[str | None, Form()] = None,
    supplier_id: Annotated[int | None, Form()] = None,
    journal_id: Annotated[int | None, Form()] = None,
    picking_type_id: Annotated[int | None, Form()] = None,
    location_id: Annotated[int | None, Form()] = None,
    location_dest_id: Annotated[int | None, Form()] = None,
    create_stock_receipt: Annotated[bool | None, Form()] = None,
    markup_percentage: Annotated[float | None, Form()] = None,
    supplier_name: Annotated[str | None, Form()] = None,
    supplier_vat: Annotated[str | None, Form()] = None,
    invoice_images: Annotated[list[UploadFile] | None, File()] = None,
    invoice_image: Annotated[UploadFile | None, File()] = None,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> PurchaseWorkflowResponse:
    attachments = await _read_invoice_attachments(
        invoice_images=invoice_images,
        invoice_image=invoice_image,
        required=False,
    )
    purchase_context = PurchaseWorkflowContext(
        supplier_id=supplier_id,
        journal_id=journal_id,
        picking_type_id=picking_type_id,
        location_id=location_id,
        location_dest_id=location_dest_id,
        create_stock_receipt=create_stock_receipt,
        markup_percentage=markup_percentage,
        supplier_name=supplier_name,
        supplier_vat=supplier_vat,
    )
    agent_result = await container.command_bus.dispatch(
        RunAgentCommand(
            prompt=_purchase_chat_prompt(message=message, has_attachments=bool(attachments)),
            session_id=session_id,
            context={
                "purchase_workflow": {
                    "context": purchase_context.model_dump(
                        mode="json",
                        exclude_none=True,
                        exclude_defaults=True,
                    ),
                    "attachments": _serialize_invoice_attachments(attachments),
                }
            },
        )
    )
    purchase_flow = agent_result.get("purchase_flow")
    if not isinstance(purchase_flow, dict):
        purchase_flow = {
            "stage": "awaiting_invoice",
            "proposal": None,
            "last_apply_result": None,
        }
    return PurchaseWorkflowResponse(
        session_id=str(agent_result.get("session_id") or session_id or ""),
        stage=str(purchase_flow.get("stage") or "awaiting_invoice"),
        assistant_message=str(agent_result.get("text") or ""),
        proposal=purchase_flow.get("proposal"),
        last_apply_result=purchase_flow.get("last_apply_result"),
    )


@router.post("/partners", response_model=OdooOperationResult)
async def create_partner(
    command: CreatePartnerCommand,
    container: ContainerDep,
) -> OdooOperationResult:
    return await container.command_bus.dispatch(command)


@router.post("/products", response_model=OdooOperationResult)
async def create_product(
    command: CreateProductCommand,
    container: ContainerDep,
) -> OdooOperationResult:
    return await container.command_bus.dispatch(command)


@router.post("/invoices", response_model=OdooOperationResult)
async def create_invoice(
    command: CreateInvoiceCommand,
    container: ContainerDep,
) -> OdooOperationResult:
    return await container.command_bus.dispatch(command)


@router.post("/deliveries", response_model=OdooOperationResult)
async def create_delivery(
    command: CreateDeliveryCommand,
    container: ContainerDep,
) -> OdooOperationResult:
    return await container.command_bus.dispatch(command)


async def _read_invoice_attachments(
    *,
    invoice_images: list[UploadFile] | None,
    invoice_image: UploadFile | None,
    required: bool,
) -> list[InvoiceAttachment]:
    files: list[UploadFile] = []
    if invoice_images:
        files.extend(invoice_images)
    if invoice_image is not None:
        files.append(invoice_image)

    attachments = [
        InvoiceAttachment(
            filename=upload.filename or "factura-compra.jpg",
            content_type=upload.content_type,
            content_bytes=await upload.read(),
        )
        for upload in files
    ]
    if required and not attachments:
        raise HTTPException(
            status_code=422,
            detail=render_message("runtime.json", "invoice_image_required"),
        )
    return attachments


def _serialize_invoice_attachments(
    attachments: list[InvoiceAttachment],
) -> list[dict[str, str | None]]:
    return [
        {
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "content_base64": base64.b64encode(attachment.content_bytes).decode("ascii"),
        }
        for attachment in attachments
    ]


def _purchase_chat_prompt(*, message: str, has_attachments: bool) -> str:
    normalized = message.strip()
    if normalized:
        return normalized
    if has_attachments:
        return "Analizá la factura adjunta y guiame con el siguiente paso."
    return (
        "Seguimos con la factura activa si existe una. "
        "Si no hay una activa, pedí la factura y sólo el contexto mínimo necesario."
    )
