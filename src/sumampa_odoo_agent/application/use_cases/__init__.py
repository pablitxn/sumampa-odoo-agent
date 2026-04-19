"""Application use cases."""

from sumampa_odoo_agent.application.use_cases.purchase_chat_resolution import (
    ApplyPurchaseChatResolutionInput,
    ApplyPurchaseChatResolutionResult,
    PurchaseChatResolutionUseCase,
    looks_positive,
    proposal_has_resolution_blockers,
)
from sumampa_odoo_agent.application.use_cases.purchase_chat_workflow import (
    AnalyzePurchaseInvoiceInput,
    ConfirmPriceUpdatesInput,
    ConfirmPurchaseInvoiceInput,
    ConfirmStockReceiptInput,
    CreateMissingProductInput,
    CreateMissingSupplierInput,
    PurchaseChatWorkflowUseCases,
)
from sumampa_odoo_agent.application.use_cases.purchase_invoice_resolution import (
    ResolvePurchaseInvoiceEntitiesInput,
    ResolvePurchaseInvoiceEntitiesUseCase,
    normalize_invoice_date,
    normalize_partner_row,
    normalize_product_row,
    normalize_text,
    normalize_vat,
    round_money,
)

__all__ = [
    "AnalyzePurchaseInvoiceInput",
    "ApplyPurchaseChatResolutionInput",
    "ApplyPurchaseChatResolutionResult",
    "ConfirmPriceUpdatesInput",
    "ConfirmPurchaseInvoiceInput",
    "ConfirmStockReceiptInput",
    "CreateMissingProductInput",
    "CreateMissingSupplierInput",
    "PurchaseChatResolutionUseCase",
    "PurchaseChatWorkflowUseCases",
    "ResolvePurchaseInvoiceEntitiesInput",
    "ResolvePurchaseInvoiceEntitiesUseCase",
    "looks_positive",
    "normalize_invoice_date",
    "normalize_partner_row",
    "normalize_product_row",
    "normalize_text",
    "normalize_vat",
    "proposal_has_resolution_blockers",
    "round_money",
]
