"""Public API schemas."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from sumampa_odoo_agent.services.models.odoo import (
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
    OdooMutationPlan,
    OdooOperationResult,
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


class AttachmentInput(BaseModel):
    filename: str = Field(min_length=1)
    mime_type: str | None = None
    content_base64: str | None = None
    download_url: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> AttachmentInput:
        if bool(self.content_base64) == bool(self.download_url):
            raise ValueError("provide exactly one of content_base64 or download_url")
        return self


class ConversationMessageRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    text: str = ""
    attachments: list[AttachmentInput] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class ConversationMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    text: str


class WorkflowStateResponse(BaseModel):
    stage: str


class ConversationMessageResponse(BaseModel):
    conversation_id: str
    messages: list[ConversationMessage] = Field(min_length=1)
    workflow_state: WorkflowStateResponse
    operations: list[OdooMutationPlan] | None = None


class PartnersLookupRequest(SearchPartnersQuery):
    kind: Literal["partners"]


class ProductsLookupRequest(SearchProductsQuery):
    kind: Literal["products"]


class JournalsLookupRequest(SearchJournalsQuery):
    kind: Literal["journals"]


class TaxesLookupRequest(SearchTaxesQuery):
    kind: Literal["taxes"]


class PickingTypesLookupRequest(SearchPickingTypesQuery):
    kind: Literal["picking_types"]


class LocationsLookupRequest(SearchLocationsQuery):
    kind: Literal["locations"]


LookupRequest = Annotated[
    PartnersLookupRequest
    | ProductsLookupRequest
    | JournalsLookupRequest
    | TaxesLookupRequest
    | PickingTypesLookupRequest
    | LocationsLookupRequest,
    Field(discriminator="kind"),
]


class InvoiceValidationRequest(ValidateInvoiceDraftQuery):
    kind: Literal["invoice"]


class ArgentinaInvoiceValidationRequest(ValidateArgentinaInvoiceDraftQuery):
    kind: Literal["argentina_invoice"]


class DeliveryValidationRequest(ValidateDeliveryDraftQuery):
    kind: Literal["delivery"]


ValidationRequest = Annotated[
    InvoiceValidationRequest | ArgentinaInvoiceValidationRequest | DeliveryValidationRequest,
    Field(discriminator="kind"),
]


class CreatePartnerMutation(CreatePartnerCommand):
    kind: Literal["create_partner"]


class CreateProductMutation(CreateProductCommand):
    kind: Literal["create_product"]


class CreateInvoiceMutation(CreateInvoiceCommand):
    kind: Literal["create_invoice"]


class CreateDeliveryMutation(CreateDeliveryCommand):
    kind: Literal["create_delivery"]


MutationRequest = Annotated[
    CreatePartnerMutation
    | CreateProductMutation
    | CreateInvoiceMutation
    | CreateDeliveryMutation,
    Field(discriminator="kind"),
]


MutationResponse = OdooOperationResult
LookupResponse = OdooSearchResult
ValidationResponse = OdooValidationResult
