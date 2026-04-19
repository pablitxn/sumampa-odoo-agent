# LLM Specs

Especificaciones versionadas para interacción con modelos.

- `purchase_chat/decide_system.md`: instrucciones del turno de decisión estructurada.
- `purchase_chat/reply_system.md`: instrucciones del turno de redacción.
- `invoice_extraction/purchase_invoice.md`: prompt base para extraer facturas de compra.
- `agent/system.md`: system prompt base del agent MFA/OpenAI.

Los schemas estructurados asociados siguen viviendo en código:

- `application/requests/purchase_chat.py`
- `application/requests/odoo.py`
- `application/requests/agent.py`
