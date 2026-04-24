# sumampa-odoo-agent

Backend FastAPI orientado a un bot de WhatsApp que orquesta flujos operativos sobre Odoo.

## Arquitectura

- `src/sumampa_odoo_agent/api`: surface HTTP.
- `src/sumampa_odoo_agent/services`: orquestación y reglas de negocio.
- `src/sumampa_odoo_agent/integrations`: armado de backends concretos.
- `src/sumampa_odoo_agent/tools`: tools concretas que el agente puede invocar.

La app ya no usa `MCP`, buses internos ni registro dinámico de módulos.
Odoo se opera desde tools internas del agente; no hay una API HTTP directa para mutaciones o lookups.

## Endpoints

- `GET /health`
- `POST /api/v1/messages`

## Desarrollo

```bash
cd ~/repos/sumampa-odoo-agent
uv sync --extra dev
uv run sumampa_odoo_agent --reload
```

## Tests y checks

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src tests
```

## Modos soportados

- Odoo: `dry-run` y `jsonrpc`
- Session store: `memory` y `hybrid`
- Agent runtime: `openai` y `disabled`

## Integración local con Odoo 19

```bash
docker compose -f docker-compose.odoo19.yml up -d
PYTHONPATH=src uv run python scripts/bootstrap_odoo_integration.py
```
