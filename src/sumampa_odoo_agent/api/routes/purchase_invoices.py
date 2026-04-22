"""Purchase invoice routes."""

from __future__ import annotations

from fastapi import APIRouter

from sumampa_odoo_agent.api.dependencies import ServicesDep
from sumampa_odoo_agent.api.schemas import PurchaseInvoiceAnalyzeRequest
from sumampa_odoo_agent.services.attachments import resolve_invoice_attachment
from sumampa_odoo_agent.services.models.odoo import (
    AnalyzePurchaseInvoiceCommand,
    PurchaseInvoiceProposalResult,
)

router = APIRouter(prefix="/api/v1/purchase-invoices", tags=["purchase_invoices"])


@router.post("/analyze", response_model=PurchaseInvoiceProposalResult)
async def analyze_purchase_invoice(
    request: PurchaseInvoiceAnalyzeRequest,
    services: ServicesDep,
) -> PurchaseInvoiceProposalResult:
    attachments = [
        await resolve_invoice_attachment(
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            content_base64=attachment.content_base64,
            download_url=attachment.download_url,
        )
        for attachment in request.attachments
    ]
    return await services.purchase_invoices.analyze(
        AnalyzePurchaseInvoiceCommand(
            attachments=attachments,
            supplier_name=request.supplier_name,
            supplier_vat=request.supplier_vat,
            markup_percentage=request.markup_percentage,
        )
    )
