"""JSON-RPC Odoo gateway."""

from __future__ import annotations

from typing import Any

import httpx

from sumampa_odoo_agent.integrations.odoo.mapping import normalize_odoo_value
from sumampa_odoo_agent.integrations.odoo.payloads import (
    delivery_payload,
    invoice_payload,
)
from sumampa_odoo_agent.integrations.odoo.validation import (
    validate_argentina_invoice_draft,
    validate_delivery_draft,
    validate_invoice_draft,
)
from sumampa_odoo_agent.services.errors import UpstreamServiceError
from sumampa_odoo_agent.services.models.odoo import (
    ArgentinaInvoiceValidationInput,
    DeliveryInput,
    DeliveryValidationInput,
    InvoiceInput,
    InvoiceValidationInput,
    OdooOperationResult,
    OdooSearchHit,
    OdooSearchResult,
    OdooValidationResult,
    PartnerInput,
    ProductInput,
    SearchInput,
)

ODOO_AUTHENTICATION_FAILED_MESSAGE = "No se pudo autenticar contra Odoo."
ODOO_UPSTREAM_FAILURE_MESSAGE = "Odoo no pudo completar la solicitud."
ODOO_INVALID_RESPONSE_MESSAGE = "Odoo devolvio una respuesta invalida."


class OdooJsonRpcClient:
    """Minimal JSON-RPC client for direct Odoo writes."""

    def __init__(
        self,
        *,
        base_url: str,
        database: str,
        username: str,
        password: str,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._database = database
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds
        self._uid: int | None = None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search_partners(self, query: SearchInput) -> OdooSearchResult:
        rows = await self._execute_kw(
            "res.partner",
            "search_read",
            [
                [
                    "|",
                    "|",
                    ("name", "ilike", query.query),
                    ("email", "ilike", query.query),
                    ("vat", "ilike", query.query),
                ]
            ],
            {"fields": ["display_name", "vat", "email"], "limit": query.limit},
        )
        return OdooSearchResult(
            mode="jsonrpc",
            model="res.partner",
            hits=[
                OdooSearchHit(
                    id=int(row["id"]),
                    display_name=str(row["display_name"]),
                    extra={"vat": row.get("vat"), "email": row.get("email")},
                )
                for row in rows
            ],
        )

    async def search_products(self, query: SearchInput) -> OdooSearchResult:
        rows = await self._execute_kw(
            "product.template",
            "search_read",
            [
                [
                    "|",
                    ("name", "ilike", query.query),
                    ("default_code", "ilike", query.query),
                ]
            ],
            {
                "fields": ["display_name", "default_code", "list_price", "standard_price"],
                "limit": query.limit,
            },
        )
        return OdooSearchResult(
            mode="jsonrpc",
            model="product.template",
            hits=[
                OdooSearchHit(
                    id=int(row["id"]),
                    display_name=str(row["display_name"]),
                    extra={
                        "default_code": row.get("default_code"),
                        "list_price": row.get("list_price"),
                        "standard_price": row.get("standard_price"),
                    },
                )
                for row in rows
            ],
        )

    async def search_journals(self, query: SearchInput) -> OdooSearchResult:
        return await self._search_read_hits(
            model="account.journal",
            domain=["|", ("name", "ilike", query.query), ("code", "ilike", query.query)],
            fields=["display_name", "code", "type"],
            limit=query.limit,
        )

    async def search_taxes(self, query: SearchInput) -> OdooSearchResult:
        return await self._search_read_hits(
            model="account.tax",
            domain=[("name", "ilike", query.query)],
            fields=["display_name", "amount", "type_tax_use"],
            limit=query.limit,
        )

    async def search_picking_types(self, query: SearchInput) -> OdooSearchResult:
        return await self._search_read_hits(
            model="stock.picking.type",
            domain=["|", ("name", "ilike", query.query), ("code", "ilike", query.query)],
            fields=["display_name", "code", "warehouse_id"],
            limit=query.limit,
        )

    async def search_locations(self, query: SearchInput) -> OdooSearchResult:
        return await self._search_read_hits(
            model="stock.location",
            domain=[("complete_name", "ilike", query.query)],
            fields=["display_name", "usage"],
            limit=query.limit,
        )

    async def validate_invoice_draft(
        self,
        draft: InvoiceValidationInput,
    ) -> OdooValidationResult:
        return validate_invoice_draft(mode="jsonrpc", draft=draft)

    async def validate_argentina_invoice_draft(
        self,
        draft: ArgentinaInvoiceValidationInput,
    ) -> OdooValidationResult:
        return validate_argentina_invoice_draft(mode="jsonrpc", draft=draft)

    async def validate_delivery_draft(
        self,
        draft: DeliveryValidationInput,
    ) -> OdooValidationResult:
        return validate_delivery_draft(mode="jsonrpc", draft=draft)

    async def create_partner(self, partner: PartnerInput) -> OdooOperationResult:
        payload = partner.model_dump(exclude_none=True)
        record_id = await self._execute_kw("res.partner", "create", [payload])
        return OdooOperationResult(
            mode="jsonrpc",
            model="res.partner",
            record_id=int(record_id),
            payload=payload,
        )

    async def create_product(self, product: ProductInput) -> OdooOperationResult:
        payload = product.model_dump(exclude_none=True)
        record_id = await self._execute_kw("product.template", "create", [payload])
        return OdooOperationResult(
            mode="jsonrpc",
            model="product.template",
            record_id=int(record_id),
            payload=payload,
        )

    async def create_invoice(self, invoice: InvoiceInput) -> OdooOperationResult:
        payload = invoice_payload(invoice)
        record_id = await self._execute_kw("account.move", "create", [payload])
        return OdooOperationResult(
            mode="jsonrpc",
            model="account.move",
            record_id=int(record_id),
            payload=payload,
        )

    async def create_delivery(self, delivery: DeliveryInput) -> OdooOperationResult:
        metadata = await self._product_template_metadata([move.product_id for move in delivery.moves])
        payload = delivery_payload(delivery, metadata=metadata)
        record_id = await self._execute_kw("stock.picking", "create", [payload])
        return OdooOperationResult(
            mode="jsonrpc",
            model="stock.picking",
            record_id=int(record_id),
            payload=payload,
        )

    async def _authenticate(self) -> int:
        if self._uid is not None:
            return self._uid

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "common",
                "method": "login",
                "args": [self._database, self._username, self._password],
            },
            "id": 1,
        }
        body = await self._post_jsonrpc(payload, operation="authenticate")
        if "result" not in body:
            raise _invalid_response_error("authenticate")
        uid = body["result"]
        if not isinstance(uid, int) or uid <= 0:
            raise UpstreamServiceError(
                ODOO_AUTHENTICATION_FAILED_MESSAGE,
                code="odoo_authentication_failed",
                details={"provider": "odoo", "operation": "authenticate"},
            )
        self._uid = uid
        return uid

    async def _execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        uid = await self._authenticate()
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self._database,
                    uid,
                    self._password,
                    model,
                    method,
                    args,
                    kwargs or {},
                ],
            },
            "id": 1,
        }
        body = await self._post_jsonrpc(payload, operation=f"{model}.{method}")
        if "result" not in body:
            raise _invalid_response_error(f"{model}.{method}")
        return body["result"]

    async def _post_jsonrpc(self, payload: dict[str, Any], *, operation: str) -> dict[str, Any]:
        try:
            response = await self._client.post("/jsonrpc", json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise UpstreamServiceError(
                ODOO_UPSTREAM_FAILURE_MESSAGE,
                code="odoo_upstream_failure",
                details={
                    "provider": "odoo",
                    "operation": operation,
                    "exception_type": exc.__class__.__name__,
                },
            ) from exc
        except ValueError as exc:
            raise UpstreamServiceError(
                ODOO_INVALID_RESPONSE_MESSAGE,
                code="odoo_invalid_response",
                details={"provider": "odoo", "operation": operation},
            ) from exc
        if not isinstance(body, dict):
            raise UpstreamServiceError(
                ODOO_INVALID_RESPONSE_MESSAGE,
                code="odoo_invalid_response",
                details={"provider": "odoo", "operation": operation},
            )
        if "error" in body:
            raise UpstreamServiceError(
                ODOO_UPSTREAM_FAILURE_MESSAGE,
                code="odoo_upstream_failure",
                details={
                    "provider": "odoo",
                    "operation": operation,
                    "error": body["error"],
                },
            )
        return body

    async def _search_read_hits(
        self,
        *,
        model: str,
        domain: list[Any],
        fields: list[str],
        limit: int,
    ) -> OdooSearchResult:
        rows = await self._execute_kw(
            model,
            "search_read",
            [domain],
            {"fields": fields, "limit": limit},
        )
        return OdooSearchResult(
            mode="jsonrpc",
            model=model,
            hits=[
                OdooSearchHit(
                    id=int(row["id"]),
                    display_name=str(row.get("display_name") or row.get("name") or row["id"]),
                    extra={
                        key: normalize_odoo_value(row.get(key))
                        for key in fields
                        if key != "display_name"
                    },
                )
                for row in rows
            ],
        )

    async def _product_template_metadata(
        self,
        template_ids: list[int],
    ) -> dict[int, dict[str, int | None]]:
        if not template_ids:
            return {}
        rows = await self._execute_kw(
            "product.template",
            "search_read",
            [[("id", "in", template_ids)]],
            {"fields": ["product_variant_id", "uom_id"], "limit": len(template_ids)},
        )
        metadata: dict[int, dict[str, int | None]] = {}
        for row in rows:
            template_id = int(row["id"])
            product_variant = normalize_odoo_value(row.get("product_variant_id"))
            uom = normalize_odoo_value(row.get("uom_id"))
            metadata[template_id] = {
                "product_variant_id": (
                    int(product_variant["id"])
                    if isinstance(product_variant, dict) and isinstance(product_variant.get("id"), int)
                    else None
                ),
                "uom_id": (
                    int(uom["id"])
                    if isinstance(uom, dict) and isinstance(uom.get("id"), int)
                    else None
                ),
            }
        return metadata


def _invalid_response_error(operation: str) -> UpstreamServiceError:
    return UpstreamServiceError(
        ODOO_INVALID_RESPONSE_MESSAGE,
        code="odoo_invalid_response",
        details={"provider": "odoo", "operation": operation},
    )
