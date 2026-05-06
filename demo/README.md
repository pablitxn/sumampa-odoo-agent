# Demo WhatsApp Sales

## Uso rapido

Abrir `http://127.0.0.1:8000/demo/` con la API local levantada. La pantalla envia
mensajes a `/demo/api/messages`, selecciona presets versionados y muestra el estado
mock mutable del lead.

El pill del panel consulta `GET /health` sobre el mismo origen del endpoint configurado.

## Contra el backend local

Levantar la API:

```bash
ATTACHMENT_STORE_MODE=memory uv run sumampa_odoo_agent --reload
```

Endpoint default:

```text
http://127.0.0.1:8000/demo/api/messages
```

El demo envia el contrato de ventas mock:

```json
{
  "conversation_id": "whatsapp-demo-...",
  "user_id": "demo-user-001",
  "scenario_id": "interested-lead",
  "scenario_params": {
    "commercial_state": "interested",
    "activation_link_status": "available"
  },
  "text": "Me interesa comprar por mayor, como seguimos?",
  "eval_tags": ["eval:candidate"],
  "context": {
    "demo": true,
    "demo_sales": true,
    "transport_profile": "whatsapp-mobile"
  }
}
```

`GET /demo/api/scenarios` devuelve presets y parametros para los dropdowns. El primer
turno clona el fixture seleccionado; los turnos siguientes reutilizan el estado en memoria
por `conversation_id`. Cambiar escenario o parametros inicia una conversacion nueva.

El fixture `New Odoo lead, empty states` representa el caso desde cero: el lead ya existe,
pero estado comercial, pago, suscripcion, activacion, rol y follow-up arrancan vacios.
Los dropdowns aceptan `Unset` para mantener esos campos en `null` y ver como el agente los
va poblando mediante tools.

El panel `Evals preset` permite seleccionar los tags que definen el proposito del ejemplo.
Es obligatorio elegir al menos uno antes del primer mensaje. El preset viaja en el
`eval_tags` del turno y queda bloqueado cuando empieza la conversacion para que Phoenix
reciba una etiqueta estable desde el trace inicial. Usar `eval:discarded` para marcar
conversaciones que no deberian entrar en datasets.

Los traces `demo.message` incluyen escenario, version, parametros, estado inicial,
estado antes/despues, transcript, tool calls, notas privadas y mensajes publicos. La
curacion sigue requiriendo `eval:dataset-ready`; el output del agente queda como evidencia
candidata hasta que alguien revise el expected output.

## Export JSONL local

El boton `Export JSONL` exporta la conversacion actual sin pasar por Phoenix:

```text
GET /demo/api/conversations/{conversation_id}/export.jsonl
```

El archivo sale como JSONL, una linea por turno. Cada item incluye `input`,
`candidate_output`, `expected_output: null` y metadata con
`requires_expected_output_review=true`, tool ledger, mutaciones de estado y transcript.

El bloque `Manual feedback` es retroactivo: permite guardar outcome tags manuales y una
nota opcional sin cambiar el preset inicial. Ese feedback queda en el trace
`conversation.feedback` y tambien en la metadata del JSONL exportado.

Los tags del demo estan pensados para dataset curation:

- `eval:*`: lifecycle del ejemplo (`candidate`, `needs-review`, `dataset-ready`, `regression`, `discarded`).
- `sales:*`: tarea comercial cubierta (`new-lead`, `qualification`, `activation`, `payment`, `follow-up`, `opt-out`, `human-review`).
- `risk:*`: casos adversariales como `prompt-injection`.
- `quality:*`: evidencia estructural como `state-mutation` o `multi-turn`.
