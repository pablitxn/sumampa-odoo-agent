# Guia Phoenix + Harbor para Sumampa Odoo Agent

Esta guia documenta como usar la nueva capa de observabilidad y evaluacion del repo:
Phoenix para traces, datasets, experiments y annotations; Harbor para benchmarks full-stack
reproducibles contra la API, Odoo y sus sidecars.

Estado de referencia: migracion Phoenix + Harbor vigente al 2026-04-26.

## Fuentes consultadas

- Phoenix home: https://phoenix.arize.com
- Phoenix Docker/self-hosting: https://arize.com/docs/phoenix/self-hosting/deployment-options/docker
- Phoenix OTEL SDK: https://arize.com/docs/phoenix/sdk-api-reference/python/arize-phoenix-otel
- Phoenix tracing concepts: https://arize.com/docs/phoenix/tracing/concepts-tracing/how-tracing-works
- Phoenix trace querying: https://arize.com/docs/phoenix/tracing/how-to-tracing/importing-and-exporting-traces/extract-data-from-spans
- Phoenix annotations: https://arize.com/docs/phoenix/tracing/how-to-tracing/feedback-and-annotations/capture-feedback
- Phoenix datasets: https://arize.com/docs/phoenix/datasets-and-experiments/concepts-datasets
- Phoenix experiments: https://arize.com/docs/phoenix/datasets-and-experiments/how-to-experiments/run-experiments
- Phoenix evaluators: https://arize.com/docs/phoenix/datasets-and-experiments/how-to-experiments/using-evaluators
- Phoenix evals package: https://arize.com/docs/phoenix/sdk-api-reference/python/arize-phoenix-evals
- Harbor getting started: https://www.harborframework.com/docs/getting-started
- Harbor core concepts: https://www.harborframework.com/docs/core-concepts
- Harbor task structure: https://www.harborframework.com/docs/tasks
- Harbor running evals: https://www.harborframework.com/docs/run-jobs/run-evals
- Harbor artifacts: https://www.harborframework.com/docs/run-jobs/results-and-artifacts

## 1. Modelo mental

Phoenix y Harbor no compiten; resuelven problemas distintos.

| Capa | Tool | Que responde |
| --- | --- | --- |
| Observabilidad diaria | Phoenix traces | Que paso en una request, que spans se ejecutaron, cuanto tardo, que tool/LLM/Odoo fallo |
| Curacion | Phoenix spans + datasets | Que conversaciones reales o sinteticas queremos convertir en casos repetibles |
| Evals offline | Phoenix experiments | Si una version del agente mejora o empeora sobre un dataset con evaluadores |
| Benchmark E2E | Harbor | Si el workflow completo funciona en contenedores reproducibles con app + Odoo |
| Debug de regresiones | Phoenix annotations + Harbor artifacts | Que reward fallo y que trace/artifact explica el fallo |

Regla practica:

- Usa Phoenix cuando queres ver, curar, comparar o anotar comportamiento.
- Usa Harbor cuando queres probar el sistema completo con sidecars reales y un verifier que escribe rewards.
- Usa ambos cuando queres que un benchmark full-stack deje evidencia investigable: Harbor produce `reward.json` y artifacts; Phoenix guarda el trace y las annotations correlacionadas.

## 2. Lo que quedo implementado en este repo

### Configuracion publica

El modo aceptado por `OBSERVABILITY_MODE` ahora es:

- `disabled`
- `phoenix`

Langfuse fue removido. No existen mas `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY` ni
`LANGFUSE_SECRET_KEY` como configuracion soportada.

Variables Phoenix:

```bash
OBSERVABILITY_MODE=phoenix
PHOENIX_BASE_URL=http://localhost:6006
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
PHOENIX_PROJECT_NAME=sumampa-odoo-agent
PHOENIX_API_KEY_ENV_VAR=PHOENIX_API_KEY
PHOENIX_API_KEY=
```

Notas importantes:

- `PHOENIX_BASE_URL` es para el cliente Python de Phoenix: datasets, experiments,
  span queries y annotations.
- `PHOENIX_COLLECTOR_ENDPOINT` es para OTLP HTTP trace ingestion. En local usamos
  `http://localhost:6006/v1/traces`.
- `TELEMETRY_ENABLED=true` no es necesario para emitir traces a Phoenix si
  `OBSERVABILITY_MODE=phoenix`; la condicion real es Phoenix habilitado y
  `TELEMETRY_TRACES_ENABLED` no seteado a false.
- Si ademas habilitas `TELEMETRY_ENABLED=true`, metrics/logs siguen yendo por la
  configuracion OTLP operacional. Los traces, con Phoenix habilitado, van a Phoenix.

### Servicios locales

`docker-compose.yml` agrega:

- `phoenix`: UI + collector HTTP en `6006`.
- `phoenix-postgres`: Postgres persistente para Phoenix local.

Levantar Phoenix local:

```bash
docker compose --profile observability up -d phoenix
```

Abrir:

```text
http://localhost:6006
```

### Dependencias relevantes

Runtime / tracing:

- `arize-phoenix-otel`
- `arize-phoenix-client`

Evals:

- `arize-phoenix-evals`
- `pandas`

Harbor se instala como CLI externa:

```bash
uv tool install harbor
harbor --help
```

## 3. Como arranca Phoenix tracing en la app

La entrada real esta en:

- `src/sumampa_odoo_agent/integrations/telemetry/bootstrap.py`
- `src/sumampa_odoo_agent/integrations/telemetry/otel_provider.py`

