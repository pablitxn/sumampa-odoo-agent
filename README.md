# sumampa-odoo-agent

POC inicial para operar Odoo con una app Python basada en FastAPI, límites hexagonales y un wrapper sobre Microsoft Agent Framework.

## Qué trae hoy

- API FastAPI con `health` y `capabilities`
- Endpoints Odoo para buscar entidades operativas y prevalidar facturación ARCA/AFIP antes de crear documentos
- Flujo inicial de factura de compra por una o varias fotos para proponer costos, precios y movimientos de stock
- Servidor MCP opcional con las mismas operaciones
- Backend `dry-run` por defecto para trabajar sin tocar Odoo real
- Agent con Microsoft Agent Framework listo para usar tools de lookup y alta sobre Odoo cuando se configure `OPENAI_API_KEY`
- Extracción de facturas de compra con OpenAI `gpt-5.4`
- Chat de compras con OpenAI `gpt-5.4` para small talk, clarificaciones y confirmaciones guiadas

## Stack

- Python 3.11+
- FastAPI
- MCP Python SDK
- Microsoft `agent-framework`
- `httpx` para JSON-RPC contra Odoo

## Estructura

- `src/sumampa_odoo_agent/domain` contratos y puertos
- `src/sumampa_odoo_agent/application` requests, handlers y buses
- `src/sumampa_odoo_agent/application/llm_specs` prompts/schemas textuales versionados para agent, extracción y chat
- `src/sumampa_odoo_agent/application/message_specs` copy canónico versionado para warnings, blockers y mensajes de dominio no-LLM
- `src/sumampa_odoo_agent/infrastructure` runtime, Odoo backend y agent backend
- `src/sumampa_odoo_agent/adapters` HTTP y MCP

## Desarrollo local

```bash
cd ~/repos/sumampa-odoo-agent
uv sync --extra dev
uv run sumampa_odoo_agent --reload
```

Con eso levanta en `http://127.0.0.1:8000`.

Para correr tests dentro del entorno del proyecto:

```bash
uv run --python 3.12 python -m pytest
```

Para correr la extracción real de facturas contra OpenAI usando los fixtures locales:

```bash
cd ~/repos/sumampa-odoo-agent
PYTHONPATH=src uv run pytest -q -m integration tests/integration/test_purchase_invoice_extraction_openai.py
```

Los fixtures de facturas quedaron en `tests/integration/fixtures/purchase_invoices/`. Esta suite usa la `OPENAI_API_KEY` del entorno y consume API real.

Para refrescar los snapshots JSON a partir de esas mismas imágenes:

```bash
cd ~/repos/sumampa-odoo-agent
PYTHONPATH=src uv run python scripts/generate_purchase_invoice_extraction_snapshots.py
```

Los snapshots quedan en `tests/integration/fixtures/purchase_invoice_extractions/`.

Para validar propuesta comercial, matching y gating de `human in the loop` sin volver a consumir API:

```bash
cd ~/repos/sumampa-odoo-agent
PYTHONPATH=src uv run pytest -q -m integration \
  tests/integration/test_purchase_invoice_proposals_from_snapshots.py \
  tests/integration/test_purchase_chat_human_loop.py
```

Para levantar un Odoo 19 local alineado al tenant real y seedear fixtures de retrieval:

```bash
cd ~/repos/sumampa-odoo-agent
docker compose -f docker-compose.odoo19.yml up -d
PYTHONPATH=src uv run python scripts/bootstrap_odoo_integration.py
```

La DB local queda en `sumampa_integration`, corre en `http://127.0.0.1:8069` y carga partners/productos/aliases suficientes para probar resolución humana con typos y `product.supplierinfo`.

Además, el runtime ahora puede persistir memoria local de resoluciones humanas confirmadas en `.data/purchase_resolution_memory.json` para reutilizar aliases de proveedor y descripciones de línea ya validadas.

Para resetear el stack local y volver a un seed limpio, borrando también la memoria de resoluciones humanas:

```bash
cd ~/repos/sumampa-odoo-agent
uv run python scripts/reset_odoo_integration.py
```

Si querés hacer todo junto para la demo local de compras, con un solo comando:

```bash
cd ~/repos/sumampa-odoo-agent
uv run python scripts/run_purchase_chat_demo.py
```

Eso hace:

- reset duro del Odoo local,
- reseed de partners/productos/aliases,
- levanta la API en `ORCHID_ENV=integration`,
- deja la demo disponible en `http://127.0.0.1:8000/demo/purchase-invoices`.

Por default fuerza `ORCHID_SESSION_STORE_MODE=memory` para no depender además de Postgres/Redis del app. Si querés conservar sesiones híbridas:

```bash
cd ~/repos/sumampa-odoo-agent
uv run python scripts/run_purchase_chat_demo.py --session-store-mode hybrid
```

