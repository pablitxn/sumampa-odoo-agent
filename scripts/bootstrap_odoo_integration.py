"""Bootstrap local Odoo 19 integration database with retrieval-focused fixtures."""

from __future__ import annotations

import json
import os
import re
import time
import xmlrpc.client
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

DEFAULT_MODULES = ("contacts", "mail", "account", "stock", "purchase")
DEFAULT_BASE_URL = "http://127.0.0.1:8069"
DEFAULT_DATABASE = "sumampa_integration"
DEFAULT_ADMIN_LOGIN = "admin"
DEFAULT_ADMIN_PASSWORD = ""
DEFAULT_MASTER_PASSWORD = ""
REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PRODUCTS_DIR = (
    REPO_ROOT / "tests" / "integration" / "fixtures" / "purchase_invoice_extractions"
)


def _normalize_seed_name(value: str) -> str:
    return " ".join(value.casefold().replace(".", " ").split())


def _generated_default_code(description: str, seen_codes: set[str]) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "-", description.upper()).strip("-") or "ITEM"
    slug = slug[:18].strip("-") or "ITEM"
    base = f"FIX-{slug}"
    candidate = base
    suffix = 1
    while candidate in seen_codes:
        suffix += 1
        candidate = f"{base[:14]}-{suffix}"
    seen_codes.add(candidate)
    return candidate