Con `OBSERVABILITY_MODE=phoenix`, `bootstrap_telemetry(settings)` llama a
`phoenix.otel.register(...)` con:

- `endpoint=settings.observability.collector_endpoint`
- `project_name=settings.observability.project_name`
- `protocol="http/protobuf"`
- `batch=True`
- `auto_instrument=False`
- `sampler=TraceIdRatioBased(settings.observability.sample_rate)`

La auto-instrumentacion de Phoenix queda apagada porque el repo controla explicitamente que
instrumentar:

- FastAPI via `FastAPIInstrumentor`.
- HTTPX.
- SQLAlchemy.
- Redis.
- Botocore.
- Microsoft Agent Framework observability.
- Spans manuales del dominio Sumampa.

Detalle que puede confundir: `build_observability_provider(settings)` devuelve
`NoOpObservabilityProvider` para `phoenix`. Eso es intencional. En Phoenix, el provider real
entra por `bootstrap_telemetry` y se inyecta en `build_app_services(...)` como
`telemetry_observability`.

## 4. Anatomia de un trace

Cada `POST /api/v1/messages` deberia producir un trace centrado en el span
`conversation.turn`.

Spans principales:

| Span | Tipo OpenInference | Donde nace | Para que sirve |
| --- | --- | --- | --- |
| `conversation.turn` | `AGENT` | `ConversationService.run_turn` | Raiz funcional de un turno WhatsApp |
| `attachments.prepare` | `CHAIN` | `ConversationService.run_turn` | Ingestion/normalizacion de adjuntos |
| `agent.run` | `AGENT` | `MicrosoftAgentFrameworkOpenAIService.run` | Llamada al agente |
| `agent.session.load` | `CHAIN` | Agent service | Carga de session state |
| `agent.session.save` | `CHAIN` | Agent service | Persistencia de session state |
| `odoo.<operation>` | `TOOL` | `integrations/observability/odoo.py` | Operaciones Odoo dry-run/jsonrpc |
| spans Agent Framework | `LLM`, `TOOL`, etc. | Instrumentacion del framework | LLM calls y tool calls automaticos |
| spans FastAPI/HTTPX/etc. | `CHAIN` / `TOOL` | Instrumentacion global + normalizador OTEL | Transporte, outbound HTTP, DB/cache |
| `conversation.tags` | `CHAIN` | `/api/v1/conversation-tags` | Retagging de conversaciones para curacion |

### Atributos clave

Los spans manuales usan atributos compatibles con OpenInference/Phoenix:

| Atributo | Uso |
| --- | --- |
| `openinference.span.kind` | Clasifica el span: `AGENT`, `CHAIN`, `TOOL`, `LLM`, etc. |
| `input.mime_type` / `output.mime_type` | Actualmente `application/json` cuando hay payload |
| `input.value` / `output.value` | JSON serializado del input/output |
| `session.id` | `conversation_id`; agrupa turnos por sesion en Phoenix |
| `user.id` / `enduser.id` | Usuario del canal |
| `metadata` | Metadata JSON del span |
| `sumampa.*` | Metadata simple expandida para filtrar/buscar |
| `sumampa.openinference.kind.source` | `otel-auto` cuando el repo completo el tipo OpenInference de un span autoinstrumentado |
| `sumampa.otel.span_kind` | `SERVER`, `CLIENT`, etc.; ayuda a auditar la traduccion OTEL -> OpenInference |
| `sumampa.tags` | Tags como CSV |
| `tag.tags` | Tags como JSON |
| `gen_ai.request.model` / `llm.model_name` | Modelo asociado cuando aplica |

### Redaccion de payloads

El helper `to_observability_payload(...)` evita subir bytes crudos. Si un valor es `bytes`,
lo transforma en:

```json
{
  "kind": "bytes",
  "size_bytes": 12345,
  "sha256": "..."
}
```

Esto es importante para adjuntos: Phoenix puede mostrar manifests, filenames, hashes y tamanos,
pero no el binario original.

## 5. Operacion local end-to-end

Instalar dependencias:

```bash
uv sync --extra dev
```

Levantar Phoenix:

```bash
docker compose --profile observability up -d phoenix
```

Configurar `.env`:

```bash
OBSERVABILITY_MODE=phoenix
PHOENIX_BASE_URL=http://localhost:6006
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
PHOENIX_PROJECT_NAME=sumampa-odoo-agent
PHOENIX_API_KEY_ENV_VAR=PHOENIX_API_KEY
```

Arrancar la app:

```bash
uv run sumampa_odoo_agent --reload
```

Enviar un mensaje de smoke:

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

En Phoenix:

1. Abrir `http://localhost:6006`.
2. Elegir el proyecto `sumampa-odoo-agent`.
3. Buscar el span `conversation.turn`.
4. Filtrar por `session.id = phoenix-smoke-1` o por tag `eval:candidate`.
5. Abrir el trace y revisar child spans: `agent.run`, `attachments.prepare`, `odoo.*`,
   HTTPX y spans del Agent Framework.

## 6. Como leer traces con criterio

Cuando inspecciones un trace, no mires solo el output final. Segui esta secuencia:

1. `conversation.turn`
   - `input.value`: texto, contexto, eval tags, placeholders de adjuntos.
   - `output.value`: `assistant_text`, `conversation_id` o error.
   - `session.id`: debe coincidir con `conversation_id`.
   - `sumampa.transport.*`: canal, usuario, conversacion.

2. `attachments.prepare`
   - Confirma si habia adjuntos.
   - Revisa manifests, hashes y artifacts derivados.
   - Si falta contenido, el problema suele estar antes del agente.

