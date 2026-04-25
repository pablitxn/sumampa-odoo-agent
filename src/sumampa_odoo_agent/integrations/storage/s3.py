"""S3-compatible attachment object store for MinIO."""

from __future__ import annotations

import asyncio
import math
from typing import Any, cast
from urllib.parse import urlencode

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from sumampa_odoo_agent.services.errors import UpstreamServiceError
from sumampa_odoo_agent.services.models.attachments import StoredObjectReference

ATTACHMENT_STORE_FAILED_MESSAGE = "Could not store the attachment."
ATTACHMENT_RETENTION_POLICY_FAILED_MESSAGE = "Could not configure attachment retention."
ATTACHMENT_RETENTION_TAG_KEY = "sumampa-retention"
ATTACHMENT_RETENTION_TAG_VALUE = "enabled"
ATTACHMENT_RETENTION_RULE_ID = "sumampa-attachment-retention"


class S3AttachmentObjectStore:
    """S3-compatible object store client used for MinIO."""

    def __init__(
        self,
        *,
        bucket_name: str,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region_name: str,
    ) -> None:
        self._bucket_name = bucket_name
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    async def put_object(
        self,
        *,
        key: str,
        content_bytes: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> StoredObjectReference:
        def _put_object() -> dict[str, Any]:
            return cast(
                dict[str, Any],
                self._client.put_object(
                    Bucket=self._bucket_name,
                    Key=key,
                    Body=content_bytes,
                    ContentType=content_type,
                    Metadata=metadata,
                    Tagging=urlencode(
                        {ATTACHMENT_RETENTION_TAG_KEY: ATTACHMENT_RETENTION_TAG_VALUE}
                    ),
                ),
            )

        try:
            response = await asyncio.to_thread(_put_object)
        except (BotoCoreError, ClientError) as exc:
            raise UpstreamServiceError(
                ATTACHMENT_STORE_FAILED_MESSAGE,
                code="attachment_store_failed",
                details={"bucket": self._bucket_name, "key": key},
            ) from exc

        raw_etag = response.get("ETag")
        etag = raw_etag.strip('"') if isinstance(raw_etag, str) else None
        return StoredObjectReference(
            bucket=self._bucket_name,
            key=key,
            uri=f"s3://{self._bucket_name}/{key}",
            etag=etag,
        )

    async def ensure_retention_policy(
        self,
        *,
        key_prefix: str,
        ttl_seconds: int,
    ) -> None:
        """Ensure bucket lifecycle expiration for managed attachment objects."""

        expiration_days = max(1, math.ceil(ttl_seconds / 86400))
        normalized_prefix = key_prefix.strip("/")
        if normalized_prefix:
            normalized_prefix = f"{normalized_prefix}/"

        def _put_lifecycle_configuration() -> None:
            rules = self._load_lifecycle_rules()
            managed_rule = {
                "ID": ATTACHMENT_RETENTION_RULE_ID,
                "Status": "Enabled",
                "Filter": {
                    "And": {
                        "Prefix": normalized_prefix,
                        "Tags": [
                            {
                                "Key": ATTACHMENT_RETENTION_TAG_KEY,
                                "Value": ATTACHMENT_RETENTION_TAG_VALUE,
                            }
                        ],
                    }
                },
                "Expiration": {"Days": expiration_days},
            }
            rules = [
                rule
                for rule in rules
                if rule.get("ID") != ATTACHMENT_RETENTION_RULE_ID
            ]
            rules.append(managed_rule)
            self._client.put_bucket_lifecycle_configuration(
                Bucket=self._bucket_name,
                LifecycleConfiguration={"Rules": rules},
            )

        try:
            await asyncio.to_thread(_put_lifecycle_configuration)
        except (BotoCoreError, ClientError) as exc:
            raise UpstreamServiceError(
                ATTACHMENT_RETENTION_POLICY_FAILED_MESSAGE,
                code="attachment_retention_policy_failed",
                details={
                    "bucket": self._bucket_name,
                    "key_prefix": normalized_prefix,
                    "ttl_seconds": ttl_seconds,
                },
            ) from exc

    def _load_lifecycle_rules(self) -> list[dict[str, Any]]:
        try:
            response = self._client.get_bucket_lifecycle_configuration(
                Bucket=self._bucket_name,
            )
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"NoSuchLifecycleConfiguration", "NoSuchBucketLifecycle"}:
                return []
            raise
        rules = response.get("Rules", [])
        return cast(list[dict[str, Any]], rules)

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await asyncio.to_thread(close)
