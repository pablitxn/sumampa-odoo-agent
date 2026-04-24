"""Search helpers shared by Odoo gateway implementations."""

from __future__ import annotations

from typing import Any

from sumampa_odoo_agent.services.models.odoo import OdooSearchHit


def filter_hits(
    rows: list[dict[str, Any]],
    *,
    query: str,
    limit: int,
    extra_keys: tuple[str, ...],
) -> list[OdooSearchHit]:
    needle = query.casefold()
    hits: list[OdooSearchHit] = []
    for row in rows:
        searchable = [
            str(row.get("display_name", "")),
            *[str(row.get(key, "")) for key in extra_keys],
        ]
        if not any(needle in value.casefold() for value in searchable):
            continue
        hits.append(
            OdooSearchHit(
                id=int(row["id"]),
                display_name=str(row["display_name"]),
                extra={key: row.get(key) for key in extra_keys},
            )
        )
        if len(hits) >= limit:
            break
    return hits
