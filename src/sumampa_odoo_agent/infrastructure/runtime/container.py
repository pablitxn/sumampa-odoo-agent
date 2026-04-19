"""Application container wiring handlers to infrastructure adapters."""

from __future__ import annotations

from dataclasses import dataclass

from sumampa_odoo_agent.application.bus import CommandBus, QueryBus
from sumampa_odoo_agent.application.handlers.agent import RunAgentCommandHandler
from sumampa_odoo_agent.application.handlers.odoo import (
    AnalyzePurchaseInvoiceCommandHandler,
    ApplyPurchaseInvoiceProposalCommandHandler,
    CreateDeliveryCommandHandler,
    CreateInvoiceCommandHandler,
    CreatePartnerCommandHandler,
    CreateProductCommandHandler,
)
from sumampa_odoo_agent.application.handlers.odoo_queries import (
    SearchJournalsQueryHandler,
    SearchLocationsQueryHandler,
    SearchPartnersQueryHandler,
    SearchPickingTypesQueryHandler,
    SearchProductsQueryHandler,
    SearchTaxesQueryHandler,
    ValidateArgentinaInvoiceDraftQueryHandler,
    ValidateDeliveryDraftQueryHandler,
    ValidateInvoiceDraftQueryHandler,
)
from sumampa_odoo_agent.application.handlers.purchase_chat import (
    PurchaseChatMessageCommandHandler,
)
from sumampa_odoo_agent.application.requests.agent import RunAgentCommand
from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
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
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatMessageCommand,
)
from sumampa_odoo_agent.domain.ports.invoice_extractor_port import PurchaseInvoiceExtractorPort
from sumampa_odoo_agent.domain.ports.purchase_chat_assistant_port import (
    PurchaseChatAssistantPort,
)
from sumampa_odoo_agent.infrastructure.agent.service import (
    MicrosoftAgentFrameworkOpenAIService,
    StubAgentService,
)
from sumampa_odoo_agent.infrastructure.extraction.service import (
    OpenAIPurchaseInvoiceExtractor,
    StubPurchaseInvoiceExtractor,
)
from sumampa_odoo_agent.infrastructure.odoo.client import DryRunOdooClient, OdooJsonRpcClient
from sumampa_odoo_agent.infrastructure.odoo.resolution_memory import (
    PurchaseResolutionMemoryStore,
)
from sumampa_odoo_agent.infrastructure.purchase_chat.assistant import (
    OpenAIPurchaseChatAssistant,
    StubPurchaseChatAssistant,
)
from sumampa_odoo_agent.infrastructure.purchase_chat.service import PurchaseChatService
from sumampa_odoo_agent.infrastructure.runtime.modules import ModuleMetadata
from sumampa_odoo_agent.infrastructure.runtime.settings import AppSettings


@dataclass(slots=True)
class ApplicationContainer:
    """Dependency graph exposed to API/MCP adapters."""

    settings: AppSettings
    enabled_modules: frozenset[str]
    module_manifest: dict[str, ModuleMetadata]
    command_bus: CommandBus
    query_bus: QueryBus


