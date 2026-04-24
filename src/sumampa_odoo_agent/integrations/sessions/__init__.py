"""Session persistence integrations."""

from sumampa_odoo_agent.integrations.sessions.factory import build_session_store
from sumampa_odoo_agent.integrations.sessions.hybrid import HybridSessionStore
from sumampa_odoo_agent.integrations.sessions.memory import InMemorySessionStore
from sumampa_odoo_agent.integrations.sessions.postgres import PostgresSessionStore
from sumampa_odoo_agent.integrations.sessions.redis import RedisSessionCache

__all__ = [
    "HybridSessionStore",
    "InMemorySessionStore",
    "PostgresSessionStore",
    "RedisSessionCache",
    "build_session_store",
]
