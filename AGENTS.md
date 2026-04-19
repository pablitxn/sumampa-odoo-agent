# sumampa-odoo-agent

## Directivas locales

- Mantené arquitectura hexagonal estricta: `adapters -> application -> domain`, con `infrastructure` implementando puertos.
- No metas lógica Odoo en routers FastAPI ni en tools MCP; va en handlers/puertos/backends.
- El modo por defecto tiene que seguir siendo seguro: `dry-run` para Odoo y `stub` para el agent.
- Si se agregan operaciones nuevas, exponerlas de forma pareja en API y MCP cuando tenga sentido.
- Antes de tocar integración real con Odoo, preferí requests explícitos y payloads auditables sobre magia implícita.
- Si se activa Microsoft Agent Framework real, el import del provider tiene que quedar lazy para que el proyecto siga arrancando sin credenciales.