def _snapshot_seed_products(*, skip_names: set[str] | None = None) -> tuple[dict[str, Any], ...]:
    seen_names = {_normalize_seed_name(product["name"]) for product in BASE_PRODUCTS}
    seen_codes = {str(product["default_code"]) for product in BASE_PRODUCTS}
    skipped_names = {_normalize_seed_name(name) for name in (skip_names or set())}
    products: list[dict[str, Any]] = []
    for path in sorted(SNAPSHOT_PRODUCTS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for line in payload.get("lines", []):
            description = str(line.get("description") or "").strip()
            if not description:
                continue
            normalized_name = _normalize_seed_name(description)
            if normalized_name in seen_names or normalized_name in skipped_names:
                continue
            gross_price = float(line.get("unit_price_gross") or 0.0)
            vat_rate = float(line.get("vat_rate") or 0.0)
            net_price = gross_price / (1 + (vat_rate / 100)) if vat_rate else gross_price
            products.append(
                {
                    "name": description,
                    "default_code": _generated_default_code(description, seen_codes),
                    "list_price": round(gross_price * 1.3, 2),
                    "standard_price": round(net_price, 2),
                }
            )
            seen_names.add(normalized_name)
    return tuple(products)

PARTNERS = (
    {
        "name": "JULIO M PALACIOS",
        "vat": "20179786151",
        "email": "julio.palacios@example.test",
    },
    {
        "name": "JAMBO SA",
        "vat": "30644193078",
        "email": "compras@jambo.test",
    },
    {
        "name": "MOLINOS MARIMBO SAIC",
        "vat": "30537582916",
        "email": "ventas@marimbo.test",
    },
    {
        "name": "SUMAMPA SRL",
        "vat": "30123456789",
        "email": "admin@sumampa.test",
    },
)

BASE_PRODUCTS = (
    {
        "name": "PURE DE TOMATE ARCOR X 520 GR",
        "default_code": "ARCOR-520",
        "list_price": 900.0,
        "standard_price": 620.0,
    },
    {
        "name": "MENTA CRISTAL X 810 GR",
        "default_code": "CRISTAL-810",
        "list_price": 10400.0,
        "standard_price": 7600.0,
    },
    {
        "name": "MERENGADAS FRUT x 88 gr",
        "default_code": "MER-88",
        "list_price": 1100.0,
        "standard_price": 780.0,
    },
    {
        "name": "HOGAREÑAS 7 SEMILLAS x 189 gr",
        "default_code": "HOG-189",
        "list_price": 1150.0,
        "standard_price": 850.0,
    },
    {
        "name": "GRASA VEGETAL PASTEL 20 KG",
        "default_code": "PASTELGRAS-20",
        "list_price": 129000.0,
        "standard_price": 102400.0,
    },
    {
        "name": "54353",
        "default_code": "54353",
        "list_price": 470000.0,
        "standard_price": 434296.05,
    },
    {
        "name": "54602",
        "default_code": "54602",
        "list_price": 240000.0,
        "standard_price": 217535.0,
    },
    {
        "name": "54676",
        "default_code": "54676",
        "list_price": 65000.0,
        "standard_price": 55800.05,
    },
    {
        "name": "HARINA 000 PANIFICABLE 25 KG",
        "default_code": "HAR-0008",
        "list_price": 15000.0,
        "standard_price": 12750.0,
    },
)

SUPPLIERINFO = (
    {
        "partner_name": "JULIO M PALACIOS",
        "product_code": "ARCOR-520",
        "supplier_product_name": "PURE DE TOMATE ARCOR X 520 GR.",
    },
    {
        "partner_name": "JULIO M PALACIOS",
        "product_code": "CRISTAL-810",
        "supplier_product_name": "MENTA CRISTAL X 810 GR.",
    },
    {
        "partner_name": "JAMBO SA",
        "product_code": "PASTELGRAS-20",
        "supplier_product_name": "Grasa Pastelgras x 20 kg",
        "supplier_product_code": "54353",
    },
    {
        "partner_name": "JAMBO SA",
        "product_code": "54602",
        "supplier_product_name": "54602",
        "supplier_product_code": "54602",
    },
    {
        "partner_name": "JAMBO SA",
        "product_code": "54676",
        "supplier_product_name": "54676",
        "supplier_product_code": "54676",
    },
    {
        "partner_name": "MOLINOS MARIMBO SAIC",
        "product_code": "HAR-0008",
        "supplier_product_name": "HARINA 000 COMUN X 25 KGS. - 0008",
    },
)

PRODUCTS = BASE_PRODUCTS + _snapshot_seed_products(
    skip_names={
        str(row["supplier_product_name"])
        for row in SUPPLIERINFO
        if row.get("supplier_product_name")
    }
)


def main() -> int:
    base_url = os.environ.get("ORCHID_ODOO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    database = os.environ.get("ORCHID_ODOO_DATABASE", DEFAULT_DATABASE)
    admin_login = os.environ.get("ORCHID_ODOO_USERNAME", DEFAULT_ADMIN_LOGIN)
    admin_password = os.environ.get("ORCHID_ODOO_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    master_password = os.environ.get("ODOO_MASTER_PASSWORD", DEFAULT_MASTER_PASSWORD)
    timeout_seconds = float(os.environ.get("ORCHID_ODOO_TIMEOUT_SECONDS", "30"))
    modules = tuple(
        module.strip()
        for module in os.environ.get("ODOO_BOOTSTRAP_MODULES", ",".join(DEFAULT_MODULES)).split(",")
        if module.strip()
    )

    wait_for_odoo(base_url=base_url, timeout_seconds=timeout_seconds)
    ensure_database(
        base_url=base_url,
        database=database,
        admin_login=admin_login,
        admin_password=admin_password,
        master_password=master_password,
        timeout_seconds=timeout_seconds,
    )
    uid = authenticate(
        base_url=base_url,
        database=database,
        admin_login=admin_login,
        admin_password=admin_password,
    )
    install_modules(
        base_url=base_url,
        database=database,
        uid=uid,
        password=admin_password,
        modules=modules,
    )
    seed_fixtures(
        base_url=base_url,
        database=database,
        uid=uid,
        password=admin_password,
    )
    print(f"Odoo integration bootstrap listo en {base_url} db={database}")
    return 0


def wait_for_odoo(*, base_url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/web/login", timeout=5.0, follow_redirects=True)
            if response.status_code < 500:
                return
        except Exception as exc:  # pragma: no cover - network bootstrap
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"Odoo no respondió en {base_url!r}: {last_error}")


def ensure_database(
    *,
    base_url: str,
    database: str,
    admin_login: str,
    admin_password: str,
    master_password: str,
    timeout_seconds: float,
) -> None:
    if database in list_databases(base_url):
        return

    response = httpx.post(
        f"{base_url}/web/database/create",
        data={
            "master_pwd": master_password,
            "name": database,
            "login": admin_login,
            "password": admin_password,
            "lang": "es_AR",
            "country_code": "AR",
            "phone": "",
            "demo": False,
        },
        timeout=timeout_seconds,
        follow_redirects=True,
    )
    response.raise_for_status()

    if database not in list_databases(base_url):
        raise RuntimeError(f"No se pudo crear la base {database!r} en Odoo.")


def list_databases(base_url: str) -> list[str]:
    db_proxy = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/db", allow_none=True)
    try:
        result = db_proxy.list()
    except TypeError:
        result = db_proxy.list(True)
    return [str(name) for name in result]


def authenticate(
    *,
    base_url: str,
    database: str,
    admin_login: str,
    admin_password: str,
) -> int:
    common_proxy = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/common", allow_none=True)
    uid = common_proxy.authenticate(database, admin_login, admin_password, {})
    if not isinstance(uid, int) or uid <= 0:
        raise RuntimeError("No se pudo autenticar contra Odoo para bootstrap.")
    return uid


def install_modules(
    *,
    base_url: str,
    database: str,
    uid: int,
    password: str,
    modules: Iterable[str],
) -> None:
    object_proxy = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/object", allow_none=True)
    module_names = list(modules)
    rows = object_proxy.execute_kw(
        database,
        uid,
        password,
        "ir.module.module",
        "search_read",
        [[("name", "in", module_names)]],
        {"fields": ["name", "state"], "limit": len(module_names)},
    )
    install_ids = [int(row["id"]) for row in rows if row.get("state") != "installed"]
    if install_ids:
        object_proxy.execute_kw(
            database,
            uid,
            password,
            "ir.module.module",
            "button_immediate_install",
            [install_ids],
        )


def seed_fixtures(
    *,
    base_url: str,
    database: str,
    uid: int,
    password: str,
) -> None:
    object_proxy = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/object", allow_none=True)

    partner_ids = {
        partner["name"]: upsert_record(
            object_proxy=object_proxy,
            database=database,
            uid=uid,
            password=password,
            model="res.partner",
            domain=[[("vat", "=", partner["vat"])]],
            values=partner,
        )
        for partner in PARTNERS
    }

    product_ids = {
        product["default_code"]: upsert_record(
            object_proxy=object_proxy,
            database=database,
            uid=uid,
            password=password,
            model="product.template",
            domain=[[("default_code", "=", product["default_code"])]],
            values=product,
        )
        for product in PRODUCTS
    }

    for row in SUPPLIERINFO:
        partner_id = partner_ids[row["partner_name"]]
        product_tmpl_id = product_ids[row["product_code"]]
        values = {
            "partner_id": partner_id,
            "product_tmpl_id": product_tmpl_id,
            "product_name": row.get("supplier_product_name"),
            "product_code": row.get("supplier_product_code"),
        }
        upsert_record(
            object_proxy=object_proxy,
            database=database,
            uid=uid,
            password=password,
            model="product.supplierinfo",
            domain=[
                [
                    ("partner_id", "=", partner_id),
                    ("product_tmpl_id", "=", product_tmpl_id),
                ]
            ],
            values=values,
        )


def upsert_record(
    *,
    object_proxy: xmlrpc.client.ServerProxy,
    database: str,
    uid: int,
    password: str,
    model: str,
    domain: list[list[tuple[str, str, Any]]],
    values: dict[str, Any],
) -> int:
    record_ids = object_proxy.execute_kw(
        database,
        uid,
        password,
        model,
        "search",
        domain,
        {"limit": 1},
    )
    if record_ids:
        record_id = int(record_ids[0])
        object_proxy.execute_kw(
            database,
            uid,
            password,
            model,
            "write",
            [[record_id], values],
        )
        return record_id

    record_id = object_proxy.execute_kw(
        database,
        uid,
        password,
        model,
        "create",
        [values],
    )
    return int(record_id)


if __name__ == "__main__":
    raise SystemExit(main())