3. `agent.session.load`
   - `found=true/false`.
   - Si el agente olvida contexto, mirar aca primero.

4. `agent.run`
   - Prompt, contexto normalizado, manifests de adjuntos y modelo.
   - Child spans del Agent Framework muestran LLM/tool activity.

5. `odoo.<operation>`
   - Input del tool, modo `dry-run` o `jsonrpc`, output del gateway.
   - Si el asistente dice algo no soportado por Odoo, comparar `assistant_text` contra estos outputs.

6. `agent.session.save`
   - Confirma que se persistio el nuevo estado.
   - Verifica `eval_tags` si estas curando conversaciones.

7. Annotations
   - Scores manuales, CODE, LLM o importados desde Harbor.
   - En Harbor, deberias ver metadata como `harbor.task_id`, `git.sha`, `agent_model`.

Preguntas utiles:

- El fallo fue de transporte, agente, Odoo o verificador?
- El modelo tenia el dato en el tool output o lo invento?
- Faltaba informacion de usuario y el agente la pidio correctamente?
- El session state tenia tags/turnos esperados?
- El reward de Harbor corresponde a este run o a un run viejo? Para eso importamos usando
  ventana temporal desde `run_started_at` y metadata de correlacion.

## 7. Consultar spans desde Python

Phoenix permite bajar spans como DataFrame. En este repo usamos `build_phoenix_client(settings)`
de `scripts/phoenix_eval_utils.py`.

Ejemplo minimo:

```bash
PYTHONPATH=src uv run python - <<'PY'
from sumampa_odoo_agent.config import load_settings
from scripts.phoenix_eval_utils import build_phoenix_client

settings = load_settings()
client = build_phoenix_client(settings)

df = client.spans.get_spans_dataframe(
    project_identifier=settings.observability.project_name,
    limit=50,
)
print(df[["name"]].head())
print(df.columns.tolist())
PY
```

Con rango temporal:

```bash
PYTHONPATH=src uv run python - <<'PY'
from datetime import UTC, datetime, timedelta
from sumampa_odoo_agent.config import load_settings
from scripts.phoenix_eval_utils import build_phoenix_client

settings = load_settings()
client = build_phoenix_client(settings)

start = datetime.now(UTC) - timedelta(hours=1)
df = client.spans.get_spans_dataframe(
    project_identifier=settings.observability.project_name,
    start_time=start,
    limit=500,
)
print(df[["name", "context.trace_id", "context.span_id"]].tail(20))
PY
```

Con `SpanQuery`:

```bash
PYTHONPATH=src uv run python - <<'PY'
from phoenix.trace.dsl import SpanQuery
from sumampa_odoo_agent.config import load_settings
from scripts.phoenix_eval_utils import build_phoenix_client

settings = load_settings()
client = build_phoenix_client(settings)

query = (
    SpanQuery()
    .where("span_kind == 'AGENT'")
    .select(
        input="input.value",
        output="output.value",
        session_id="session.id",
    )
)

df = client.spans.get_spans_dataframe(
    query=query,
    project_name=settings.observability.project_name,
)
print(df.tail(10))
PY
```

Para scripts internos, preferi reutilizar `_span_row_to_trace(...)` de
`scripts/curate_phoenix_datasets.py`, porque normaliza diferencias entre columnas OTEL,
atributos Phoenix y JSON strings.

## 8. Tags y curacion de conversaciones

Los `eval_tags` son el puente entre trafico real/dev y datasets.

Se pueden enviar directamente en `/api/v1/messages`:

```json
{
  "conversation_id": "conv-123",
  "channel": "whatsapp",
  "user_id": "u-1",
  "text": "Busca el proveedor JAMBO SA",
  "attachments": [],
  "context": {},
  "eval_tags": ["eval:candidate", "eval:odoo-jsonrpc"]
}
```

O retaggear una conversacion existente:

```bash
curl -sS http://127.0.0.1:8000/api/v1/conversation-tags \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "conv-123",
    "channel": "whatsapp",
    "user_id": "reviewer",
    "eval_tags": ["eval:dataset-ready", "eval:odoo-jsonrpc"],
    "context": {"reason": "good regression case"}
  }' | jq
```

En el demo estatico (`demo/index.html`), cambiar un tag desde el panel `Eval tags` llama a
`/api/v1/conversation-tags` y adjunta un snapshot del transcript visible en
`context.transcript`. Ese snapshot contiene rol, texto, timestamp y metadata segura de
adjuntos, sin `content_base64`. Gracias a eso, `scripts/export_tagged_conversations.py`
puede reconstruir conversaciones retaggeadas desde Phoenix incluso cuando la app local corre
con `SESSION_STORE_MODE=memory`.

Convencion sugerida:

| Tag | Uso |
| --- | --- |
| `eval:candidate` | Caso potencial para revisar |
| `eval:dataset-ready` | Revisado y listo para dataset |
| `eval:regression` | Caso que representa una regresion |
| `eval:discarded` | No promover, aunque exista trace |
| `eval:harbor` | Generado por benchmark Harbor |
| `eval:odoo-jsonrpc` | Toca Odoo real/jsonrpc |
| `eval:attachment` | Usa adjuntos |

Reglas:

- No uses tags como unica fuente de verdad si hay session store Postgres. El exportador intenta
  leer Postgres y, si encuentra tags actuales en session state, los trata como autoritativos.
- Usa tags estables y pocos. Es preferible `eval:dataset-ready` + metadata que 10 tags casi iguales.
- Para Harbor, usa `conversation_id` unico por task o por run si el fixture lo permite. Ayuda a la
  correlacion de rewards con spans.

