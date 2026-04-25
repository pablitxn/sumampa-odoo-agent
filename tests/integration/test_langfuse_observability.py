from __future__ import annotations

import os
from uuid import uuid4

import pytest
from langfuse import Langfuse

pytestmark = pytest.mark.integration


@pytest.fixture()
def langfuse_client() -> Langfuse:
    if not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get("LANGFUSE_SECRET_KEY"):
        pytest.skip("Langfuse credentials are not configured")
    client = Langfuse(
        base_url=os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000"),
        environment=os.environ.get("OBSERVABILITY_ENVIRONMENT", "integration"),
    )
    if not client.auth_check():
        pytest.skip("Langfuse auth check failed")
    return client


def test_langfuse_trace_ingestion_smoke(langfuse_client: Langfuse) -> None:
    with langfuse_client.start_as_current_observation(
        name="integration.trace.smoke",
        as_type="span",
        input={"ping": "pong"},
        metadata={"test": "langfuse_trace_ingestion_smoke"},
    ) as span:
        span.update(output={"ok": True})
    langfuse_client.flush()


def test_langfuse_score_creation_smoke(langfuse_client: Langfuse) -> None:
    session_id = f"integration-{uuid4()}"
    langfuse_client.create_score(
        name="task_success",
        value=1.0,
        session_id=session_id,
        data_type="NUMERIC",
        comment="Integration smoke score.",
    )
    langfuse_client.flush()


def test_langfuse_dataset_item_creation_smoke(langfuse_client: Langfuse) -> None:
    dataset_name = "sumampa/integration/smoke"
    try:
        langfuse_client.create_dataset(
            name=dataset_name,
            description="Integration smoke dataset for sumampa-odoo-agent.",
        )
    except Exception:
        pass
    langfuse_client.create_dataset_item(
        dataset_name=dataset_name,
        input={"text": "hola"},
        expected_output={"assistant_text": "hola"},
        metadata={"test": "langfuse_dataset_item_creation_smoke"},
    )
    langfuse_client.flush()
