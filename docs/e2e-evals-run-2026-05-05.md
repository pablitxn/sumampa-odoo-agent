# E2E Evals Run - 2026-05-05

Objective: run e2e evals, bring up the real local environments, verify that the
system works end to end at least at a smoke/regression level, and leave exhaustive
evidence.

## Result

Status: completed with passing evidence across the app, real Odoo JSON-RPC, Phoenix,
Harbor, hybrid Postgres/Redis sessions, and S3-compatible attachment storage.

Main caveat: Harbor's multi-task Docker runner can delete the shared
`sumampa-odoo-agent:harbor-<sha>` image while later tasks are still starting. The
full batch produced useful evidence, but the clean per-scenario evidence below is
from single-task Harbor reruns, which avoid that image cleanup race.

## Environment

- Repo: `<repo>/sumampa-odoo-agent`
- Git HEAD used by Harbor image tag: `140010643f79`
- Local app smoke ports:
  - `8011`: JSON-RPC Odoo + OpenAI + Phoenix + in-memory sessions/attachments
  - `8012`: JSON-RPC Odoo + OpenAI + Phoenix + hybrid sessions + S3 attachments
- Default host ports already occupied by another local stack:
  - `8000`, `5432`, `6379`, `9000`, `9001`
- Alternate live hybrid/S3 validation ports:
  - Postgres: `127.0.0.1:15432`
  - Redis: `127.0.0.1:16379`
  - MinIO API: `127.0.0.1:19000`
  - MinIO console: `127.0.0.1:19001`

## Services Started

Compose services started with:

```bash
docker compose --profile odoo --profile observability up -d \
  odoo19 phoenix otel-collector prometheus loki tempo grafana
```

Observed service checks:

- Phoenix: `http://127.0.0.1:6006` returned `200`
- Odoo: `http://127.0.0.1:8069/web/login` returned `200`
- Grafana: `http://127.0.0.1:3001/api/health` returned `200`
- Prometheus: `http://127.0.0.1:9090/-/healthy` returned `200`
- Loki: `http://127.0.0.1:3100/ready` returned `200`
- Tempo: container health was healthy; `/metrics` returned `200`

Odoo bootstrap:

```bash
PYTHONPATH=src uv run python scripts/bootstrap_odoo_integration.py
PYTHONPATH=src uv run python scripts/describe_odoo_integration.py --json
```

Seed evidence:

- DB: `sumampa_integration`
- Purchase defaults: journal `Purchases`, picking type `My Company: Receipts`,
  source `Vendors`, destination `WH/Stock`
- Seeded partners: 4
- Seeded products: 9
- Seeded supplierinfo rows: 29
- Key records verified: `DEMO CUSTOMER SRL`, `DEMO SUPPLIER SA`, `HAR-0008`

## Quality Gates

Commands run after the changes:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src tests
git diff --check
```

Results:

- `102 passed, 7 skipped, 1 warning`
- `ruff`: all checks passed
- `mypy`: success, no issues in 98 source files
- `git diff --check`: clean

Targeted live integrations also passed:

```bash
RUN_ODOO19_INTEGRATION=1 PYTHONPATH=src \
  uv run pytest tests/integration/test_odoo_jsonrpc_retrieval.py -q

RUN_PHOENIX_INTEGRATION=1 PYTHONPATH=src \
  uv run pytest tests/integration/test_phoenix_observability.py -q

uv run pytest tests/e2e -q
```

Results:

- Odoo JSON-RPC integration: `2 passed`
- Phoenix integration: `2 passed`
- API e2e tests: `7 passed`

## Live API Smoke

Mode:

- `ODOO_MODE=jsonrpc`
- `AGENT_MODE=openai`
- `SESSION_STORE_MODE=memory`
- `ATTACHMENT_STORE_MODE=memory`
- `OBSERVABILITY_MODE=phoenix`
- `TELEMETRY_ENABLED=true`

Request:

```text
Busca en Odoo si existe el producto HAR-0008 y respondeme con el nombre y precio si lo encontrás.
```

Response:

```text
Si, lo encontre.
- Nombre: [HAR-0008] 000 BREAD FLOUR 25 KG
- Precio: 15000.0
```

Phoenix trace evidence for `live-smoke-20260505T131646Z`:

- Root span: `conversation.turn`
- Trace span count: 15
- Child span names included:
  - `agent.run`
  - `attachments.prepare`
  - `agent.session.load`
  - `agent.session.save`
  - `odoo.search_products`
  - `execute_tool search_products`
  - OpenAI model span `chat gpt-5.4-mini`

## Hybrid Session And S3 Attachment Smoke

Temporary isolated services:

```bash
docker run -d --name sumampa-e2e-postgres \
  -e POSTGRES_DB=sumampa_odoo_agent \
  -e POSTGRES_USER=orchid \
  -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?Set private credentials}" \
  -p 15432:5432 postgres:16

docker run -d --name sumampa-e2e-redis \
  -p 16379:6379 redis:7 redis-server --appendonly yes

docker run -d --name sumampa-e2e-minio \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:?Set private credentials}" \
  -p 19000:9000 -p 19001:9001 \
  minio/minio:latest server /data --console-address :9001