## 9. Exportar conversaciones taggeadas

Script:

```bash
PYTHONPATH=src uv run python scripts/export_tagged_conversations.py \
  --tag eval:candidate \
  --json-array
```

Opciones utiles:

```bash
PYTHONPATH=src uv run python scripts/export_tagged_conversations.py \
  --tag eval:dataset-ready \
  --session-id conv-123 \
  --from-timestamp 2026-04-26T00:00:00+00:00 \
  --to-timestamp 2026-04-27T00:00:00+00:00 \
  --include-session-payload \
  --json-array
```

Que devuelve:

- `conversation_id`
- `eval_tags`
- resumen de traces
- mensajes reconstruidos desde Postgres si existe session payload
- fallback al snapshot `context.transcript` emitido por el demo al retaggear
- fallback a input/output de traces si no hay Postgres
- resumen Postgres y errores de carga si los hubo

Usos:

- Revisar candidatos antes de promoverlos.
- Generar ejemplos manuales para dataset.
- Auditar que un retagging quedo aplicado.
- Extraer conversaciones completas cuando el trace individual no alcanza.

## 10. Datasets Phoenix en Sumampa

Los datasets base estan definidos en `scripts/phoenix_eval_utils.py`:

| Dataset | Uso |
| --- | --- |
| `sumampa/dev/conversation-turns` | Conversaciones WhatsApp curadas, calidad conversacional |
| `sumampa/dev/odoo-ops` | Casos Odoo con expectativas deterministicas |
| `sumampa/dev/regression-failures` | Fallos reales/dev promovidos a regresion |

Crear datasets base:

```bash
PYTHONPATH=src uv run python scripts/bootstrap_phoenix_evals.py
```

El script intenta crear datasets vacios. Si ya existen, Phoenix puede devolver error y el script
lo imprime como skipped/failed.

### Shape recomendado de un example

Input:

```json
{
  "conversation_id": "eval-case-001",
  "channel": "whatsapp",
  "user_id": "eval-user",
  "text": "Busca si existe el proveedor JAMBO SA y dame el CUIT.",
  "context": {
    "source": "manual"
  },
  "attachments": [],
  "attachment_manifests": []
}
```

Expected output / reference:

```json
{
  "required_substrings": ["JAMBO", "30644193078"],
  "forbidden_substrings": ["traceback", "exception"],
  "missing_fields": [],
  "grounded_terms": ["JAMBO", "30644193078"]
}
```

Metadata:

```json
{
  "kind": "odoo",
  "priority": "p1",
  "scenario": "supplier-search",
  "source": "manual"
}
```

Campos que entienden los evaluadores actuales:

| Campo | Evaluador | Significado |
| --- | --- | --- |
| `required_substrings` | `deterministic_eval` | Todos deben aparecer en `assistant_text` |
| `forbidden_substrings` | `deterministic_eval` | Ninguno debe aparecer |
| `missing_fields` | `conversation_quality_eval` | El asistente debe pedir/mencionar esos campos |
| `grounded_terms` | `conversation_quality_eval` | Terminos que deberian estar soportados por tool output |

## 11. Promover traces a datasets

Script:

```bash
PYTHONPATH=src uv run python scripts/curate_phoenix_datasets.py \
  sumampa/dev/regression-failures \
  --tag eval:dataset-ready
```

Opciones utiles:

```bash
PYTHONPATH=src uv run python scripts/curate_phoenix_datasets.py \
  sumampa/dev/odoo-ops \
  --tag eval:dataset-ready \
  --session-id conv-123 \
  --limit 100 \
  --from-timestamp 2026-04-26T00:00:00+00:00
```

Si queres usar el output observado como expected output:

```bash
PYTHONPATH=src uv run python scripts/curate_phoenix_datasets.py \
  sumampa/dev/conversation-turns \
  --tag eval:reviewed-good \
  --use-output-as-expected
```

Usar `--use-output-as-expected` solo despues de revision humana. Si no, convertis una salida
potencialmente mala en golden output.

El item curado guarda metadata como:

- `source=phoenix_trace`
- `source_trace_id`
- `source_span_id`
- `source_session_id`
- `source_user_id`
- `source_tags`
- `source_metadata`
- `attachment_manifests`
- `requires_expected_output_review`
- `rubric`

Para adjuntos, el script busca child spans `attachments.prepare` del mismo trace y preserva
manifests/artifacts. Esto permite reproducir el caso sin subir binarios crudos a Phoenix.

## 12. Crear cases manuales con Phoenix Client

Para agregar un caso sintetico sin pasar por traces:

```bash
PYTHONPATH=src uv run python - <<'PY'
from sumampa_odoo_agent.config import load_settings
from scripts.phoenix_eval_utils import build_phoenix_client

settings = load_settings()
client = build_phoenix_client(settings)

client.datasets.add_examples_to_dataset(
    dataset="sumampa/dev/odoo-ops",
    inputs=[
        {
            "conversation_id": "manual-supplier-jambo",
            "channel": "whatsapp",
            "user_id": "eval-user",
            "text": "Busca en Odoo si existe el proveedor JAMBO SA y respondeme con el CUIT.",
            "attachments": [],
            "context": {"case": "manual"},
        }
    ],
    outputs=[
        {
            "required_substrings": ["JAMBO", "30644193078"],
            "forbidden_substrings": ["traceback", "exception"],
            "grounded_terms": ["JAMBO", "30644193078"],
            "missing_fields": [],
        }
    ],
    metadata=[
        {
            "kind": "odoo",
            "scenario": "supplier-search",
            "priority": "p1",
            "source": "manual",
        }
    ],
)
PY
```

