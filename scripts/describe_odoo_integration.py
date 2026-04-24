"""Describe seeded local Odoo 19 integration defaults and fixtures."""

from __future__ import annotations

import argparse
import json
import os
import xmlrpc.client
from typing import Any

from bootstrap_odoo_integration import (
    DEFAULT_ADMIN_LOGIN,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_BASE_URL,
    DEFAULT_DATABASE,
    PARTNERS,
    PRODUCTS,
    SUPPLIERINFO,
    authenticate,
    wait_for_odoo,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emitir el resumen en JSON.")
    args = parser.parse_args()

    summary = build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    print("Odoo 19 local listo para pruebas")
    print(f"- URL: {summary['base_url']}")
    print(f"- DB: {summary['database']}")

    defaults = summary["purchase_defaults"]
    print("- Contexto de compras sugerido:")
    print(
        "  "
        f"journal_id={defaults['journal_id']} ({defaults['journal_name']}), "
        f"picking_type_id={defaults['picking_type_id']} ({defaults['picking_type_name']}), "
        f"location_id={defaults['location_id']} ({defaults['location_name']}), "
        f"location_dest_id={defaults['location_dest_id']} ({defaults['location_dest_name']})"
    )
    print("- Queries útiles para la demo/API:")
    print("  journals= purchase | picking-types= incoming | locations= Vendors / Stock")
    print(f"- Partners seedados: {summary['seed_counts']['partners']}")
    for partner in summary["partners"]:
        print(f"  {partner['id']}: {partner['name']} [{partner['vat'] or 'sin CUIT'}]")
    print(f"- Productos seedados: {summary['seed_counts']['products']}")
    for product in summary["products"]:
        print(f"  {product['id']}: {product['default_code']} -> {product['display_name']}")
    print(f"- Supplierinfo seedado: {summary['seed_counts']['supplierinfo']}")
    for alias in summary["supplierinfo"]:
        print(
            "  "
            f"{alias['partner_name']} / {alias['product_label']} -> "
            f"{alias['product_name'] or alias['supplier_product_name']}"
        )
    return 0


def build_summary() -> dict[str, Any]:
    base_url = os.environ.get("ORCHID_ODOO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    database = os.environ.get("ORCHID_ODOO_DATABASE", DEFAULT_DATABASE)
    admin_login = os.environ.get("ORCHID_ODOO_USERNAME", DEFAULT_ADMIN_LOGIN)
    admin_password = os.environ.get("ORCHID_ODOO_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    timeout_seconds = float(os.environ.get("ORCHID_ODOO_TIMEOUT_SECONDS", "30"))

    wait_for_odoo(base_url=base_url, timeout_seconds=timeout_seconds)
    uid = authenticate(
        base_url=base_url,
        database=database,
        admin_login=admin_login,
        admin_password=admin_password,
    )
    object_proxy = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/object", allow_none=True)

    partners = _search_read(
        object_proxy=object_proxy,
        database=database,
        uid=uid,
        password=admin_password,
        model="res.partner",
        domain=[[("vat", "in", [partner["vat"] for partner in PARTNERS if partner.get("vat")])]],
        fields=["display_name", "name", "vat", "email"],
        limit=len(PARTNERS),
    )
    products = _search_read(
        object_proxy=object_proxy,
        database=database,
        uid=uid,
        password=admin_password,
        model="product.template",
        domain=[[("default_code", "in", [product["default_code"] for product in PRODUCTS])]],
        fields=["display_name", "default_code", "list_price", "standard_price"],
        limit=len(PRODUCTS),
    )
    purchase_journal = _search_read(
        object_proxy=object_proxy,
        database=database,
        uid=uid,
        password=admin_password,
        model="account.journal",
        domain=[[("type", "=", "purchase")]],
        fields=["display_name", "name", "code", "type"],
        limit=1,
    )[0]
    incoming_picking = _search_read(
        object_proxy=object_proxy,
        database=database,
        uid=uid,
        password=admin_password,
        model="stock.picking.type",
        domain=[[("code", "=", "incoming")]],
        fields=[
            "display_name",
            "name",
            "code",
            "default_location_src_id",
            "default_location_dest_id",
        ],
        limit=1,
    )[0]
    location_src = _m2o(incoming_picking.get("default_location_src_id"))
    location_dest = _m2o(incoming_picking.get("default_location_dest_id"))

    supplierinfo = _search_read(
        object_proxy=object_proxy,
        database=database,
        uid=uid,
        password=admin_password,
        model="product.supplierinfo",
        domain=[[]],
        fields=["partner_id", "product_tmpl_id", "product_name", "product_code"],
        limit=max(50, len(SUPPLIERINFO) + 10),
    )

    return {
        "base_url": base_url,
        "database": database,
        "purchase_defaults": {
            "journal_id": int(purchase_journal["id"]),
            "journal_name": str(purchase_journal.get("display_name") or purchase_journal.get("name")),
            "picking_type_id": int(incoming_picking["id"]),
            "picking_type_name": str(
                incoming_picking.get("display_name") or incoming_picking.get("name")
            ),
            "location_id": location_src.get("id"),
            "location_name": location_src.get("name"),
            "location_dest_id": location_dest.get("id"),
            "location_dest_name": location_dest.get("name"),
        },
        "seed_counts": {
            "partners": len(partners),
            "products": len(products),
            "supplierinfo": len(supplierinfo),
        },
        "partners": [
            {
                "id": int(row["id"]),
                "name": str(row.get("display_name") or row.get("name") or row["id"]),
                "vat": row.get("vat"),
                "email": row.get("email"),
            }
            for row in partners
        ],
        "products": [
            {
                "id": int(row["id"]),
                "display_name": str(row.get("display_name") or row["id"]),
                "default_code": row.get("default_code"),
                "list_price": float(row.get("list_price") or 0.0),
                "standard_price": float(row.get("standard_price") or 0.0),
            }
            for row in products
        ],
        "supplierinfo": [
            {
                "id": int(row["id"]),
                "partner_name": _m2o(row.get("partner_id")).get("name"),
                "product_label": _m2o(row.get("product_tmpl_id")).get("name"),
                "product_name": row.get("product_name"),
                "supplier_product_name": row.get("product_name"),
                "supplier_product_code": row.get("product_code"),
            }
            for row in supplierinfo
        ],
    }


def _search_read(
    *,
    object_proxy: xmlrpc.client.ServerProxy,
    database: str,
    uid: int,
    password: str,
    model: str,
    domain: list[list[tuple[str, str, Any]]],
    fields: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    return object_proxy.execute_kw(
        database,
        uid,
        password,
        model,
        "search_read",
        domain,
        {"fields": fields, "limit": limit},
    )


def _m2o(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value:
        return {
            "id": int(value[0]),
            "name": str(value[1]) if len(value) > 1 else str(value[0]),
        }
    if isinstance(value, tuple) and value:
        return {
            "id": int(value[0]),
            "name": str(value[1]) if len(value) > 1 else str(value[0]),
        }
    return {}


if __name__ == "__main__":
    raise SystemExit(main())
