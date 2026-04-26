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
- Attachment store: `memory` and S3-compatible MinIO

## Local Odoo 19 Integration

```bash
docker compose --profile odoo up -d odoo19
PYTHONPATH=src uv run python scripts/bootstrap_odoo_integration.py
```

To reset and reseed the Odoo integration database:

```bash
PYTHONPATH=src uv run python scripts/reset_odoo_integration.py
```

## Local Attachment Storage

```bash
docker compose up -d minio minio-init
```

Attachments are stored as originals in MinIO, then normalized before they are sent to the
Agent Framework runtime. PDF and audio normalization expect `pdftotext`, `pdftoppm`, and
`ffmpeg` to be available on the app host.

## Local Operational Observability

Run the local OTel stack alongside Postgres, Redis, and MinIO:

```bash
docker compose --profile odoo --profile observability up -d \
  postgres redis minio minio-init odoo19 otel-collector prometheus loki tempo grafana
```

Then run the app with OTLP export enabled:

```bash
SESSION_STORE_MODE=hybrid \
ODOO_MODE=jsonrpc \
ODOO_BASE_URL=http://127.0.0.1:8069 \
ODOO_DATABASE=sumampa_integration \
ODOO_USERNAME=admin \
ODOO_PASSWORD="${ODOO_PASSWORD:?Set private credentials}" \
TELEMETRY_ENABLED=true \
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4317 \
uv run sumampa_odoo_agent --reload
```

Grafana is available at `http://localhost:3001` with Prometheus, Loki, and Tempo
datasources provisioned. The app emits stable operational metrics under
`service_name="sumampa-odoo-agent"` and traces/logs through the local collector.

## Local Langfuse Observability

Run Langfuse locally with the upstream v3 Docker Compose setup:

```bash
git clone https://github.com/langfuse/langfuse.git ~/repos/langfuse
cd ~/repos/langfuse
docker compose up
```

Open `http://localhost:3000`, create a project, then add the project keys to this repo's
`.env`:

```bash
OBSERVABILITY_MODE=langfuse
LANGFUSE_BASE_URL=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

The app records one `conversation.turn` trace per `/api/v1/messages` request, grouped by
Langfuse session using `conversation_id`. Agent, attachment, session-store, and Odoo calls
are child observations. Text, tool inputs/results, and attachment manifests are captured;
raw binary attachment bytes are replaced with size and SHA-256 metadata.

Bootstrap eval assets:

```bash
PYTHONPATH=src uv run python scripts/bootstrap_langfuse_evals.py
```

Promote reviewed traces into datasets:

```bash
PYTHONPATH=src uv run python scripts/curate_langfuse_datasets.py \
  sumampa/dev/regression-failures --tag eval:candidate
```

Export tagged conversation transcripts with optional Postgres session enrichment:

```bash
PYTHONPATH=src uv run python scripts/export_tagged_conversations.py \
  --tag eval:candidate --json-array
```

Run evals against a Langfuse dataset with dry-run Odoo and isolated in-memory sessions:

```bash
PYTHONPATH=src uv run python scripts/run_evals.py sumampa/dev/odoo-ops
```

Set `OPENAI_EVAL_MODEL` or pass `--llm-judge-model` to add the optional LLM rubric judge
on top of deterministic checks.