Checklist para un buen case:

- Input minimal pero realista.
- `conversation_id` estable si queres reproducibilidad, unico si queres evitar mezcla de sesiones.
- Expected output con constraints observables.
- Metadata que permita segmentar: `scenario`, `priority`, `source`, `odoo_mode`, `has_attachments`.
- No incluir secretos ni binarios crudos.

## 13. Correr Phoenix experiments

Script:

```bash
PYTHONPATH=src uv run python scripts/run_phoenix_evals.py sumampa/dev/odoo-ops
```

Dry run:

```bash
PYTHONPATH=src uv run python scripts/run_phoenix_evals.py \
  sumampa/dev/odoo-ops \
  --dry-run
```

Con nombre y repeticiones:

```bash
PYTHONPATH=src uv run python scripts/run_phoenix_evals.py \
  sumampa/dev/odoo-ops \
  --run-name "odoo-ops/gpt-5.4-mini-baseline" \
  --description "Baseline posterior a migracion Phoenix" \
  --repetitions 3
```

Con LLM judge:

```bash
OPENAI_EVAL_MODEL=gpt-5.4-mini \
PYTHONPATH=src uv run python scripts/run_phoenix_evals.py \
  sumampa/dev/conversation-turns
```

O explicitamente:

```bash
PYTHONPATH=src uv run python scripts/run_phoenix_evals.py \
  sumampa/dev/conversation-turns \
  --llm-judge-model gpt-5.4-mini
```

Que hace internamente:

- Carga el dataset desde Phoenix.
- Fuerza settings de eval:
  - Odoo `dry-run`.
  - session store `memory`.
  - attachment store `memory`.
- Por cada example, construye servicios locales e invoca `ConversationService.run_turn(...)`.
- Llama `bootstrap_telemetry(settings)`, asi que los traces del eval tambien llegan a Phoenix.
- Corre evaluadores deterministas y opcionalmente LLM-as-judge.

Scores actuales:

| Score | Fuente | Interpretacion |
| --- | --- | --- |
| `task_success` | deterministic / LLM / Harbor | Exito general del caso |
| `odoo_payload_valid` | deterministic / Harbor | Runtime sin error de schema/validacion y respuesta con forma util |
| `grounded_in_tool_result` | heuristic / LLM / Harbor | Claims soportados por Odoo/tool result |
| `missing_data_handled` | heuristic / LLM / Harbor | Pide o maneja datos faltantes |
| `communication_quality` | heuristic / LLM / Harbor | Calidad de respuesta WhatsApp en espanol |
| `needs_human_review` | heuristic / LLM / Harbor | 1.0 si conviene revisar |
| `latency_ms` | deterministic / Harbor | Latencia end-to-end |
| `error` | deterministic / Harbor | 1.0 si fallo |

Interpretacion:

- `task_success=1` y `error=0` es el minimo.
- `communication_quality` alto no alcanza si `grounded_in_tool_result` es bajo.
- `needs_human_review=1` no siempre significa fallo; significa ambiguedad o baja confianza.
- `latency_ms` se mira por distribucion, no como pass/fail universal.

## 14. Agregar o modificar evaluadores Phoenix

Archivo:

```text
scripts/phoenix_eval_utils.py
```

Un evaluador simple recibe `input`, `output`, `expected`/`expected_output`, `metadata` y devuelve
records Phoenix-compatible:

```python
def my_eval(*, input, output, expected=None, expected_output=None, metadata=None, **kwargs):
    assistant_text = str((output or {}).get("assistant_text") or "")
    passed = "JAMBO" in assistant_text
    return [
        {
            "name": "mentions_supplier",
            "score": 1.0 if passed else 0.0,
            "label": "pass" if passed else "fail",
            "explanation": "Checks that assistant mentions expected supplier.",
            "metadata": {"source": "code"},
        }
    ]
```

Luego agregarlo a `evaluators` en `scripts/run_phoenix_evals.py`.

Buenas practicas:

- Preferir evaluadores deterministas para contratos duros: JSON valido, tool correcto, dato exacto.
- Usar LLM judge para tono, claridad, relevancia o groundedness semantico.
- Mantener nombres de scores estables; Phoenix y Harbor dependen de comparabilidad historica.
- Si cambias la semantica de un score, versionarlo: `communication_quality_v2`.
- Evitar evaluadores que dependan de orden accidental o texto demasiado exacto, salvo que ese sea el contrato.

## 15. Annotations en Phoenix

Phoenix annotations permiten pegar feedback a un span. Una annotation tiene:

- span id.
- name.
- annotator kind: `HUMAN`, `LLM` o `CODE`.
- score y/o label.
- explanation.
- metadata.

Ejemplo desde Python:

```bash
PYTHONPATH=src uv run python - <<'PY'
from sumampa_odoo_agent.config import load_settings
from scripts.phoenix_eval_utils import build_phoenix_client

settings = load_settings()
client = build_phoenix_client(settings)

client.spans.add_span_annotation(
    span_id="67f6740bbe1ddc3f",
    annotation_name="task_success",
    annotator_kind="CODE",
    score=1.0,
    explanation="Verified manually from Odoo tool output.",
    metadata={"source": "manual-review"},
    sync=True,
)
PY
```

En este repo las annotations se usan especialmente para importar Harbor rewards:

