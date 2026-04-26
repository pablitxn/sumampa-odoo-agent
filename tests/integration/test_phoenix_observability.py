from __future__ import annotations

import os
from uuid import uuid4

import pytest
from opentelemetry import trace
from phoenix.client import Client
from phoenix.client.experiments import run_experiment
from phoenix.otel import register

pytestmark = pytest.mark.integration


@pytest.fixture()
def phoenix_client() -> Client:
    if os.environ.get("RUN_PHOENIX_INTEGRATION") != "1":
        pytest.skip("Phoenix integration smoke tests are disabled")
    return Client(
        base_url=os.environ.get("PHOENIX_BASE_URL", "http://localhost:6006"),
        api_key=os.environ.get(os.environ.get("PHOENIX_API_KEY_ENV_VAR", "PHOENIX_API_KEY")),
    )


def test_phoenix_trace_ingestion_and_annotation_smoke(phoenix_client: Client) -> None:
    project_name = f"sumampa-integration-{uuid4()}"
    tracer_provider = register(
        endpoint=os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces"),
        project_name=project_name,
        protocol="http/protobuf",
        batch=False,
        auto_instrument=False,
    )
    tracer = trace.get_tracer("sumampa.integration")
    with tracer.start_as_current_span("integration.trace.smoke") as span:
        span.set_attribute("openinference.span.kind", "CHAIN")
        span.set_attribute("input.value", '{"ping": "pong"}')
        span.set_attribute("output.value", '{"ok": true}')
        span_id = f"{span.get_span_context().span_id:016x}"
    tracer_provider.force_flush()

    phoenix_client.spans.add_span_annotation(
        span_id=span_id,
        annotation_name="task_success",
        annotator_kind="CODE",
        score=1.0,
        explanation="Integration smoke score.",
    )


def test_phoenix_dataset_creation_and_experiment_dry_run(phoenix_client: Client) -> None:
    dataset_name = f"sumampa/integration/smoke/{uuid4()}"
    dataset = phoenix_client.datasets.create_dataset(
        name=dataset_name,
        dataset_description="Integration smoke dataset for sumampa-odoo-agent.",
        inputs=[{"text": "hola"}],
        outputs=[{"assistant_text": "hola"}],
        metadata=[{"test": "phoenix_dataset_creation_and_experiment_dry_run"}],
    )

    experiment = run_experiment(
        dataset=dataset,
        task=lambda input: {"assistant_text": input["text"]},
        evaluators=[lambda output, expected: float(output == expected)],
        experiment_name=f"{dataset_name}/dry-run",
        dry_run=True,
        print_summary=False,
        client=phoenix_client,
    )

    assert experiment is not None