Si sólo querés rebootstrapear sobre el stack ya levantado, sin tirar volúmenes:

```bash
cd ~/repos/sumampa-odoo-agent
uv run python scripts/reset_odoo_integration.py --soft
```

Y si querés el one-shot pero sin tirar volúmenes:

```bash
cd ~/repos/sumampa-odoo-agent
uv run python scripts/run_purchase_chat_demo.py --soft-reset
```

Para inspeccionar rápido los IDs/defaults del entorno local seedado:

```bash
cd ~/repos/sumampa-odoo-agent
PYTHONPATH=src uv run python scripts/describe_odoo_integration.py
```

Eso te devuelve, entre otras cosas:

- `journal_id` de compras
- `picking_type_id` de recepciones
- `location_id` de proveedores
- `location_dest_id` de `WH/Stock`
- partners/productos seedados
- aliases presentes en `product.supplierinfo`

Para correr la suite JSON-RPC real contra ese Odoo 19:

```bash
cd ~/repos/sumampa-odoo-agent
RUN_ODOO19_INTEGRATION=1 PYTHONPATH=src uv run pytest -q -m integration \
  tests/integration/test_odoo_jsonrpc_retrieval.py \
  tests/integration/test_odoo19_purchase_chat_flow.py
```

Si querés levantar la API contra ese stack en vez de `dry-run`:

```bash
cd ~/repos/sumampa-odoo-agent
ORCHID_ENV=integration uv run sumampa_odoo_agent --reload
```

## Configuración

- `config/appsettings.development.json` usa `dry-run`, extracción OpenAI y deja el módulo agent deshabilitado por defecto
- `config/appsettings.integration.json` apunta a un Odoo 19 local por `jsonrpc`, usa extracción/chat reales, activa persistencia híbrida de sesiones y deja el módulo agent deshabilitado por defecto
- `config/appsettings.production.json` cambia a `jsonrpc` para Odoo, `openai` para el agent, `openai` para extracción de facturas, `openai` para el planner conversacional y persistencia híbrida de sesiones
- `.env.example` documenta la variable mínima para el provider
- Las instrucciones de sistema y prompts versionados viven en `src/sumampa_odoo_agent/application/llm_specs/`
- Overrides útiles por entorno: `ORCHID_INVOICE_EXTRACTION_MODE`, `ORCHID_INVOICE_EXTRACTION_PROMPT_SPEC`, `ORCHID_PURCHASE_CHAT_MODE`, `ORCHID_PURCHASE_CHAT_DECIDE_SYSTEM_SPEC`, `ORCHID_PURCHASE_CHAT_REPLY_SYSTEM_SPEC`, `ORCHID_AGENT_MODE`, `ORCHID_AGENT_SYSTEM_PROMPT_SPEC`, `ORCHID_AGENT_SYSTEM_PROMPT_OVERRIDE`, `ORCHID_ODOO_MODE`, `ORCHID_ODOO_BASE_URL`, `ORCHID_ODOO_DATABASE`, `ORCHID_ODOO_USERNAME`, `ORCHID_ODOO_PASSWORD`, `ORCHID_PURCHASE_RESOLUTION_MEMORY_PATH`, `ORCHID_SESSION_STORE_MODE`, `ORCHID_SESSION_STORE_POSTGRES_DSN`, `ORCHID_SESSION_STORE_REDIS_URL`, `ORCHID_SESSION_STORE_REDIS_TTL_SECONDS`

## Persistencia de sesiones

- `purchase_chat` persiste `stage`, contexto, propuesta y resultados parciales.
- El módulo `agent` persiste el `AgentSession` serializado del Microsoft Agent Framework.
- En modo `hybrid`, Postgres es la fuente de verdad y Redis funciona como cache `write-through`.
- Si reiniciás la API con el mismo `session_id`, el flujo puede retomar donde había quedado.
- En `development`, el default sigue siendo `memory` para no exigir Postgres/Redis siempre.
- Para probar persistencia híbrida localmente, levantá primero:

```bash
cd ~/repos/sumampa-odoo-agent
docker compose up -d postgres redis
ORCHID_SESSION_STORE_MODE=hybrid uv run sumampa_odoo_agent --reload
```

Para validar el store híbrido contra Postgres+Redis reales:

```bash
cd ~/repos/sumampa-odoo-agent
RUN_SESSION_STORE_INTEGRATION=1 PYTHONPATH=src uv run pytest -q tests/integration/db
```

## Capacidades actuales

