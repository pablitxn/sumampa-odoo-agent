"""Unit tests for attachment object storage integrations."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from sumampa_odoo_agent.integrations.storage.s3 import (
    ATTACHMENT_RETENTION_RULE_ID,
    S3AttachmentObjectStore,
)


class _FakeS3Client:
    def __init__(self) -> None:
        self.put_object_kwargs: dict[str, Any] | None = None
        self.lifecycle_configuration: dict[str, Any] | None = None

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.put_object_kwargs = kwargs
        return {"ETag": '"etag-1"'}

    def get_bucket_lifecycle_configuration(self, **_: Any) -> dict[str, Any]:
        raise ClientError(
            {"Error": {"Code": "NoSuchLifecycleConfiguration"}},
            "GetBucketLifecycleConfiguration",
        )

    def put_bucket_lifecycle_configuration(self, **kwargs: Any) -> None:
        self.lifecycle_configuration = kwargs

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_s3_store_tags_objects_for_retention(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeS3Client()
    monkeypatch.setattr(
        "sumampa_odoo_agent.integrations.storage.s3.boto3.client",
        lambda *args, **kwargs: fake_client,
    )
    store = S3AttachmentObjectStore(
        bucket_name="attachments",
        endpoint_url="http://minio:9000",
        access_key="access",
        secret_key="secret",
        region_name="us-east-1",
    )

    stored = await store.put_object(
        key="attachments/file.txt",
        content_bytes=b"hello",
        content_type="text/plain",
        metadata={"filename": "file.txt"},
    )

    assert stored.uri == "s3://attachments/attachments/file.txt"
    assert fake_client.put_object_kwargs is not None
    assert fake_client.put_object_kwargs["Tagging"] == "sumampa-retention=enabled"


@pytest.mark.asyncio
async def test_s3_store_configures_lifecycle_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeS3Client()
    monkeypatch.setattr(
        "sumampa_odoo_agent.integrations.storage.s3.boto3.client",
        lambda *args, **kwargs: fake_client,
    )
    store = S3AttachmentObjectStore(
        bucket_name="attachments",
        endpoint_url="http://minio:9000",
        access_key="access",
        secret_key="secret",
        region_name="us-east-1",
    )

    await store.ensure_retention_policy(key_prefix="attachments", ttl_seconds=604800)

    assert fake_client.lifecycle_configuration is not None
    rules = fake_client.lifecycle_configuration["LifecycleConfiguration"]["Rules"]
    managed_rule = next(rule for rule in rules if rule["ID"] == ATTACHMENT_RETENTION_RULE_ID)
    assert managed_rule["Expiration"]["Days"] == 7
    assert managed_rule["Filter"]["And"]["Prefix"] == "attachments/"
    assert managed_rule["Filter"]["And"]["Tags"] == [
        {"Key": "sumampa-retention", "Value": "enabled"}
    ]
