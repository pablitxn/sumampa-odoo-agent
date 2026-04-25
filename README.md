# sumampa-odoo-agent

FastAPI backend for a WhatsApp bot that orchestrates operational workflows on Odoo.

## Architecture

- `src/sumampa_odoo_agent/api`: surface HTTP.
- `src/sumampa_odoo_agent/services`: orchestration and business rules.
- `src/sumampa_odoo_agent/integrations`: concrete backend assembly.
- `src/sumampa_odoo_agent/tools`: concrete tools the agent can invoke.

The app no longer uses `MCP`, internal buses, or dynamic module registration.
Odoo is operated through internal agent tools; there is no direct HTTP API for mutations or lookups.

## Endpoints

- `GET /health`
- `POST /api/v1/messages`

## Development

```bash
cd ~/repos/sumampa-odoo-agent
uv sync --extra dev
uv run sumampa_odoo_agent --reload
```

## Tests And Checks

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src tests
```

## Supported Modes

- Odoo: `dry-run` and `jsonrpc`
- Session store: `memory` and `hybrid`
- Agent runtime: `openai` and `disabled`

## Local Odoo 19 Integration

```bash
docker compose -f docker-compose.odoo19.yml up -d
PYTHONPATH=src uv run python scripts/bootstrap_odoo_integration.py
```
