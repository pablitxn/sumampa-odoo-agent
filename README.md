# sumampa-odoo-agent

FastAPI backend for a WhatsApp bot that orchestrates operational workflows on Odoo.

## Architecture

- `src/sumampa_odoo_agent/api`: surface HTTP.
- `src/sumampa_odoo_agent/services`: orchestration and business rules.
- `src/sumampa_odoo_agent/integrations`: concrete backend assembly.
- `src/sumampa_odoo_agent/tools`: concrete tools the agent can invoke.

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

## Local Phoenix Observability

Phoenix is the local source of truth for traces, datasets, experiments, and
annotations. Harbor is the benchmark harness for full-stack runs. The longer
operational guide lives in
[`docs/phoenix-harbor-evals-guide.md`](docs/phoenix-harbor-evals-guide.md).

### Local Prerequisites

```bash
uv sync --extra dev
docker info
```

Harbor is only needed for the full-stack benchmark harness:

```bash
uv tool install harbor
harbor --help
```

### Local Environment

For local Phoenix smoke tests, make sure `.env` contains these values. A local
Phoenix instance does not require `PHOENIX_API_KEY`; leave it empty unless your
Phoenix deployment has auth enabled.

```bash
PYTHON_ENV=local
OPENAI_API_KEY=replace-with-real-key
AGENT_MODE=openai

OBSERVABILITY_MODE=phoenix
PHOENIX_BASE_URL=http://localhost:6006
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
PHOENIX_PROJECT_NAME=sumampa-odoo-agent
PHOENIX_API_KEY_ENV_VAR=PHOENIX_API_KEY
PHOENIX_API_KEY=

SESSION_STORE_MODE=memory
ATTACHMENT_STORE_MODE=memory
ODOO_MODE=dry-run
ODOO_BASE_URL=http://127.0.0.1:8069
ODOO_DATABASE=sumampa_integration
ODOO_USERNAME=admin
ODOO_PASSWORD="${ODOO_PASSWORD:?Set private credentials}"
ODOO_MASTER_PASSWORD="${ODOO_MASTER_PASSWORD:?Set private credentials}"
```

To check a local `.env` without printing secrets:

```bash
awk -F= '
BEGIN {
  split("PYTHON_ENV OPENAI_API_KEY OBSERVABILITY_MODE PHOENIX_BASE_URL PHOENIX_COLLECTOR_ENDPOINT PHOENIX_PROJECT_NAME PHOENIX_API_KEY_ENV_VAR ODOO_MODE ODOO_BASE_URL ODOO_DATABASE ODOO_USERNAME ODOO_PASSWORD", req, " ")
}
/^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/ {
  key=$1; gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
  val=$0; sub(/^[^=]*=/, "", val); gsub(/^[[:space:]"'"'"' ]+|[[:space:]"'"'"' ]+$/, "", val)
  vars[key]=val
}
END {
  for (i in req) {
    key=req[i]
    if (!(key in vars)) status="MISSING"
    else if (vars[key] == "" || vars[key] == "replace-me" || vars[key] == "replace-with-real-key") status="EMPTY_OR_PLACEHOLDER"
    else status="SET"
    print key "=" status
  }
  if ((!("PHOENIX_API_KEY" in vars)) || vars["PHOENIX_API_KEY"] == "") print "PHOENIX_API_KEY=EMPTY_OK_FOR_LOCAL"
  else print "PHOENIX_API_KEY=SET"
}' .env
```

### Phoenix Trace Smoke Test

Run Phoenix locally with the observability compose profile:

```bash
docker compose --profile observability up -d phoenix
```

Open `http://localhost:6006`, then run the app:

```bash
uv run sumampa_odoo_agent --reload
```

Send a smoke message:

```bash
curl -sS http://127.0.0.1:8000/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "phoenix-smoke-1",
    "channel": "whatsapp",
    "user_id": "local-user",
    "text": "Hola, necesito buscar un proveedor en Odoo.",
    "attachments": [],
    "context": {},
    "eval_tags": ["eval:candidate"]
  }' | jq
```