- El verifier escribe `/logs/verifier/reward.json`.
- El runner encuentra el `conversation.turn` de Phoenix por `conversation_id` y ventana temporal.
- Por cada metric numerica en `reward.json`, llama `client.spans.add_span_annotation(...)`.
- Metadata incluye `harbor.task_id`, `harbor.job_id`, `git.sha`, `agent_model`, dataset y path del reward.

Si no aparece la annotation:

- Verificar que Phoenix tenga el trace del run.
- Verificar que `conversation_id` del fixture sea el mismo que `session.id`.
- Verificar que el run no haya empezado antes del `run_started_at` usado por el uploader.
- Verificar que el reward tenga valores numericos, no strings.

## 16. Harbor: que es un benchmark en este repo

Harbor define:

- Task: una instruccion, un ambiente y un test/verifier.
- Dataset: coleccion de tasks.
- Trial: intento de un agente sobre una task.
- Job: coleccion de trials.
- Reward: salida numerica que dice que tan bien fue el trial.

Nuestro dataset local:

```text
benchmarks/harbor/sumampa-odoo-fullstack
```

Task actual:

```text
benchmarks/harbor/sumampa-odoo-fullstack/search-seeded-supplier
```

Estructura:

```text
search-seeded-supplier/
  instruction.md
  task.toml
  environment/
    Dockerfile
    docker-compose.yaml
  solution/
    solve.sh
  tests/
    test.sh
    verify.py
    fixtures/
      request.json
      expected.json
```

Piezas:

- `instruction.md`: instruccion de alto nivel para el agente.
- `task.toml`: metadata, timeouts, env del verifier, recursos.
- `environment/docker-compose.yaml`: sidecars full-stack.
- `tests/test.sh`: entrypoint del verifier.
- `tests/verify.py`: llama `/api/v1/messages`, compara respuesta, escribe rewards.
- `tests/fixtures/request.json`: payload real de la API.
- `tests/fixtures/expected.json`: asserts esperados.
- `solution/solve.sh`: requerido para oracle/sanity checks.

## 17. Harbor sidecars actuales

`environment/docker-compose.yaml` define:

| Servicio | Rol |
| --- | --- |
| `main` | Contenedor principal donde Harbor ejecuta agent/verifier |
| `sumampa-app` | Imagen local de la app construida por el runner |
| `odoo19` | Odoo 19 real |
| `odoo-postgres` | Postgres para Odoo |

`sumampa-app` corre:

```bash
python scripts/bootstrap_odoo_integration.py && python -m sumampa_odoo_agent.main
```

Variables relevantes:

- `ODOO_MODE=jsonrpc`
- `ODOO_BASE_URL=http://odoo19:8069`
- `ODOO_DATABASE=sumampa_integration`
- `SESSION_STORE_MODE=memory`
- `ATTACHMENT_STORE_MODE=memory`
- `OBSERVABILITY_MODE=phoenix`
- `PHOENIX_COLLECTOR_ENDPOINT=http://host.docker.internal:6006/v1/traces`
- `OPENAI_API_KEY=${OPENAI_API_KEY:-}`

El benchmark es full-stack porque la API habla con Odoo por JSON-RPC dentro del ambiente Docker.

## 18. Correr Harbor

Prerequisitos:

```bash
uv tool install harbor
docker info
export OPENAI_API_KEY=...
```

Comando recomendado:

```bash
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py
```

Que hace:

1. Calcula `git_sha`.
2. Construye imagen local `sumampa-odoo-agent:harbor-{git_sha}`.
3. Levanta Phoenix local si no pasas `--skip-phoenix`.
4. Ejecuta:

   ```bash
   harbor run -p benchmarks/harbor/sumampa-odoo-fullstack \
     -a oracle \
     -m gpt-5.4-mini \
     --env docker
   ```

5. Guarda artifacts bajo:

   ```text
   benchmark_runs/harbor/{git_sha}
   ```

6. Indexa rewards en `reward-index.json`.
7. Sube rewards a Phoenix como annotations si no pasas `--no-upload-phoenix`.

Flags utiles:

```bash
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py \
  --agent oracle \
  --model gpt-5.4-mini \
  --artifacts-dir benchmark_runs/harbor \
  --skip-build \
  --skip-phoenix
```

Solo correr Harbor sin subir a Phoenix:

```bash
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py \
  --no-upload-phoenix
```

Usar Phoenix remoto/self-host distinto:

```bash
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py \
  --phoenix-base-url https://phoenix.example.com \
  --phoenix-collector-endpoint https://phoenix.example.com/v1/traces \
  --phoenix-project-name sumampa-odoo-agent
```

## 19. Reward schema Harbor

El verifier debe escribir:

```text
/logs/verifier/reward.json
```

Con valores numericos:

```json
{
  "task_success": 1.0,
  "odoo_payload_valid": 1.0,
  "grounded_in_tool_result": 1.0,
  "missing_data_handled": 1.0,
  "communication_quality": 0.95,
  "needs_human_review": 0.0,
  "latency_ms": 1234.0,
  "error": 0.0
}
```

Harbor tambien soporta `reward.txt`, pero en este repo preferimos `reward.json` porque necesitamos
multiples metricas comparables con Phoenix.

Ademas escribimos:

```text
/logs/verifier/correlation.json
/logs/verifier/verifier.log
/logs/artifacts/request.json
/logs/artifacts/response.json
```

`correlation.json` debe incluir:

- `harbor.job_id`
- `harbor.task_id`
- `git.sha`
- `agent_model`
- `dataset`
- `phoenix.project_name`
- `conversation_id`
- `eval_tags`

