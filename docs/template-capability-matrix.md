# Orchid MCP Template Capability Matrix

## Objetivo

Este template debe permitir iniciar un servicio tipo OpenAPI plugin y/o MCP server
con arquitectura hexagonal estricta, activando solo los recursos necesarios
(Postgres, Redis, MinIO/S3/R2, MongoDB, Qdrant, RabbitMQ, observability).

La personalizacion se hace con un script de setup que:
- selecciona modulos
- resuelve dependencias
- elimina lo no usado
- deja registro de modulos activos

## Reglas de Arquitectura Hexagonal (estrictas)

1. `domain` no importa nada de `application`, `adapters` ni `infrastructure`.
2. `application` depende solo de `domain` y de `domain.ports`.
3. `infrastructure` implementa puertos de `domain` y no contiene reglas de negocio.
4. `adapters` (API/MCP/CLI) solo traducen I/O a comandos/queries y delegan a handlers.
5. Ningun modulo opcional se importa de forma estatica desde archivos obligatorios.
6. Registro de routes/tools por `importlib` usando `enabled_modules`.

## Capas y Convencion de Nombres

- `domain/<module>/entities.py`
- `domain/<module>/value_objects.py`
- `domain/ports/<module>_ports.py`
- `application/<module>/commands.py`
- `application/<module>/queries.py`
- `application/<module>/use_cases.py`
- `application/<module>/handlers.py`
- `infrastructure/<module>/adapters.py`
- `adapters/api/routes/<module>.py`
- `adapters/mcp/tools/<module>.py`

## Matriz de Casos y Dummies

| Modulo | Recurso/Infra | Domain dummy | Use case dummy | Handler/Command dummy | Endpoint dummy | MCP tool dummy |
|---|---|---|---|---|---|---|
| `core` (obligatorio) | Ninguno | N/A | N/A | N/A | N/A | N/A |
| `postgres` | `orchid_commons.db.postgres` | `Workflow`, `WorkflowId` | `CreateWorkflowUseCase`, `ListWorkflowsUseCase` | `CreateWorkflowCommand`, `CreateWorkflowHandler` | `POST /api/v1/workflows`, `GET /api/v1/workflows` | `create_workflow`, `list_workflows` |
| `redis` | `orchid_commons.db.redis` | `CacheEntry` | `PutCacheEntryUseCase`, `GetCacheEntryUseCase` | `PutCacheEntryCommand`, `PutCacheEntryHandler` | `PUT /api/v1/cache/{key}`, `GET /api/v1/cache/{key}` | `cache_set`, `cache_get`, `cache_delete` |
| `blob` | `orchid_commons.blob.(minio/s3/r2)` | `AssetRef`, `BlobKey` | `UploadAssetUseCase`, `CreatePresignedUrlUseCase` | `UploadAssetCommand`, `UploadAssetHandler` | `POST /api/v1/assets/presign-upload`, `GET /api/v1/assets/{id}/download-url` | `asset_upload_url`, `asset_download_url` |
| `mongodb` | `orchid_commons.db.mongodb` | `DocumentNote` | `CreateDocumentUseCase`, `SearchDocumentsUseCase` | `CreateDocumentCommand`, `CreateDocumentHandler` | `POST /api/v1/documents`, `GET /api/v1/documents/search` | `create_document`, `search_documents` |
| `qdrant` | `orchid_commons.db.qdrant` | `VectorItem`, `Embedding` | `IndexVectorUseCase`, `SearchSimilarUseCase` | `IndexVectorCommand`, `IndexVectorHandler` | `POST /api/v1/vectors/index`, `POST /api/v1/vectors/search` | `index_vector`, `search_similar` |
| `rabbitmq` | `orchid_commons.db.rabbitmq` | `DomainEvent`, `EventEnvelope` | `PublishEventUseCase`, `ConsumeEventUseCase` | `PublishEventCommand`, `PublishEventHandler` | `POST /api/v1/events/publish` | `publish_event` |
| `observability` | `orchid_commons.observability.*` | `TraceContext` (VO) | `GetTelemetryStatusUseCase` | `GetTelemetryStatusHandler` | `GET /metrics`, `GET /health/telemetry` | `telemetry_ping` |

## Combinaciones Clave a Cubrir

1. `core` solamente
2. `core + postgres`
3. `core + postgres + redis`
4. `core + blob`
5. `core + blob + qdrant`
6. `core + mongodb + qdrant`
7. `core + postgres + rabbitmq`
8. `full`: todos los modulos

## Casos de Prueba Minimos por Modulo

- Unit:
  - entidades/value objects
  - contrato de puertos (fakes)
  - handlers/use cases
- Integration:
  - adapter de infraestructura contra recurso real (docker)
  - health checks por recurso
- E2E:
  - endpoint OpenAPI
  - tool MCP equivalente

## Diseño Para "Desenchufar" Modulos

1. Cada modulo vive en rutas propias (sin mezclar carpetas).
2. Registro de API/MCP por `enabled_modules` (sin imports fijos de modulos opcionales).
3. `config/enabled_modules.json` es la fuente de verdad.
4. El setup elimina paths declarados por modulo y tests asociados.
5. El setup reescribe `docker-compose.yml` y config para solo los recursos activos.

## Estructura Propuesta

```text
src/sumampa_odoo_agent/
  domain/
    postgres/
    redis/
    blob/
    mongodb/
    qdrant/
    rabbitmq/
    observability/
    ports/
  application/
    postgres/
    redis/
    blob/
    mongodb/
    qdrant/
    rabbitmq/
    observability/
  infrastructure/
    postgres/
    redis/
    blob/
    mongodb/
    qdrant/
    rabbitmq/
    observability/
  adapters/
    api/routes/
    mcp/
config/
  enabled_modules.json
template/
  module-manifest.json
scripts/
  setup_template.py
```
