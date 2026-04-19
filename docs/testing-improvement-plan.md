# Plan de Mejora de Testing, Coverage y Estructura de Tests

Fecha de baseline: **2026-02-11**
Ultima actualizacion: **2026-02-11**

## 1. Objetivo

Mejorar dos frentes en paralelo:

1. **Coverage real** (con metrica, umbral y foco en modulos criticos).
2. **Orden del arbol de tests** para que refleje la arquitectura del proyecto y escale sin caos.

## 2. Estado medido

### 2.1 Baseline inicial (historico)

Comando:

```bash
PYTHONPATH=src uv run --extra dev pytest -q --cov=src/sumampa_odoo_agent --cov-report=term-missing tests/unit tests/e2e
```

Resultado historico:

- `41 passed`
- **Coverage total: 75%** (75 aprox, 74.64 real al aplicar gate)

### 2.2 Estado actual (implementado)

Comando actual de referencia:

```bash
PYTHONPATH=src uv run --extra dev pytest -q --cov=src/sumampa_odoo_agent --cov-report=term-missing --cov-fail-under=85 tests/unit tests/e2e
```

Resultado actual:

- `96 passed`
- **Coverage total: 95.81%**

Conteo total recolectado (`tests` completo):

```bash
PYTHONPATH=src uv run --extra dev pytest --collect-only -q tests
```

- `98 tests collected` (incluye integration)

### 2.3 Estado integration con servicios (local)

Comando de referencia para validacion estricta:

```bash
REQUIRE_INTEGRATION_SERVICES=1 PYTHONPATH=src uv run --extra dev pytest -q -m integration tests/integration
```

Resultado:

- `2 passed`

## 3. Cambios implementados

### 3.1 CI y comandos

- CI ya no usa ruta inexistente (`tests/unit/sync`).
- CI ejecuta `tests/unit tests/e2e` con coverage.
- Gate activo en CI: `--cov-fail-under=85`.
- CI ejecuta `tests/integration` en job dedicado con servicios `postgres` + `redis`.
- CI ejecuta `ruff` completo sobre `src tests`.
- CI ejecuta `mypy` sobre todo `src/sumampa_odoo_agent`.
- `README.md` actualizado con comandos oficiales de:
  - unit + e2e
  - integration
  - coverage sin gate
  - coverage con gate (85)

### 3.2 Reorden del arbol de tests

Reorganizacion completada por capas, alineada a `src/sumampa_odoo_agent`.

Estructura activa:

```text
tests/
  unit/
    adapters/
      api/
      mcp/
    application/
      use_cases/
    infrastructure/
      runtime/
      db/
    scripts/
    test_main.py
  integration/
    db/
      postgres/
      redis/
  e2e/
    api/
    cli/
```

Se agregaron `__init__.py` en los nuevos directorios para evitar conflictos de import de `pytest` por basenames repetidos.

### 3.3 Cobertura agregada por tests nuevos

Implementado:

- MCP:
  - `tests/unit/adapters/mcp/test_server.py`
  - `tests/unit/adapters/mcp/test_tools_registry.py`
  - `tests/unit/adapters/mcp/tools/test_core.py`
  - `tests/unit/adapters/mcp/tools/test_postgres.py`
  - `tests/unit/adapters/mcp/tools/test_redis.py`
- API routes:
  - `tests/unit/adapters/api/routes/test_postgres.py`
  - `tests/unit/adapters/api/routes/test_redis.py`
- Runtime / main:
  - `tests/unit/infrastructure/runtime/test_container.py`
  - `tests/unit/infrastructure/runtime/test_state.py`
  - `tests/unit/test_main.py`
- Infrastructure repositories:
  - `tests/unit/infrastructure/db/postgres/test_workflow_repository.py`
  - `tests/unit/infrastructure/db/redis/test_cache_repository.py`

Tambien se ajusto `tests/e2e/cli/test_setup_prune_smoke.py` (calculo de `PROJECT_ROOT`) tras mover el archivo.

## 4. Hotspots: antes vs ahora

| Archivo | Antes | Ahora | Estado |
|---|---:|---:|---|
| `src/sumampa_odoo_agent/adapters/mcp/tools/core.py` | 0% | 100% | Resuelto |
| `src/sumampa_odoo_agent/adapters/mcp/tools/postgres.py` | 0% | 100% | Resuelto |
| `src/sumampa_odoo_agent/adapters/mcp/server.py` | 33% | 100% | Resuelto |
| `src/sumampa_odoo_agent/adapters/api/routes/redis.py` | 44% | 100% | Resuelto |
| `src/sumampa_odoo_agent/adapters/api/routes/postgres.py` | 58% | 100% | Resuelto |
| `src/sumampa_odoo_agent/infrastructure/runtime/container.py` | 64% | 100% | Resuelto |
| `src/sumampa_odoo_agent/infrastructure/runtime/state.py` | 92% | 100% | Resuelto |
| `src/sumampa_odoo_agent/main.py` | 0% | 100% | Resuelto |
| `src/sumampa_odoo_agent/infrastructure/db/postgres/workflow_repository.py` | 0% | 100% | Resuelto |
| `src/sumampa_odoo_agent/infrastructure/db/redis/cache_repository.py` | 0% | 100% | Resuelto |