Los artifacts bajo `/logs/artifacts/` son recolectados por Harbor automaticamente y aparecen en el
trial output directory.

## 20. Agregar una nueva task Harbor

Workflow recomendado:

1. Copiar la task existente:

   ```bash
   cp -R \
     benchmarks/harbor/sumampa-odoo-fullstack/search-seeded-supplier \
     benchmarks/harbor/sumampa-odoo-fullstack/<new-task>
   ```

2. Editar `task.toml`:

   - `task.name` unico, por ejemplo `sumampa/odoo-fullstack-create-draft-invoice`.
   - `task.description`.
   - `task.keywords`.
   - `HARBOR_TASK_ID`.
   - timeouts si el caso es mas largo.

3. Editar `instruction.md`:

   - Decir que debe hacer el agente.
   - No incluir asserts del verifier si eso sesga el comportamiento.
   - Mantener foco en comportamiento observable por usuario/API.

4. Editar `tests/fixtures/request.json`:

   - `conversation_id` unico.
   - `text` realista.
   - `context` minimo necesario.
   - `eval_tags` utiles.
   - `attachments` si aplica.

5. Editar `tests/fixtures/expected.json`:

   - `required_terms`.
   - `forbidden_terms`.
   - `missing_fields`.
   - `max_latency_ms`.

6. Si el caso necesita validacion mas fuerte, extender `tests/verify.py`:

   - Comprobar respuesta HTTP.
   - Comprobar texto de assistant.
   - Si se agrega consulta directa a Odoo, escribir artifacts de esa consulta.
   - Mantener todos los rewards numericos.

7. Si agregas estructura nueva, sumar o adaptar tests unitarios en
   `tests/unit/test_harbor_benchmark_assets.py`.

8. Probar local:

   ```bash
   PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py \
     --path benchmarks/harbor/sumampa-odoo-fullstack \
     --no-upload-phoenix
   ```

9. Repetir con upload a Phoenix y revisar annotations.

Buenas practicas:

- Cada task debe ser autocontenida.
- El verifier no debe depender de estado externo fuera del ambiente Harbor.
- Si el seed de Odoo cambia, actualizar expected fixtures y documentar el motivo.
- No usar sleeps fijos si se puede usar healthcheck/retry.
- Guardar request, response y cualquier payload Odoo relevante en `/logs/artifacts/`.

## 21. Flujo recomendado para crear una eval nueva

### Caso barato / offline en Phoenix

1. Identificar comportamiento a proteger.
2. Crear caso manual o curarlo desde trace.
3. Agregar expected output con constraints.
4. Correr:

   ```bash
   PYTHONPATH=src uv run python scripts/run_phoenix_evals.py \
     sumampa/dev/odoo-ops \
     --dry-run
   ```

5. Si pasa dry run, correr sin `--dry-run`.
6. Mirar experiment en Phoenix.
7. Ajustar evaluator si el score no refleja calidad real.

### Caso full-stack en Harbor

1. Crear task Harbor.
2. Fixture `request.json` debe llamar `/api/v1/messages`.
3. Verifier debe producir `reward.json`.
4. Correr Harbor con `--no-upload-phoenix` hasta que artifacts sean correctos.
5. Correr Harbor con upload a Phoenix.
6. Revisar:
   - `reward-index.json`.
   - trial artifacts.
   - trace `conversation.turn`.
   - annotations importadas.

### Caso desde bug real

1. Taggear conversacion:

   ```bash
   curl -sS http://127.0.0.1:8000/api/v1/conversation-tags \
     -H 'Content-Type: application/json' \
     -d '{
       "conversation_id": "conv-bug-123",
       "channel": "whatsapp",
       "user_id": "reviewer",
       "eval_tags": ["eval:regression", "eval:dataset-ready"],
       "context": {"bug": "wrong supplier cuit"}
     }'
   ```

2. Exportar para revisar:

   ```bash
   PYTHONPATH=src uv run python scripts/export_tagged_conversations.py \
     --tag eval:regression \
     --session-id conv-bug-123 \
     --json-array
   ```

3. Curar a dataset:

   ```bash
   PYTHONPATH=src uv run python scripts/curate_phoenix_datasets.py \
     sumampa/dev/regression-failures \
     --tag eval:regression \
     --session-id conv-bug-123
   ```

4. Editar expected output en Phoenix.
5. Correr experiment y confirmar que falla antes del fix.
6. Fix.
7. Re-correr y comparar experiment.

## 22. Como comparar resultados en Phoenix

En Phoenix, usar experiments para responder:

- Cambio el modelo mejora `task_success`?
- Subio `latency_ms`?
- Aumentaron `needs_human_review` o `error`?
- Los fallos se concentran en `scenario=supplier-search` o en attachments?
- El LLM judge contradice al deterministic evaluator?

Practica recomendada:

- Nombrar runs con patron:

  ```text
  <dataset>/<modelo>/<descripcion-corta>
  ```

  Ejemplo:

  ```text
  sumampa/dev/odoo-ops/gpt-5.4-mini-after-tool-prompt
  ```

- Usar metadata del experiment:
  - `agent_mode`
  - `agent_model`
  - `odoo_mode`
  - `git.sha` si agregamos ese campo en el futuro.

- Comparar por score, pero abrir traces de los peores ejemplos antes de sacar conclusiones.

## 23. CI y checks recomendados

Checks basicos:

```bash
uv run ruff check .
uv run mypy src tests
uv run pytest
```

Smoke Phoenix local:

