# Demo WhatsApp

Mini aplicacion estatica para probar el flujo conversacional como si el usuario estuviera en WhatsApp.

## Uso rapido

Abrir `demo/index.html` en el browser. La pantalla siempre envia mensajes al backend local
configurado en el panel.

El pill del panel consulta `GET /health` sobre el mismo origen del endpoint configurado.

## Contra el backend local

Levantar la API:

```bash
ATTACHMENT_STORE_MODE=memory uv run sumampa_odoo_agent --reload
```

Endpoint default:

```text
http://127.0.0.1:8000/api/v1/messages
```

El demo envia el contrato actual de la API:

```json
{
  "conversation_id": "whatsapp-demo-...",
  "channel": "whatsapp",
  "user_id": "5491123456789",
  "text": "Necesito cargar esta factura en Odoo.",
  "eval_tags": ["eval:candidate", "eval:invoice-upload"],
  "attachments": [
    {
      "filename": "factura.jpg",
      "mime_type": "image/jpeg",
      "content_base64": "<base64>"
    }
  ],
  "context": {
    "demo": true,
    "transport_profile": "whatsapp-mobile"
  }
}
```

`ATTACHMENT_STORE_MODE=memory` evita depender de MinIO para pruebas rapidas con adjuntos.

Los shortcuts de facturas cargan una imagen mock en el composer para simular el caso
`mensaje + imagen` de WhatsApp.

El panel permite seleccionar varios `Eval tags` de un catalogo fijo. Cada toggle envia
un evento liviano al backend para dejar rastro en Phoenix sin invocar al agente, y
cada turno envia el array `eval_tags`. Usar `eval:discarded` para marcar conversaciones
que no deberian entrar en datasets.