Pendientes relevantes (no bloqueantes para gate actual):

- `src/sumampa_odoo_agent/infrastructure/runtime/modules.py` (90%)
- `src/sumampa_odoo_agent/infrastructure/blob/__init__.py` (0%, modulo no desarrollado aun)

## 5. Estado por etapas

### Etapa 1 (corta)

- [x] Subir de 75% a 80%
- [x] Corregir CI para tests reales
- [x] Activar gate de coverage

### Etapa 2 (media)

- [x] Subir de 80% a 85%
- [x] Cubrir MCP (`server.py` + `tools/*`) y routes opcionales
- [x] Reorganizar arbol unit por capas

### Etapa 3 (madurez)

- [x] Mantener gate >=85 en CI
- [x] Mantener coverage global >85
- [x] Job separado para integration en CI

## 6. Mapeo de migracion (ejecutado)

Movimientos principales completados:

- `tests/unit/core/test_application_bus.py` -> `tests/unit/application/test_bus.py`
- `tests/unit/core/test_api_error_handler.py` -> `tests/unit/adapters/api/test_error_handler.py`
- `tests/unit/core/test_mcp_errors.py` -> `tests/unit/adapters/mcp/test_errors.py`
- `tests/unit/core/test_module_resolution.py` -> `tests/unit/infrastructure/runtime/test_modules.py`
- `tests/unit/core/test_core_use_case_layer.py` -> `tests/unit/application/use_cases/test_core_layer.py`
- `tests/unit/core/test_core_use_cases.py` -> `tests/unit/application/use_cases/test_core.py`
- `tests/unit/postgres/test_postgres_use_case_layer.py` -> `tests/unit/application/use_cases/test_postgres_layer.py`
- `tests/unit/postgres/test_postgres_use_cases.py` -> `tests/unit/application/use_cases/test_postgres.py`
- `tests/unit/redis/test_redis_use_case_layer.py` -> `tests/unit/application/use_cases/test_redis_layer.py`
- `tests/unit/redis/test_redis_use_cases.py` -> `tests/unit/application/use_cases/test_redis.py`
- `tests/e2e/test_api_core.py` -> `tests/e2e/api/test_core.py`
- `tests/e2e/test_setup_prune_smoke.py` -> `tests/e2e/cli/test_setup_prune_smoke.py`
- `tests/integration/postgres/test_postgres_integration.py` -> `tests/integration/db/postgres/test_postgres_integration.py`
- `tests/integration/redis/test_redis_integration.py` -> `tests/integration/db/redis/test_redis_integration.py`

## 7. Backlog restante (actualizado)

### Prioridad P1 (completada)

1. [x] `tests/unit/infrastructure/runtime/test_state.py`
2. [x] Cobertura del guard de `src/sumampa_odoo_agent/main.py` (`if __name__ == "__main__":`)

### Prioridad P2

1. Tests de `requests` / `schemas` / `domain` para edge validations adicionales.
2. Definir si `infrastructure/blob` debe excluirse temporalmente de coverage o cubrirse con smoke tests.

## 8. Configuracion recomendada (estado actual)

### 8.1 Comando coverage oficial

```bash
PYTHONPATH=src uv run --extra dev pytest -q \
  --cov=src/sumampa_odoo_agent \
  --cov-report=term-missing \
  --cov-fail-under=85 \
  tests/unit tests/e2e
```

### 8.2 CI (`.github/workflows/ci.yml`)

Estado aplicado:

```yaml
- name: Run Ruff
  run: uv run ruff check src tests
- name: Run mypy
  run: PYTHONPATH=src uv run mypy src/sumampa_odoo_agent
- name: Run unit + e2e with coverage gate
  run: PYTHONPATH=src uv run pytest -q --cov=src/sumampa_odoo_agent --cov-report=term-missing --cov-fail-under=85 tests/unit tests/e2e
- name: Run integration tests
  env:
    REQUIRE_INTEGRATION_SERVICES: "1"
  run: PYTHONPATH=src uv run pytest -q -m integration tests/integration
```

## 9. Checklist ejecutable (actualizada)

- [x] CI ejecuta ruta real de tests (`tests/unit`, no `tests/unit/sync`)
- [x] Existe comando oficial de coverage en docs
- [x] Gate coverage activo en CI
- [x] Arbol `tests/unit` refleja capas de `src`
- [x] MCP server/tools cubiertos con unit tests
- [x] Routes postgres/redis cubiertas con unit tests
- [x] Runtime container cubierto
- [x] Runtime state cubierto
- [x] `main.py` cubierto (100%)
- [x] Integration separada por job en CI
- [x] Coverage total >= objetivo de etapa

## 10. Definicion de Done (estado)

Estado actual frente a DoD:

1. CI verde con coverage gate activo: **SI**
2. Arbol de tests ordenado por capas: **SI**
3. Coverage global >= meta acordada: **SI** (95.81%)
4. Hotspots P0/P1 principales sin 0%: **SI**
5. Integracion separada en pipeline: **SI**