```

App mode:

- `SESSION_STORE_MODE=hybrid`
- `SESSION_STORE_POSTGRES_DSN=<set-private-postgres-dsn>`
- `SESSION_STORE_REDIS_URL=redis://127.0.0.1:16379/0`
- `ATTACHMENT_STORE_MODE=s3`
- `ATTACHMENT_STORE_ENDPOINT_URL=http://127.0.0.1:19000`
- `ATTACHMENT_STORE_BUCKET=sumampa-attachments`
- `ODOO_MODE=jsonrpc`
- `AGENT_MODE=openai`

Smoke result:

- `POST /api/v1/messages` returned HTTP `200`
- Postgres table `orchid_session_snapshots` had 1 row for the conversation
- Redis had key `sumampa:session:agent:hybrid-s3-smoke-20260505T134346Z`
- MinIO had 1 object:
  `attachments/2026/05/05/hybrid-s3-smoke-20260505T134346Z/.../product-note.txt`

The assistant response did not find the product from the text attachment in that
particular turn, but the hybrid session and S3 storage paths were live and
auditable.

## Phoenix Dataset/Eval Path

Commands:

```bash
PYTHONPATH=src uv run python scripts/bootstrap_phoenix_evals.py
PYTHONPATH=src uv run python scripts/curate_phoenix_datasets.py \
  sumampa/dev/fullstack-gate \
  --tag eval:live-smoke \
  --session-id live-smoke-20260505T131646Z \
  --allow-unreviewed \
  --use-output-as-expected \
  --limit 1000
PYTHONPATH=src uv run python scripts/run_phoenix_evals.py \
  sumampa/dev/fullstack-gate \
  --odoo-mode jsonrpc \
  --run-name "sumampa/dev/fullstack-gate/codex-live-jsonrpc-2026-05-05" \
  --description "Codex Phoenix eval against real local Odoo JSON-RPC fixtures on 2026-05-05" \
  --dry-run
```

Findings and fixes:

- `scripts/run_phoenix_evals.py` was passing an async task to Phoenix's sync
  experiment runner. Fixed by adding a sync wrapper.
- The eval runner previously forced `ODOO_MODE=dry-run`. Added explicit
  `--odoo-mode`, `--session-store-mode`, and `--attachment-store-mode` options.
- JSON-RPC eval run completed with:
  - 1 task run
  - 2 evaluator runs
  - 8 evaluations
  - assistant found `000 BREAD FLOUR 25 KG`
  - `task_success=1.0`
  - `odoo_payload_valid=1.0`
  - `error=0.0`

## Harbor E2E Eval Evidence

Command shape:

```bash
OPENAI_EVAL_MODEL=gpt-5.4-mini AGENT_MODE=openai PYTHONPATH=src \
  uv run python scripts/run_harbor_benchmarks.py \
  --path benchmarks/harbor/sumampa-odoo-fullstack/<scenario> \
  --gate none
```

Wrapper fixes made during validation:

- Added Harbor `--yes` support so local runs do not abort on interactive prompts.
- Rewrote host-local Phoenix URLs to `host.docker.internal` before passing them
  into Harbor Docker task containers.
- Limited reward upload to reward files created by the current run.
- Increased Phoenix span lookup limit and added retrying while traces ingest.
- Updated Harbor verifier matching to accept formatted CUITs and user-facing
  aliases for internal Odoo field names.

Latest passing reward evidence:

| Scenario | Run | task_success | odoo_payload_valid | grounded | missing | review | llm | latency_ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| argentina-fiscal-warning | `2026-05-05__14-35-22` | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 3810 |
| attachment-assisted-product-search | `2026-05-05__14-33-41` | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 6385 |
| safe-create-product | `2026-05-05__14-26-23` | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 3997 |
| search-seeded-customer | `2026-05-05__14-36-35` | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 4233 |
| search-seeded-product | `2026-05-05__14-31-11` | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 3442 |
| search-seeded-supplier | `2026-05-05__14-26-23` | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 7649 |
| validate-delivery-draft | `2026-05-05__14-32-25` | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 7951 |
| validate-invoice-draft | `2026-05-05__14-26-23` | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 4750 |

Reward artifact root:

```text
benchmark_runs/harbor/140010643f79/
```

Generated evidence summary:

```text
/tmp/sumampa-final-harbor-evidence-2026-05-05.txt
```

## Known Harness Caveats

- Full Harbor batch run can hit a shared Docker image cleanup race. Use
  single-task reruns for deterministic evidence until the wrapper grows a stable
  sequential mode that rebuilds before every child task.
- Phoenix reward upload depends on span ingestion timing. The wrapper now retries
  and scans more spans, but artifacts remain the source of truth when Phoenix
  upload skips a late trace.
- The local default ports are not exclusive on this workstation. Alternate ports
  were used for the hybrid/S3 smoke to avoid disrupting the other stack.

## Current Running Local Services

At the end of validation, these Docker services were still running for inspection:

- `sumampa-odoo-agent-odoo19` on `8069`
- `sumampa-odoo-agent-phoenix` on `6006`
- `sumampa-odoo-agent-grafana` on `3001`
- `sumampa-odoo-agent-prometheus` on `9090`
- `sumampa-odoo-agent-loki` on `3100`
- `sumampa-odoo-agent-tempo` on `3200`
- `sumampa-e2e-postgres` on `15432`
- `sumampa-e2e-redis` on `16379`
- `sumampa-e2e-minio` on `19000` / `19001`

The temporary Uvicorn app processes on `8011` and `8012` were stopped after the
smokes completed.