```bash
docker compose --profile observability up -d phoenix
RUN_PHOENIX_INTEGRATION=1 \
PYTHONPATH=src \
uv run pytest tests/integration/test_phoenix_observability.py
```

Smoke Docker build para Harbor:

```bash
docker build -t sumampa-odoo-agent:harbor-smoke .
```

Smoke Harbor:

```bash
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py \
  --no-upload-phoenix
```

Full local benchmark:

```bash
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py
```

## 24. Troubleshooting

### No aparecen traces en Phoenix

Revisar:

```bash
docker compose --profile observability ps phoenix
curl -sS http://localhost:6006 >/dev/null
```

Verificar env:

```bash
env | grep -E 'OBSERVABILITY|PHOENIX|TELEMETRY_TRACES'
```

Checklist:

- `OBSERVABILITY_MODE=phoenix`.
- `PHOENIX_COLLECTOR_ENDPOINT` incluye `/v1/traces`.
- `PHOENIX_PROJECT_NAME` coincide con el proyecto que miras en UI.
- `TELEMETRY_TRACES_ENABLED` no esta en `false`.
- La app arranco despues de cambiar env.
- El proceso flush-eo spans al cerrar. Con batch export, procesos cortos deben llamar `force_flush`;
  los scripts del repo lo hacen via `telemetry_runtime.aclose()`.

### Hay trace pero faltan spans del agente

Posibles causas:

- `AGENT_MODE=disabled`.
- Falta `OPENAI_API_KEY`.
- El Agent Framework no pudo habilitar instrumentation; revisar logs por
  `Could not enable Agent Framework OpenTelemetry`.
- La request fallo antes de `agent.run`, por ejemplo en attachments.

### El dataset curation no encuentra nada

Revisar:

- Proyecto correcto: `PHOENIX_PROJECT_NAME`.
- Tag correcto: `eval:candidate` vs `eval:dataset-ready`.
- Rango temporal.
- `conversation.turn` existe y tiene `tag.tags` o `sumampa.tags`.
- Si retaggeaste, buscar `conversation.tags`.

Comando de inspeccion:

```bash
PYTHONPATH=src uv run python scripts/export_tagged_conversations.py \
  --tag eval:dataset-ready \
  --json-array
```

### Phoenix eval falla con API key

- Los evaluadores deterministicos no necesitan OpenAI.
- El LLM judge si necesita `OPENAI_API_KEY`.
- `OPENAI_EVAL_MODEL` solo define modelo judge; no reemplaza `OPENAI_API_KEY`.

### Harbor no corre

Revisar:

```bash
harbor --help
docker info
```

Tambien:

- `OPENAI_API_KEY` seteada si `AGENT_MODE=openai`.
- Docker puede construir la imagen local.
- Puerto `6006` libre o Phoenix ya levantado.
- Odoo sidecar puede arrancar; primera corrida tarda mas.

### Harbor corre pero no sube annotations

Revisar:

- Existe `reward.json`.
- Existe `correlation.json`.
- `conversation_id` en `correlation.json` coincide con `session.id` del trace.
- El trace fue emitido despues de `run_started_at`.
- Los rewards son numericos.
- `PHOENIX_BASE_URL` y `PHOENIX_PROJECT_NAME` del runner apuntan al Phoenix correcto.

### Rewards parecen pegados a un trace viejo

El uploader ya filtra por `start_time=run_started_at` y toma el ultimo span matching. Igual, para
evitar ambiguedad:

- Usar `conversation_id` unico por task o por run.
- Incluir `git.sha` y `harbor.task_id` en metadata.
- No reutilizar fixtures con la misma session cuando estes comparando runs manualmente muy cercanos.

## 25. Checklist para mantener calidad

Antes de mergear un cambio de evaluacion:

- El score nuevo tiene nombre estable y significado claro.
- Hay al menos un test unitario del evaluator o verifier.
- Los cases nuevos tienen expected outputs revisados.
- Los Harbor tasks escriben `/logs/verifier/reward.json`.
- Los artifacts permiten debug sin entrar al contenedor.
- No se suben secretos ni binarios crudos a Phoenix.
- `uv run pytest`, `uv run ruff check .` y `uv run mypy src tests` pasan.

Antes de confiar en una mejora:

- Comparar experiment contra baseline.
- Abrir ejemplos con score bajo.
- Revisar traces, no solo promedios.
- Si el LLM judge contradice el deterministic evaluator, inspeccionar la rubric y el trace.
- Si Harbor falla pero Phoenix eval pasa, probablemente el problema esta en integracion real,
  seed de Odoo, Docker, networking o verifier.

## 26. Resumen operativo rapido

Phoenix local:

```bash
docker compose --profile observability up -d phoenix
```

Crear datasets:

```bash
PYTHONPATH=src uv run python scripts/bootstrap_phoenix_evals.py
```

Exportar conversaciones:

```bash
PYTHONPATH=src uv run python scripts/export_tagged_conversations.py \
  --tag eval:candidate \
  --json-array
```

Curar traces:

```bash
PYTHONPATH=src uv run python scripts/curate_phoenix_datasets.py \
  sumampa/dev/regression-failures \
  --tag eval:dataset-ready
```

Correr Phoenix evals:

```bash
PYTHONPATH=src uv run python scripts/run_phoenix_evals.py sumampa/dev/odoo-ops
```

Correr Harbor full-stack:

```bash
PYTHONPATH=src uv run python scripts/run_harbor_benchmarks.py
```

Ver Harbor UI:

```bash
harbor view benchmark_runs/harbor
```

Checks:

```bash
uv run ruff check .
uv run mypy src tests
uv run pytest
```
