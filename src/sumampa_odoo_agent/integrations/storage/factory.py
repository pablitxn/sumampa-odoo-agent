"""Attachment object store builders."""

from __future__ import annotations

import os

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.storage.memory import InMemoryAttachmentObjectStore
from sumampa_odoo_agent.integrations.storage.s3 import S3AttachmentObjectStore
from sumampa_odoo_agent.services.contracts import AttachmentObjectStore
from sumampa_odoo_agent.services.errors import ConfigurationError


async def build_attachment_store(settings: AppSettings) -> AttachmentObjectStore:
    """Build the configured attachment object store."""

    attachment_settings = settings.attachments
    mode = attachment_settings.store_mode
    if mode == "memory":
        return InMemoryAttachmentObjectStore(bucket_name=attachment_settings.bucket_name)
    if mode == "s3":
        access_key = (
            os.environ.get(attachment_settings.access_key_env_var) or attachment_settings.access_key
        )
        secret_key = (
            os.environ.get(attachment_settings.secret_key_env_var) or attachment_settings.secret_key
        )
        if not access_key or not secret_key:
            raise ConfigurationError(
                "Attachment store credentials are not configured.",
                code="attachment_store_credentials_missing",
                details={
                    "access_key_env_var": attachment_settings.access_key_env_var,
                    "secret_key_env_var": attachment_settings.secret_key_env_var,
                },
            )
        store = S3AttachmentObjectStore(
            bucket_name=attachment_settings.bucket_name,
            endpoint_url=attachment_settings.endpoint_url,
            access_key=access_key,
            secret_key=secret_key,
            region_name=attachment_settings.region_name,
        )
        await store.ensure_retention_policy(
            key_prefix=attachment_settings.key_prefix,
            ttl_seconds=attachment_settings.retention_ttl_seconds,
        )
        return store
    raise ConfigurationError(
        f"Unsupported attachments.store_mode: {mode}",
        code="unsupported_attachment_store_mode",
    )
