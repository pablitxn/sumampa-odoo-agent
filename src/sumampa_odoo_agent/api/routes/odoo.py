"""Internal Odoo routes."""

from __future__ import annotations

from fastapi import APIRouter

from sumampa_odoo_agent.api.dependencies import ServicesDep
from sumampa_odoo_agent.api.schemas import (
    CreateDeliveryMutation,
    CreateInvoiceMutation,
    CreatePartnerMutation,
    CreateProductMutation,
    LookupRequest,
    LookupResponse,
    MutationRequest,
    MutationResponse,
    ValidationRequest,
    ValidationResponse,
)

router = APIRouter(prefix="/api/v1/odoo", tags=["odoo"])


@router.post("/lookups", response_model=LookupResponse)
async def lookup(request: LookupRequest, services: ServicesDep) -> LookupResponse:
    if request.kind == "partners":
        return await services.odoo.search_partners(request)
    if request.kind == "products":
        return await services.odoo.search_products(request)
    if request.kind == "journals":
        return await services.odoo.search_journals(request)
    if request.kind == "taxes":
        return await services.odoo.search_taxes(request)
    if request.kind == "picking_types":
        return await services.odoo.search_picking_types(request)
    return await services.odoo.search_locations(request)


@router.post("/validations", response_model=ValidationResponse)
async def validate(request: ValidationRequest, services: ServicesDep) -> ValidationResponse:
    if request.kind == "invoice":
        return await services.odoo.validate_invoice_draft(request)
    if request.kind == "argentina_invoice":
        return await services.odoo.validate_argentina_invoice_draft(request)
    return await services.odoo.validate_delivery_draft(request)


@router.post("/mutations", response_model=MutationResponse)
async def mutate(request: MutationRequest, services: ServicesDep) -> MutationResponse:
    if isinstance(request, CreatePartnerMutation):
        return await services.odoo.create_partner(request)
    if isinstance(request, CreateProductMutation):
        return await services.odoo.create_product(request)
    if isinstance(request, CreateInvoiceMutation):
        return await services.odoo.create_invoice(request)
    if isinstance(request, CreateDeliveryMutation):
        return await services.odoo.create_delivery(request)
    raise AssertionError("Unhandled mutation kind")
