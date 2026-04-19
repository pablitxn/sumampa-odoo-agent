"""Unit tests for purchase chat workflow use cases."""

from __future__ import annotations

import pytest

from sumampa_odoo_agent.application.requests.odoo import (
    ApplyPurchaseInvoiceProposalResult,
    InvoiceAttachment,
    OdooMutationPlan,
    OdooOperationResult,
    PurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalTotals,
)
from sumampa_odoo_agent.application.use_cases import (
    AnalyzePurchaseInvoiceInput,
    ConfirmPriceUpdatesInput,
    ConfirmPurchaseInvoiceInput,
    ConfirmStockReceiptInput,
    CreateMissingProductInput,
    CreateMissingSupplierInput,
    PurchaseChatWorkflowUseCases,
)


class SpyOdooPort:
    def __init__(self) -> None:
        self.analyze_request = None
        self.apply_request = None
        self.partner_request = None
        self.product_request = None

    async def analyze_purchase_invoice(self, command):
        self.analyze_request = command
        return _sample_proposal()

    async def apply_purchase_invoice_proposal(self, command):
        self.apply_request = command
        return ApplyPurchaseInvoiceProposalResult(
            mode="dry-run",
            applied=True,
            operations=[OdooMutationPlan(action="create", model="account.move")],
        )

    async def create_partner(self, command):
        self.partner_request = command
        return OdooOperationResult(
            mode="dry-run",
            model="res.partner",
            record_id=999,
            payload=command.model_dump(exclude_none=True),
        )

    async def create_product(self, command):
        self.product_request = command
        return OdooOperationResult(
            mode="dry-run",
            model="product.template",
            record_id=555,
            payload=command.model_dump(exclude_none=True),
        )


def _sample_proposal() -> PurchaseInvoiceProposalResult:
    return PurchaseInvoiceProposalResult(
        mode="dry-run",
        supplier_name="Proveedor Demo",
        invoice_number="A-1",
        invoice_date="2026-04-19",
        document_type="Factura A",
        markup_percentage=30.0,
        totals=PurchaseInvoiceProposalTotals(untaxed=100.0, vat=21.0, total=121.0),
    )


@pytest.mark.asyncio
async def test_workflow_use_case_analyzes_invoice_through_port() -> None:
    odoo = SpyOdooPort()
    use_cases = PurchaseChatWorkflowUseCases(odoo)

    result = await use_cases.analyze_purchase_invoice(
        AnalyzePurchaseInvoiceInput(
            attachments=[
                InvoiceAttachment(
                    filename="factura.jpg",
                    content_type="image/jpeg",
                    content_bytes=b"abc",
                )
            ],
            supplier_name="Proveedor Demo",
            supplier_vat="20123456789",
            markup_percentage=25.0,
        )
    )

    assert result.invoice_number == "A-1"
    assert odoo.analyze_request is not None
    assert odoo.analyze_request.attachments[0].filename == "factura.jpg"
    assert odoo.analyze_request.markup_percentage == 25.0


@pytest.mark.asyncio
async def test_workflow_use_case_confirms_invoice_with_bill_flags() -> None:
    odoo = SpyOdooPort()
    use_cases = PurchaseChatWorkflowUseCases(odoo)
    proposal = _sample_proposal()

    await use_cases.confirm_purchase_invoice(
        ConfirmPurchaseInvoiceInput(
            supplier_id=10,
            journal_id=20,
            proposal=proposal,
        )
    )

    assert odoo.apply_request is not None
    assert odoo.apply_request.create_vendor_bill is True
    assert odoo.apply_request.update_products is False
    assert odoo.apply_request.learn_resolutions is True
    assert odoo.apply_request.create_stock_receipt is False


@pytest.mark.asyncio
async def test_workflow_use_case_confirms_stock_with_stock_flags() -> None:
    odoo = SpyOdooPort()
    use_cases = PurchaseChatWorkflowUseCases(odoo)
    proposal = _sample_proposal()

    await use_cases.confirm_stock_receipt(
        ConfirmStockReceiptInput(
            supplier_id=10,
            journal_id=20,
            proposal=proposal,
            picking_type_id=30,
            location_id=40,
            location_dest_id=50,
        )
    )

    assert odoo.apply_request is not None
    assert odoo.apply_request.create_vendor_bill is False
    assert odoo.apply_request.update_products is False
    assert odoo.apply_request.learn_resolutions is False
    assert odoo.apply_request.create_stock_receipt is True
    assert odoo.apply_request.picking_type_id == 30
    assert odoo.apply_request.location_id == 40
    assert odoo.apply_request.location_dest_id == 50


@pytest.mark.asyncio
async def test_workflow_use_case_confirms_prices_with_price_flags() -> None:
    odoo = SpyOdooPort()
    use_cases = PurchaseChatWorkflowUseCases(odoo)
    proposal = _sample_proposal()

    await use_cases.confirm_price_updates(
        ConfirmPriceUpdatesInput(
            supplier_id=10,
            journal_id=20,
            proposal=proposal,
        )
    )

    assert odoo.apply_request is not None
    assert odoo.apply_request.create_vendor_bill is False
    assert odoo.apply_request.update_products is True
    assert odoo.apply_request.learn_resolutions is False
    assert odoo.apply_request.create_stock_receipt is False


@pytest.mark.asyncio
async def test_workflow_use_case_creates_missing_entities() -> None:
    odoo = SpyOdooPort()
    use_cases = PurchaseChatWorkflowUseCases(odoo)

    partner_result = await use_cases.create_missing_supplier(
        CreateMissingSupplierInput(
            name="Proveedor Nuevo",
            vat="30712345678",
        )
    )
    product_result = await use_cases.create_missing_product(
        CreateMissingProductInput(
            name="Producto Nuevo",
            default_code="PROD-NEW",
            list_price=1500.0,
            standard_price=1000.0,
            description_sale="Producto Nuevo",
        )
    )

    assert partner_result.record_id == 999
    assert odoo.partner_request is not None
    assert odoo.partner_request.supplier_rank == 1
    assert product_result.record_id == 555
    assert odoo.product_request is not None
    assert odoo.product_request.standard_price == 1000.0