The app records one `conversation.turn` trace per `/api/v1/messages` request, grouped by
Phoenix session using `conversation_id`. Agent, attachment, session-store, and Odoo calls
are child observations. Text, tool inputs/results, and attachment manifests are captured;
raw binary attachment bytes are replaced with size and SHA-256 metadata.

In Phoenix, select project `sumampa-odoo-agent` and look for:

- `conversation.turn`
- `agent.run`
- `attachments.prepare`
- `agent.session.load`
- `agent.session.save`
- `odoo.*` spans when the request reaches Odoo tools

The static demo's `Eval tags` panel sends tag changes to
`/api/v1/conversation-tags`. Those tag-update traces include a safe
`context.transcript` snapshot, so conversations marked after the fact can still
be exported from Phoenix even when the local app uses `SESSION_STORE_MODE=memory`.

### Phoenix Datasets And Evals

Bootstrap eval assets:

```bash
PYTHONPATH=src uv run python scripts/bootstrap_phoenix_evals.py
```

Promote reviewed traces into datasets:

```bash
PYTHONPATH=src uv run python scripts/curate_phoenix_datasets.py \
  sumampa/dev/regression-failures --tag eval:candidate
```

Export tagged conversation transcripts with optional Postgres session enrichment:

```bash
PYTHONPATH=src uv run python scripts/export_tagged_conversations.py \
  --tag eval:candidate --json-array
```

Run evals against a Phoenix dataset with dry-run Odoo and isolated in-memory sessions:

```bash
PYTHONPATH=src uv run python scripts/run_phoenix_evals.py sumampa/dev/odoo-ops
```

Set `OPENAI_EVAL_MODEL` or pass `--llm-judge-model` to add the optional LLM rubric judge
on top of deterministic checks.

### Local Odoo JSON-RPC Smoke Test

Use this when you want the app to talk to the local Odoo 19 sidecar instead of
the dry-run gateway:

```bash
docker compose --profile odoo --profile observability up -d phoenix odoo19
PYTHONPATH=src uv run python scripts/bootstrap_odoo_integration.py
```

Then run the app with JSON-RPC Odoo settings:

```bash
ODOO_MODE=jsonrpc \
ODOO_BASE_URL=http://127.0.0.1:8069 \
ODOO_DATABASE=sumampa_integration \
ODOO_USERNAME=admin \
ODOO_PASSWORD="${ODOO_PASSWORD:?Set private credentials}" \
OBSERVABILITY_MODE=phoenix \
PHOENIX_BASE_URL=http://localhost:6006 \
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces \
PHOENIX_PROJECT_NAME=sumampa-odoo-agent \
uv run sumampa_odoo_agent --reload
```

### Harbor Full-Stack Benchmark

Run the local Harbor full-stack benchmark harness:

```bash
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py
```

The Harbor task under `benchmarks/harbor/sumampa-odoo-fullstack` starts the app, Odoo 19,
and Odoo Postgres as Docker sidecars, calls `/api/v1/messages`, writes
`/logs/verifier/reward.json`, and imports numeric rewards into Phoenix when the matching
conversation span is present. The V1 suite covers seeded supplier/customer/product search,
invoice and delivery validation, Argentina fiscal warnings, safe create, and attachment-assisted
workflows.

Useful variants:

```bash
# Run Harbor but do not upload reward annotations to Phoenix.
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py --no-upload-phoenix

# Reuse an already-built image and already-running Phoenix.
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py --skip-build --skip-phoenix

# Apply the nightly reward gate after Harbor finishes.
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py --gate nightly
```

Artifacts are written under `benchmark_runs/harbor/<git-sha>`. The runner also
writes `reward-index.json` when it finds one or more Harbor `reward.json` files.
The shared numeric score contract is `task_success`, `odoo_payload_valid`,
`grounded_in_tool_result`, `missing_data_handled`, `communication_quality`,
`needs_human_review`, `latency_ms`, `error`, and `llm_judge_pass`.

### Readiness Checklist

Before local tests:

- Docker is running.
- `uv sync --extra dev` has completed.
- `.env` has a real `OPENAI_API_KEY`.
- `.env` has `OBSERVABILITY_MODE=phoenix` and the `PHOENIX_*` values above.
- `docker compose --profile observability config --quiet` passes.
- `docker compose --profile observability up -d phoenix` starts Phoenix at
  `http://localhost:6006`.
- `harbor --help` works if running the full-stack benchmark.

Expected local gaps:

- `PHOENIX_API_KEY` may be empty for unauthenticated local Phoenix.
- `PYTHON_ENV=local` is the default local profile and uses human-readable `text`
  logs in PyCharm/stdout.
- `PYTHON_ENV=local_with_production_logs` keeps local Phoenix/Odoo defaults but
  switches stdout back to JSON and enables OTEL logs/metrics toward the local
  collector for Loki/Grafana checks.
- `LOGGING_FORMAT` and `LOGGING_LEVEL` can override either profile when needed;
  leave them unset for normal profile-driven behavior.
- Odoo JSON-RPC tests need the Odoo profile and seeded `sumampa_integration` DB.
- Harbor tests need the Harbor CLI and a real `OPENAI_API_KEY`.

### PyCharm Run/Debug Configurations

Shared PyCharm configurations live under `.run/`. They use the project `uv`
interpreter, load `$PROJECT_DIR$/.env`, and set non-secret local defaults for
Phoenix, Odoo, session storage, and attachments. The shared local configs use
`PYTHON_ENV=local`, which keeps traces production-like through Phoenix while
making console logs readable. To test the local Loki/Grafana log path, change
only `PYTHON_ENV` to `local_with_production_logs`.

Available configs:

- `API local Phoenix dry-run`: run/debug the API with Phoenix traces and Odoo dry-run.
- `API local Odoo JSON-RPC`: run/debug the API against local Odoo 19, with
  in-memory sessions and attachments for fast integration testing.
- `API local full stack`: run/debug the API against Phoenix, Odoo 19, Postgres,
  Redis, and MinIO.
- `Bootstrap Odoo integration`: seed the local `sumampa_integration` database.
- `Reset Odoo integration`: recreate and reseed the local Odoo stack.
- `Bootstrap Phoenix datasets`: create baseline Phoenix datasets.
- `Export dataset-ready conversations`: export `eval:dataset-ready` conversations.
- `Run Phoenix evals odoo ops dry-run`: dry-run the Phoenix experiment script.
- `Run Harbor benchmarks no upload`: run Harbor locally without uploading annotations.

Before using the API configs, start Phoenix:

```bash
docker compose --profile observability up -d phoenix
```

Before using the Odoo JSON-RPC or Odoo bootstrap/reset configs, start Odoo:

```bash
docker compose --profile odoo up -d odoo19
```

For the normal "everything local" workflow, start the full Docker stack first:

```bash
docker compose --profile odoo --profile observability up -d
```

Then run these PyCharm configs in order:

1. `Bootstrap Odoo integration` on the first run, or `Reset Odoo integration`
   only when you want to wipe and recreate the Odoo fixture database.
2. `Bootstrap Phoenix datasets` once per Phoenix database.
3. `API local full stack` while using `demo/index.html`.
4. `Export dataset-ready conversations` whenever you want to back up reviewed
   conversations from Phoenix.

Do not run more than one API config at the same time; they all bind port `8000`.
Harbor is different: `Run Harbor benchmarks no upload` builds/runs an isolated
benchmark environment and should be treated as a later E2E check, not as the API
process used by the demo.

For debugging the API in PyCharm, keep `--reload` off. Uvicorn reload starts a
child process, which makes breakpoints and shutdown behavior noisier. Use the
terminal command with `--reload` only when you want the fast edit/run loop:

```bash
uv run sumampa_odoo_agent --reload
```

If you keep personal Run/Debug configurations instead of the shared `.run/`
ones, make sure:

- `Paths to ".env" files` includes `$PROJECT_DIR$/.env`.
- Working directory is exactly `$PROJECT_DIR$` with no trailing space.
- `Add content roots to PYTHONPATH` and `Add source roots to PYTHONPATH` are enabled.
- `Run with uv run` is enabled.
- `PYTHONUNBUFFERED=1` is set.
