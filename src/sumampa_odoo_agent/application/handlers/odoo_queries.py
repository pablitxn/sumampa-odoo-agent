"""Query handlers for Odoo lookups."""

from __future__ import annotations

from sumampa_odoo_agent.application.requests.odoo import (
    OdooSearchResult,
    OdooValidationResult,
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
from sumampa_odoo_agent.domain.ports.odoo_port import OdooPort


class SearchPartnersQueryHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: SearchPartnersQuery) -> OdooSearchResult:
        return await self._odoo.search_partners(request)


class SearchProductsQueryHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: SearchProductsQuery) -> OdooSearchResult:
        return await self._odoo.search_products(request)


class SearchJournalsQueryHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: SearchJournalsQuery) -> OdooSearchResult:
        return await self._odoo.search_journals(request)


class SearchTaxesQueryHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: SearchTaxesQuery) -> OdooSearchResult:
        return await self._odoo.search_taxes(request)


class SearchPickingTypesQueryHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: SearchPickingTypesQuery) -> OdooSearchResult:
        return await self._odoo.search_picking_types(request)


class SearchLocationsQueryHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: SearchLocationsQuery) -> OdooSearchResult:
        return await self._odoo.search_locations(request)


class ValidateInvoiceDraftQueryHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: ValidateInvoiceDraftQuery) -> OdooValidationResult:
        return await self._odoo.validate_invoice_draft(request)


class ValidateArgentinaInvoiceDraftQueryHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: ValidateArgentinaInvoiceDraftQuery) -> OdooValidationResult:
        return await self._odoo.validate_argentina_invoice_draft(request)


class ValidateDeliveryDraftQueryHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: ValidateDeliveryDraftQuery) -> OdooValidationResult:
        return await self._odoo.validate_delivery_draft(request)
