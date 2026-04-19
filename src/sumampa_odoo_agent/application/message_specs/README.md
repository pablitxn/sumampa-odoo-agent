# Message Specs

Catálogos versionados para copy canónico que no debería quedar embebido en el código.

- Usar esto para warnings, blockers, assumptions y mensajes de dominio que viajan en payloads o resultados.
- No usarlo para prompts/instrucciones del LLM; eso vive en `application/llm_specs/`.
- Por ahora no resuelve i18n; sólo abstrae copy fuera del source code.

Catálogos actuales:

- `purchase_invoice.json`
- `odoo_validation.json`
