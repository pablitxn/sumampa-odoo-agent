"""Attachment object storage integrations."""

from sumampa_odoo_agent.integrations.storage.factory import build_attachment_store
from sumampa_odoo_agent.integrations.storage.memory import InMemoryAttachmentObjectStore
from sumampa_odoo_agent.integrations.storage.s3 import S3AttachmentObjectStore

__all__ = [
    "InMemoryAttachmentObjectStore",
    "S3AttachmentObjectStore",
    "build_attachment_store",
]