async def build_container(
    *,
    settings: AppSettings,
    enabled_modules: frozenset[str],
    module_manifest: dict[str, ModuleMetadata],
) -> ApplicationContainer:
    """Build app container from runtime resources + module selection."""

    command_bus = CommandBus()
    query_bus = QueryBus()
    odoo_backend: OdooJsonRpcClient | DryRunOdooClient | None = None
    invoice_extractor: PurchaseInvoiceExtractorPort = StubPurchaseInvoiceExtractor()
    purchase_chat_assistant: PurchaseChatAssistantPort = StubPurchaseChatAssistant()
    resolution_memory = PurchaseResolutionMemoryStore.from_env()

    if settings.invoice_extraction.mode == "openai":
        invoice_extractor = OpenAIPurchaseInvoiceExtractor(
            model=settings.invoice_extraction.model,
            api_key_env_var=settings.invoice_extraction.api_key_env_var,
            base_url=settings.invoice_extraction.base_url,
            max_output_tokens=settings.invoice_extraction.max_output_tokens,
        )
    if settings.purchase_chat.mode == "openai":
        purchase_chat_assistant = OpenAIPurchaseChatAssistant(
            model=settings.purchase_chat.model,
            api_key_env_var=settings.purchase_chat.api_key_env_var,
            base_url=settings.purchase_chat.base_url,
        )

    if "odoo" in enabled_modules:
        if settings.odoo.mode == "jsonrpc":
            odoo_backend = OdooJsonRpcClient(
                base_url=settings.odoo.base_url,
                database=settings.odoo.database,
                username=settings.odoo.username,
                password=settings.odoo.password,
                timeout_seconds=settings.odoo.timeout_seconds,
                invoice_extractor=invoice_extractor,
                resolution_memory=resolution_memory,
            )
        else:
            odoo_backend = DryRunOdooClient(
                invoice_extractor=invoice_extractor,
                resolution_memory=resolution_memory,
            )

        command_bus.register(CreatePartnerCommand, CreatePartnerCommandHandler(odoo_backend))
        command_bus.register(CreateProductCommand, CreateProductCommandHandler(odoo_backend))
        command_bus.register(CreateInvoiceCommand, CreateInvoiceCommandHandler(odoo_backend))
        command_bus.register(CreateDeliveryCommand, CreateDeliveryCommandHandler(odoo_backend))
        command_bus.register(
            AnalyzePurchaseInvoiceCommand,
            AnalyzePurchaseInvoiceCommandHandler(odoo_backend),
        )
        command_bus.register(
            ApplyPurchaseInvoiceProposalCommand,
            ApplyPurchaseInvoiceProposalCommandHandler(odoo_backend),
        )
        command_bus.register(
            PurchaseChatMessageCommand,
            PurchaseChatMessageCommandHandler(
                PurchaseChatService(odoo_backend, purchase_chat_assistant)
            ),
        )
        query_bus.register(SearchPartnersQuery, SearchPartnersQueryHandler(odoo_backend))
        query_bus.register(SearchProductsQuery, SearchProductsQueryHandler(odoo_backend))
        query_bus.register(SearchJournalsQuery, SearchJournalsQueryHandler(odoo_backend))
        query_bus.register(SearchTaxesQuery, SearchTaxesQueryHandler(odoo_backend))
        query_bus.register(SearchPickingTypesQuery, SearchPickingTypesQueryHandler(odoo_backend))
        query_bus.register(SearchLocationsQuery, SearchLocationsQueryHandler(odoo_backend))
        query_bus.register(ValidateInvoiceDraftQuery, ValidateInvoiceDraftQueryHandler(odoo_backend))
        query_bus.register(
            ValidateArgentinaInvoiceDraftQuery,
            ValidateArgentinaInvoiceDraftQueryHandler(odoo_backend),
        )
        query_bus.register(ValidateDeliveryDraftQuery, ValidateDeliveryDraftQueryHandler(odoo_backend))

    if "agent" in enabled_modules:
        if settings.agent.mode == "openai":
            agent_backend = MicrosoftAgentFrameworkOpenAIService(
                model=settings.agent.model,
                system_prompt=settings.agent.system_prompt,
                api_key_env_var=settings.agent.api_key_env_var,
                odoo=odoo_backend,
                base_url=settings.agent.base_url,
            )
        else:
            agent_backend = StubAgentService(odoo=odoo_backend)
        command_bus.register(RunAgentCommand, RunAgentCommandHandler(agent_backend))

    return ApplicationContainer(
        settings=settings,
        enabled_modules=enabled_modules,
        module_manifest=module_manifest,
        command_bus=command_bus,
        query_bus=query_bus,
    )