- Buscar partners por nombre, email o CUIT
- Buscar productos por nombre o SKU
- Buscar diarios, impuestos, tipos de picking y ubicaciones
- Prevalidar borradores de factura y remito antes de crear registros
- Prevalidar una factura electrónica argentina con chequeos de CUIT, punto de venta, letra A/B/C y datos mínimos del receptor
- Analizar una o varias fotos de una factura de proveedor y proponer actualización de costo, precio sugerido con markup y stock esperado
- Aplicar una propuesta de compra para preparar writes sobre productos y factura de compra
- La extracción hoy puede correr directo con OpenAI usando schema estructurado; el contrato interno permite reemplazarla más adelante por OCR barato
- El chat de compras puede usar OpenAI para responder natural y clasificar intenciones sin perder el gating explícito antes de escribir en Odoo
- Crear proveedores
- Crear productos
- Crear facturas
- Crear remitos
- Ejecutar un agent con `session_id` opcional y tools del dominio Odoo

## Demo conversacional

Para probar el flujo conversacional con OpenAI real, con el agente manejando todo el workflow:

```bash
cd ~/repos/sumampa-odoo-agent
ORCHID_INVOICE_EXTRACTION_MODE=openai ORCHID_AGENT_MODE=openai ORCHID_ODOO_MODE=dry-run uv run sumampa_odoo_agent --reload
```

Después abrí `http://127.0.0.1:8000/demo/purchase-invoices`.

Podés:

1. saludar o hablar natural;
2. subir una o varias fotos de la misma factura;
3. usar `Cargar defaults locales` para autocompletar journal/picking/locations del backend activo;
4. si hace falta, resolver proveedor/productos con respuestas tipo `proveedor 102`, `linea 2 producto 201`, `linea 3 nuevo`, `crear proveedor`, `linea 3 crear` o `crear nuevos`;
5. confirmar la carga de la factura;
6. si corresponde, confirmar la recepción de stock;
7. confirmar la actualización de precios.

Para correr el flujo completo sin UI ni WhatsApp, usando snapshots contra el Odoo local:

```bash
cd ~/repos/sumampa-odoo-agent
PYTHONPATH=src uv run python scripts/replay_agent_purchase_flow.py --create-stock-receipt --confirm-prices
```

Por defecto el replay usa `molinos_1`, que hoy recorre factura + recepción + actualización de costo/precio sin intervención manual adicional. Si querés otro snapshot:

```bash
cd ~/repos/sumampa-odoo-agent
PYTHONPATH=src uv run python scripts/replay_agent_purchase_flow.py arcor_1 --create-stock-receipt --confirm-prices
```

Si querés que el replay marque faltantes como nuevos y los cree localmente:

```bash
cd ~/repos/sumampa-odoo-agent
PYTHONPATH=src uv run python scripts/replay_agent_purchase_flow.py algun_fixture --allow-new-supplier --allow-new-products
```

## Flujo conversacional actual

El agente mantiene un workflow activo de compra y estas etapas se derivan del estado actual, no de una máquina conversacional hardcodeada:

- `awaiting_invoice`: espera saludo o imagen.
- `awaiting_resolution`: hay proveedor o productos que requieren revisión humana.
- `awaiting_invoice_confirmation`: la resolución ya está aceptada y falta confirmar la factura.
- `awaiting_stock_confirmation`: la factura ya quedó cargada y falta decidir si se genera la recepción.
- `awaiting_price_confirmation`: la factura ya quedó preparada/cargada y falta decidir cambios de precios.
- `completed`: flujo cerrado.

La propuesta de factura ahora incluye:

- `supplier_resolution`: candidatos de proveedor encontrados en Odoo.
- `product_resolution` por cada línea: candidatos de producto, match sugerido o línea nueva.
- `needs_user_resolution`: marca si todavía hace falta intervención humana antes de confirmar la factura.
- Si un proveedor o producto queda marcado como `new`, el chat permite alta guiada local con `crear proveedor`, `linea N crear` o `crear nuevos`.
- Antes de crear la factura, el backend revisa duplicados por proveedor + número/ref + fecha y frena la escritura si encuentra una compra parecida.
- Al confirmar la factura, el sistema aprende aliases humanos confirmados y puede reutilizarlos en próximas facturas.
- En modo `jsonrpc` local, el apply ya normaliza fechas al formato que espera Odoo 19, usa payloads de recepción compatibles con `stock.picking`/`stock.move` actuales y resuelve `product.template -> product.product` también en los endpoints genéricos de factura/remito.
- El seed local cubre las líneas reales de los snapshots actuales para poder resetear la DB y rejugar facturas como `molinos_1` y `arcor_1` sin depender de altas manuales.

## Próximos pasos naturales

1. Conectar las operaciones Odoo a modelos/campos reales del tenant objetivo.
2. Endurecer los fixtures reales de OCR/LLM con más casos sucios y ambiguos.
3. Enchufar tools reales de Microsoft Agent Framework en vez del wrapper de ejecución simple.
4. Agregar validaciones de negocio específicas para productos, facturas C/A/B y remitos.
