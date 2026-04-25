from __future__ import annotations

from typing import Any

from sumampa_odoo_agent.services.metrics import AppMetrics, MetricAttributes, NoOpHistogram


class RecordingCounter:
    def __init__(self) -> None:
        self.records: list[tuple[int | float, MetricAttributes | None]] = []

    def add(self, amount: int | float, attributes: MetricAttributes | None = None) -> None:
        self.records.append((amount, attributes))


def test_app_metrics_use_only_bounded_labels() -> None:
    http_counter = RecordingCounter()
    conversation_counter = RecordingCounter()
    odoo_counter = RecordingCounter()
    metrics = AppMetrics(
        base_attributes={
            "service_name": "sumampa-odoo-agent",
            "deployment_environment": "test",
            "cluster": "local",
        },
        http_requests=http_counter,
        http_request_duration=NoOpHistogram(),
        conversation_turns=conversation_counter,
        conversation_turn_duration=NoOpHistogram(),
        odoo_operations=odoo_counter,
    )

    metrics.record_http_request(
        method="post",
        route="/api/v1/messages",
        status=200,
        duration_seconds=0.01,
    )
    metrics.record_conversation_turn(
        channel="whatsapp",
        mode="microsoft-agent-framework-openai",
        result="success",
        duration_seconds=0.02,
    )
    metrics.record_odoo_operation(
        operation="search_partners",
        mode="dry-run",
        result="success",
    )

    all_attributes: list[dict[str, Any]] = [
        dict(attributes or {})
        for _amount, attributes in [
            *http_counter.records,
            *conversation_counter.records,
            *odoo_counter.records,
        ]
    ]
    forbidden_labels = {"user_id", "session_id", "trace_id", "request_id"}
    assert all_attributes
    for attributes in all_attributes:
        assert forbidden_labels.isdisjoint(attributes)
        assert attributes["service_name"] == "sumampa-odoo-agent"
