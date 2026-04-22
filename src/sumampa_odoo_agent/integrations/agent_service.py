"""Agent backends built around Microsoft Agent Framework."""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
from importlib.metadata import version as package_version
from typing import Annotated, Any, cast
from uuid import uuid4

from openai import RateLimitError

from sumampa_odoo_agent.integrations.llm_specs import load_llm_spec
from sumampa_odoo_agent.services.contracts import OdooGateway, SessionStore
from sumampa_odoo_agent.services.errors import TooManyRequestsError, UpstreamServiceError
from sumampa_odoo_agent.services.message_specs import render_message

AGENT_SESSION_NAMESPACE = "agent"
_RATE_LIMIT_RETRY_AFTER_PATTERN = re.compile(
    r"Please try again in (?P<seconds>\d+(?:\.\d+)?)s",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


class DisabledAgentService:
    """Explicit runtime disabled state for the agent module."""

    async def run(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del prompt, context, session_id
        raise RuntimeError(render_message("runtime.json", "agent_module_disabled"))


class MicrosoftAgentFrameworkOpenAIService:
    """Thin wrapper around Microsoft Agent Framework OpenAI chat client."""

    def __init__(
        self,
        *,
        model: str,
        system_prompt: str | None = None,
        system_prompt_spec: str = "agent/system.md",
        api_key_env_var: str,
        odoo: OdooGateway | None = None,
        base_url: str | None = None,
        session_store: SessionStore,
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt or load_llm_spec(system_prompt_spec)
        self._api_key_env_var = api_key_env_var
        self._base_url = base_url
        self._odoo = odoo
        self._session_store = session_store

    async def run(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        OpenAIChatClient = _load_openai_chat_client()
        Agent = _load_agent_type()

        api_key = os.environ.get(self._api_key_env_var)
        if not api_key:
            raise RuntimeError(
                f"Missing API key in environment variable '{self._api_key_env_var}'"
            )

        chat_client = OpenAIChatClient(model=self._model, api_key=api_key, base_url=self._base_url)
        resolved_session_id = session_id or str(uuid4())

        agent: Any = _create_compatible_agent(
            chat_client=chat_client,
            agent_type=Agent,
            name="Sumampa Odoo Agent",
            instructions=self._system_prompt,
            tools=_build_agent_tools(odoo=self._odoo),
            max_function_calls=16,
        )
        if not isinstance(agent, Agent):
            raise RuntimeError("Failed to create Microsoft Agent Framework agent")

        session = await self._load_or_create_session(agent=agent, session_id=resolved_session_id)
        message = _build_agent_message(prompt=prompt, context=context)
        try:
            response = await agent.run(message, session=session)
        except Exception as exc:
            translated_error = _translate_agent_run_error(exc, model=self._model)
            if translated_error is not None:
                raise translated_error from exc
            raise

        await self._session_store.save(
            namespace=AGENT_SESSION_NAMESPACE,
            session_id=session.session_id,
            payload=session.to_dict(),
        )
        return {
            "mode": "microsoft-agent-framework-openai",
            "session_id": resolved_session_id,
            "text": getattr(response, "text", str(response)),
        }

    async def _load_or_create_session(
        self,
        *,
        agent: Any,
        session_id: str,
    ) -> Any:
        AgentSession = _load_agent_session_type()
        payload = await self._session_store.load(
            namespace=AGENT_SESSION_NAMESPACE,
            session_id=session_id,
        )
        if payload is not None:
            return AgentSession.from_dict(payload)
        return agent.create_session(session_id=session_id)


def _load_openai_chat_client() -> type[Any]:
    """Work around current upstream packaging bug around `agent_framework.__version__`."""
    import agent_framework

    _ensure_agent_framework_version(agent_framework)

    from agent_framework.openai import OpenAIChatClient

    return OpenAIChatClient


def _load_agent_type() -> type[Any]:
    from agent_framework._agents import Agent

    return Agent


def _load_agent_session_type() -> type[Any]:
    import agent_framework

    _ensure_agent_framework_version(agent_framework)

    from agent_framework._sessions import AgentSession

    if getattr(agent_framework, "AgentSession", None) is None:
        cast(Any, agent_framework).AgentSession = AgentSession

    return AgentSession


def _ensure_agent_framework_version(agent_framework: Any) -> None:
    if getattr(agent_framework, "__version__", None) is None:
        agent_framework.__version__ = package_version("agent-framework")


def _create_compatible_agent(
    *,
    chat_client: Any,
    agent_type: type[Any],
    name: str,
    instructions: str,
    tools: list[Any],
    max_function_calls: int,
) -> Any:
    kwargs: dict[str, Any] = {
        "name": name,
        "instructions": instructions,
        "tools": tools,
    }
    if _chat_client_accepts_function_invocation_configuration(chat_client):
        if _agent_accepts_function_invocation_configuration(agent_type):
            kwargs["function_invocation_configuration"] = {
                "max_function_calls": max_function_calls,
            }
        else:
            kwargs["function_invocation_configuration"] = None
    return chat_client.as_agent(**kwargs)


def _agent_accepts_function_invocation_configuration(agent_type: type[Any]) -> bool:
    try:
        parameters = inspect.signature(agent_type.__init__).parameters
    except (TypeError, ValueError):
        return False
    return "function_invocation_configuration" in parameters


def _chat_client_accepts_function_invocation_configuration(chat_client: Any) -> bool:
    try:
        parameters = inspect.signature(chat_client.as_agent).parameters
    except (TypeError, ValueError):
        return False
    return "function_invocation_configuration" in parameters


def _tool_names(*, include_odoo: bool) -> list[str]:
    names = ["explain_capabilities"]
    if include_odoo:
        names.extend(
            [
                "create_partner",
                "search_partners",
                "search_products",
                "search_journals",
                "search_taxes",
                "search_picking_types",
                "search_locations",
                "validate_invoice_draft",
                "validate_argentina_invoice_draft",
                "validate_delivery_draft",
                "create_product",
                "create_invoice",
                "create_delivery",
            ]
        )
    return names


def _build_agent_tools(*, odoo: OdooGateway | None) -> list[Any]:
    async def explain_capabilities() -> str:
        """Explain what this Sumampa Odoo agent can currently do."""
        names = ", ".join(_tool_names(include_odoo=odoo is not None))
        return (
            "Puedo explicar la POC y, si el backend Odoo esta habilitado, ejecutar estas tools: "
            f"{names}."
        )

    tools: list[Any] = [explain_capabilities]
    if odoo is None:
        return tools

    async def create_partner(
        name: Annotated[str, "Nombre del partner"],
        vat: Annotated[str | None, "CUIT/CUIL del partner"] = None,
        email: Annotated[str | None, "Email del partner"] = None,
        supplier_rank: Annotated[int, "Rank de proveedor"] = 1,
    ) -> dict[str, Any]:
        """Create a partner in Odoo and return the resulting payload."""
        from sumampa_odoo_agent.services.models.odoo import CreatePartnerCommand

        result = await odoo.create_partner(
            CreatePartnerCommand(
                name=name,
                vat=vat,
                email=email,
                supplier_rank=supplier_rank,
            )
        )
        return result.model_dump()

    async def search_partners(
        query: Annotated[str, "Nombre, email o CUIT parcial del cliente"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search partners in Odoo and return candidate IDs."""
        from sumampa_odoo_agent.services.models.odoo import SearchPartnersQuery

        result = await odoo.search_partners(SearchPartnersQuery(query=query, limit=limit))
        return result.model_dump()

    async def search_products(
        query: Annotated[str, "Nombre o SKU parcial del producto"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search products in Odoo and return candidate IDs."""
        from sumampa_odoo_agent.services.models.odoo import SearchProductsQuery

        result = await odoo.search_products(SearchProductsQuery(query=query, limit=limit))
        return result.model_dump()

    async def search_journals(
        query: Annotated[str, "Nombre o codigo parcial del diario"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search journals in Odoo and return candidate IDs."""
        from sumampa_odoo_agent.services.models.odoo import SearchJournalsQuery

        result = await odoo.search_journals(SearchJournalsQuery(query=query, limit=limit))
        return result.model_dump()

    async def search_taxes(
        query: Annotated[str, "Nombre parcial del impuesto, por ejemplo IVA 21"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search taxes in Odoo and return candidate IDs."""
        from sumampa_odoo_agent.services.models.odoo import SearchTaxesQuery

        result = await odoo.search_taxes(SearchTaxesQuery(query=query, limit=limit))
        return result.model_dump()

    async def search_picking_types(
        query: Annotated[str, "Nombre o codigo parcial del tipo de picking"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search picking types in Odoo and return candidate IDs."""
        from sumampa_odoo_agent.services.models.odoo import SearchPickingTypesQuery

        result = await odoo.search_picking_types(SearchPickingTypesQuery(query=query, limit=limit))
        return result.model_dump()

    async def search_locations(
        query: Annotated[str, "Nombre parcial de la ubicacion"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search stock locations in Odoo and return candidate IDs."""
        from sumampa_odoo_agent.services.models.odoo import SearchLocationsQuery

        result = await odoo.search_locations(SearchLocationsQuery(query=query, limit=limit))
        return result.model_dump()

    async def validate_invoice_draft(
        partner_id: Annotated[int | None, "ID del cliente"] = None,
        journal_id: Annotated[int | None, "ID del diario de ventas"] = None,
        move_type: Annotated[str, "Tipo de comprobante"] = "out_invoice",
        line_count: Annotated[int, "Cantidad de lineas de factura"] = 0,
    ) -> dict[str, Any]:
        """Validate invoice prerequisites before trying to create it."""
        from sumampa_odoo_agent.services.models.odoo import ValidateInvoiceDraftQuery

        result = await odoo.validate_invoice_draft(
            ValidateInvoiceDraftQuery(
                partner_id=partner_id,
                journal_id=journal_id,
                move_type=move_type,
                line_count=line_count,
            )
        )
        return result.model_dump()

    async def validate_argentina_invoice_draft(
        emitter_vat: Annotated[str | None, "CUIT del emisor"] = None,
        emitter_taxpayer_type: Annotated[
            str | None,
            "Responsable inscripto, monotributo, exento, etc.",
        ] = None,
        point_of_sale: Annotated[int | None, "Punto de venta AFIP/ARCA"] = None,
        wsfe_service: Annotated[
            str,
            "Servicio fiscal esperado, normalmente wsfev1",
        ] = "wsfev1",
        document_letter: Annotated[str | None, "Letra del comprobante: A, B o C"] = None,
        partner_name: Annotated[str | None, "Nombre del receptor"] = None,
        partner_vat: Annotated[str | None, "CUIT o identificacion fiscal del receptor"] = None,
        partner_doc_type: Annotated[str | None, "Tipo de documento del receptor"] = None,
        partner_taxpayer_type: Annotated[
            str | None,
            "Condicion fiscal del receptor",
        ] = None,
        line_count: Annotated[int, "Cantidad de lineas de factura"] = 0,
        email_to: Annotated[str | None, "Email para envio del comprobante"] = None,
    ) -> dict[str, Any]:
        """Validate Argentine electronic invoice prerequisites before issuing a document."""
        from sumampa_odoo_agent.services.models.odoo import ValidateArgentinaInvoiceDraftQuery

        result = await odoo.validate_argentina_invoice_draft(
            ValidateArgentinaInvoiceDraftQuery(
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
        )
        return result.model_dump()

    async def validate_delivery_draft(
        partner_id: Annotated[int | None, "ID del cliente"] = None,
        picking_type_id: Annotated[int | None, "ID del tipo de picking"] = None,
        location_id: Annotated[int | None, "ID de ubicacion origen"] = None,
        location_dest_id: Annotated[int | None, "ID de ubicacion destino"] = None,
        move_count: Annotated[int, "Cantidad de movimientos"] = 0,
    ) -> dict[str, Any]:
        """Validate delivery prerequisites before trying to create it."""
        from sumampa_odoo_agent.services.models.odoo import ValidateDeliveryDraftQuery

        result = await odoo.validate_delivery_draft(
            ValidateDeliveryDraftQuery(
                partner_id=partner_id,
                picking_type_id=picking_type_id,
                location_id=location_id,
                location_dest_id=location_dest_id,
                move_count=move_count,
            )
        )
        return result.model_dump()

    async def create_product(
        name: Annotated[str, "Nombre comercial del producto"],
        default_code: Annotated[str | None, "Codigo interno o SKU"] = None,
        list_price: Annotated[float, "Precio de venta"] = 0.0,
        standard_price: Annotated[float | None, "Costo estandar"] = None,
        description_sale: Annotated[str | None, "Descripcion para ventas"] = None,
    ) -> dict[str, Any]:
        """Create a product in Odoo and return the resulting payload."""
        from sumampa_odoo_agent.services.models.odoo import CreateProductCommand

        result = await odoo.create_product(
            CreateProductCommand(
                name=name,
                default_code=default_code,
                list_price=list_price,
                standard_price=standard_price,
                description_sale=description_sale,
            )
        )
        return result.model_dump()

    async def create_invoice(
        partner_id: Annotated[int, "ID del partner o cliente en Odoo"],
        lines: Annotated[
            list[dict[str, Any]],
            "Lineas con product_id, quantity, price_unit y name opcional",
        ],
        move_type: Annotated[str, "Tipo de comprobante, por defecto out_invoice"] = "out_invoice",
        invoice_date: Annotated[str | None, "Fecha ISO de factura"] = None,
        narration: Annotated[str | None, "Notas internas o leyenda"] = None,
    ) -> dict[str, Any]:
        """Create an invoice in Odoo and return the resulting payload."""
        from sumampa_odoo_agent.services.models.odoo import (
            CreateInvoiceCommand,
            InvoiceLineInput,
        )

        result = await odoo.create_invoice(
            CreateInvoiceCommand(
                partner_id=partner_id,
                move_type=move_type,
                invoice_date=invoice_date,
                narration=narration,
                lines=[InvoiceLineInput.model_validate(line) for line in lines],
            )
        )
        return result.model_dump()

    async def create_delivery(
        partner_id: Annotated[int, "ID del partner o cliente en Odoo"],
        picking_type_id: Annotated[int, "Tipo de operacion de stock"],
        location_id: Annotated[int, "Ubicacion origen"],
        location_dest_id: Annotated[int, "Ubicacion destino"],
        moves: Annotated[
            list[dict[str, Any]],
            "Movimientos con product_id, quantity y name opcional",
        ],
        origin: Annotated[str | None, "Origen comercial del remito"] = None,
        scheduled_date: Annotated[str | None, "Fecha programada ISO"] = None,
    ) -> dict[str, Any]:
        """Create a delivery order in Odoo and return the resulting payload."""
        from sumampa_odoo_agent.services.models.odoo import (
            CreateDeliveryCommand,
            DeliveryMoveInput,
        )

        result = await odoo.create_delivery(
            CreateDeliveryCommand(
                partner_id=partner_id,
                picking_type_id=picking_type_id,
                location_id=location_id,
                location_dest_id=location_dest_id,
                origin=origin,
                scheduled_date=scheduled_date,
                moves=[DeliveryMoveInput.model_validate(move) for move in moves],
            )
        )
        return result.model_dump()

    tools.extend(
        [
            create_partner,
            search_partners,
            search_products,
            search_journals,
            search_taxes,
            search_picking_types,
            search_locations,
            validate_invoice_draft,
            validate_argentina_invoice_draft,
            validate_delivery_draft,
            create_product,
            create_invoice,
            create_delivery,
        ]
    )
    return tools


def _build_agent_message(
    *,
    prompt: str,
    context: dict[str, Any],
) -> str:
    if not context:
        return prompt
    return (
        f"{prompt}\n\n"
        "Contexto JSON:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2, default=str)}"
    )


def _translate_agent_run_error(
    exc: Exception,
    *,
    model: str,
) -> TooManyRequestsError | UpstreamServiceError | None:
    rate_limit_error = _find_openai_rate_limit_error(exc)
    if rate_limit_error is not None:
        retry_after_seconds = _extract_retry_after_seconds(rate_limit_error)
        details: dict[str, object] = {
            "provider": "openai",
            "model": model,
        }
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds
        return TooManyRequestsError(
            render_message("runtime.json", "agent_rate_limited"),
            code="agent_rate_limited",
            details=details,
        )

    if any(_is_chat_client_exception(error) for error in _exception_chain(exc)):
        return UpstreamServiceError(
            render_message("runtime.json", "agent_upstream_failure"),
            code="agent_upstream_failure",
            details={
                "provider": "openai",
                "model": model,
                "exception_type": exc.__class__.__name__,
            },
        )

    return None


def _is_chat_client_exception(error: BaseException) -> bool:
    try:
        from agent_framework.exceptions import ChatClientException
    except ModuleNotFoundError:  # pragma: no cover
        return error.__class__.__name__ == "ChatClientException"
    return isinstance(error, ChatClientException)


def _find_openai_rate_limit_error(exc: Exception) -> RateLimitError | None:
    for error in _exception_chain(exc):
        if isinstance(error, RateLimitError):
            return error
    return None


def _exception_chain(exc: BaseException) -> list[BaseException]:
    errors: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        errors.append(current)
        current = current.__cause__ or current.__context__
    return errors


def _extract_retry_after_seconds(rate_limit_error: RateLimitError) -> float | None:
    retry_after = getattr(getattr(rate_limit_error, "response", None), "headers", {}).get(
        "retry-after"
    )
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            logger.debug("Ignoring non-numeric retry-after header: %s", retry_after)

    match = _RATE_LIMIT_RETRY_AFTER_PATTERN.search(str(rate_limit_error))
    if match is None:
        return None
    return float(match.group("seconds"))
