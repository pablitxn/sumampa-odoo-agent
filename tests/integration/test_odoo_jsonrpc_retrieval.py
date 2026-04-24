"""Integration tests for generic Odoo JSON-RPC operations."""

from __future__ import annotations

import pytest

from sumampa_odoo_agent.integrations.odoo_jsonrpc import OdooJsonRpcClient
from sumampa_odoo_agent.services.models.odoo import SearchInput


def _client(*, env: dict[str, str]) -> OdooJsonRpcClient:
    return OdooJsonRpcClient(
        base_url=env["ORCHID_ODOO_BASE_URL"],
        database=env["ORCHID_ODOO_DATABASE"],
        username=env["ORCHID_ODOO_USERNAME"],
        password=env["ORCHID_ODOO_PASSWORD"],
        timeout_seconds=float(env["ORCHID_ODOO_TIMEOUT_SECONDS"]),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jsonrpc_search_partners_finds_seeded_supplier(odoo19_env: dict[str, str]) -> None:
    client = _client(env=odoo19_env)
    try:
        result = await client.search_partners(SearchInput(query="palacios", limit=10))
    finally:
        await client.aclose()

    assert result.mode == "jsonrpc"
    assert any(hit.display_name == "JULIO M PALACIOS" for hit in result.hits)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jsonrpc_search_products_finds_seeded_alias_product(odoo19_env: dict[str, str]) -> None:
    client = _client(env=odoo19_env)
    try:
        result = await client.search_products(SearchInput(query="HAR-0008", limit=10))
    finally:
        await client.aclose()

    assert result.mode == "jsonrpc"
    assert any(hit.extra.get("default_code") == "HAR-0008" for hit in result.hits)
