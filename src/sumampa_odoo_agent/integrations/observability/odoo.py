"""Odoo gateway observability wrapper."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from sumampa_odoo_agent.services.contracts import OdooGateway
from sumampa_odoo_agent.services.models.odoo import (
    ArgentinaInvoiceValidationInput,
    DeliveryInput,
    DeliveryValidationInput,
    InvoiceInput,
    InvoiceValidationInput,
    OdooOperationResult,
    OdooSearchResult,
    OdooValidationResult,
    PartnerInput,
    ProductInput,
    SearchInput,
)
from sumampa_odoo_agent.services.observability import (
    ObservabilityProvider,
    to_observability_payload,
)

_ResultT = TypeVar("_ResultT", bound=BaseModel)


class ObservedOdooGateway:
    """Trace Odoo gateway calls without changing concrete Odoo clients or agent tools."""

    def __init__(
        self,
        *,
        wrapped: OdooGateway,
        observability: ObservabilityProvider,
        mode: str,
    ) -> None:
        self._wrapped = wrapped
        self._observability = observability
        self._mode = mode

    async def aclose(self) -> None:
        await self._wrapped.aclose()

    async def search_partners(self, query: SearchInput) -> OdooSearchResult:
        return await self._observe(
            "search_partners",
            query,
            lambda: self._wrapped.search_partners(query),
        )

    async def search_products(self, query: SearchInput) -> OdooSearchResult:
        return await self._observe(
            "search_products",
            query,
            lambda: self._wrapped.search_products(query),
        )

    async def search_journals(self, query: SearchInput) -> OdooSearchResult:
        return await self._observe(
            "search_journals",
            query,
            lambda: self._wrapped.search_journals(query),
        )

    async def search_taxes(self, query: SearchInput) -> OdooSearchResult:
        return await self._observe(
            "search_taxes",
            query,
            lambda: self._wrapped.search_taxes(query),
        )

    async def search_picking_types(self, query: SearchInput) -> OdooSearchResult:
        return await self._observe(
            "search_picking_types",
            query,
            lambda: self._wrapped.search_picking_types(query),
        )

    async def search_locations(self, query: SearchInput) -> OdooSearchResult:
        return await self._observe(
            "search_locations",
            query,
            lambda: self._wrapped.search_locations(query),
        )

    async def validate_invoice_draft(
        self,
        draft: InvoiceValidationInput,
    ) -> OdooValidationResult:
        return await self._observe(
            "validate_invoice_draft",
            draft,
            lambda: self._wrapped.validate_invoice_draft(draft),
        )

    async def validate_argentina_invoice_draft(
        self,
        draft: ArgentinaInvoiceValidationInput,
    ) -> OdooValidationResult:
        return await self._observe(
            "validate_argentina_invoice_draft",
            draft,
            lambda: self._wrapped.validate_argentina_invoice_draft(draft),
        )

    async def validate_delivery_draft(
        self,
        draft: DeliveryValidationInput,
    ) -> OdooValidationResult:
        return await self._observe(
            "validate_delivery_draft",
            draft,
            lambda: self._wrapped.validate_delivery_draft(draft),
        )

    async def create_partner(self, partner: PartnerInput) -> OdooOperationResult:
        return await self._observe(
            "create_partner",
            partner,
            lambda: self._wrapped.create_partner(partner),
        )

    async def create_product(self, product: ProductInput) -> OdooOperationResult:
        return await self._observe(
            "create_product",
            product,
            lambda: self._wrapped.create_product(product),
        )

    async def create_invoice(self, invoice: InvoiceInput) -> OdooOperationResult:
        return await self._observe(
            "create_invoice",
            invoice,
            lambda: self._wrapped.create_invoice(invoice),
        )

    async def create_delivery(self, delivery: DeliveryInput) -> OdooOperationResult:
        return await self._observe(
            "create_delivery",
            delivery,
            lambda: self._wrapped.create_delivery(delivery),
        )

    async def _observe(
        self,
        operation: str,
        input_model: BaseModel,
        call: Callable[[], Awaitable[_ResultT]],
    ) -> _ResultT:
        metadata = {
            "provider": "odoo",
            "operation": operation,
            "odoo.mode": self._mode,
        }
        with self._observability.start_observation(
            name=f"odoo.{operation}",
            as_type="tool",
            input=input_model,
            metadata=metadata,
        ) as observation:
            try:
                result = await call()
            except Exception as exc:
                observation.update(
                    level="ERROR",
                    status_message=f"{exc.__class__.__name__}: {exc}",
                    metadata=metadata,
                )
                raise
            observation.update(
                output=to_observability_payload(result),
                metadata={
                    **metadata,
                    "result.mode": getattr(result, "mode", None),
                    "result.model": getattr(result, "model", None),
                },
            )
            return result
