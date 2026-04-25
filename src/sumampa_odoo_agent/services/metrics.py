"""Application metrics with stable bounded labels."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from opentelemetry import metrics
from opentelemetry.metrics import Observation as MetricObservation

from sumampa_odoo_agent.config import AppSettings

MetricAttributes = dict[str, str | int | float | bool]


class CounterLike(Protocol):
    def add(self, amount: int | float, attributes: MetricAttributes | None = None) -> None:
        """Add a value to the counter."""


class HistogramLike(Protocol):
    def record(self, amount: int | float, attributes: MetricAttributes | None = None) -> None:
        """Record a value in the histogram."""


class NoOpCounter:
    def add(self, amount: int | float, attributes: MetricAttributes | None = None) -> None:
        del amount, attributes


class NoOpHistogram:
    def record(self, amount: int | float, attributes: MetricAttributes | None = None) -> None:
        del amount, attributes


class AppMetrics:
    """Small metric facade that prevents high-cardinality labels from leaking out."""

    def __init__(
        self,
        *,
        base_attributes: MetricAttributes,
        http_requests: CounterLike,
        http_request_duration: HistogramLike,
        conversation_turns: CounterLike,
        conversation_turn_duration: HistogramLike,
        odoo_operations: CounterLike,
    ) -> None:
        self._base_attributes = base_attributes
        self._http_requests = http_requests
        self._http_request_duration = http_request_duration
        self._conversation_turns = conversation_turns
        self._conversation_turn_duration = conversation_turn_duration
        self._odoo_operations = odoo_operations

    @classmethod
    def from_settings(cls, settings: AppSettings) -> AppMetrics:
        """Create app metrics from the active global OpenTelemetry meter provider."""

        meter = metrics.get_meter("sumampa_odoo_agent.metrics", settings.service.version)
        base_attributes: MetricAttributes = {
            "service_name": settings.telemetry.service_name,
            "deployment_environment": settings.telemetry.environment,
            "cluster": settings.telemetry.cluster,
        }

        def service_info_callback(_options: Any) -> list[MetricObservation]:
            return [
                MetricObservation(
                    1,
                    attributes={
                        **base_attributes,
                        "service_version": settings.service.version,
                    },
                )
            ]

        meter.create_observable_gauge(
            "sumampa_service_info",
            callbacks=[service_info_callback],
            description="Static identity information for the Sumampa Odoo agent service.",
            unit="1",
        )
        return cls(
            base_attributes=base_attributes,
            http_requests=meter.create_counter(
                "sumampa_http_requests_total",
                description="Total HTTP requests handled by the API.",
                unit="1",
            ),
            http_request_duration=meter.create_histogram(
                "sumampa_http_request_duration_seconds",
                description="HTTP request duration in seconds.",
                unit="s",
            ),
            conversation_turns=meter.create_counter(
                "sumampa_conversation_turns_total",
                description="Total conversation turns processed by the service.",
                unit="1",
            ),
            conversation_turn_duration=meter.create_histogram(
                "sumampa_conversation_turn_duration_seconds",
                description="Conversation turn duration in seconds.",
                unit="s",
            ),
            odoo_operations=meter.create_counter(
                "sumampa_odoo_operations_total",
                description="Total Odoo gateway operations.",
                unit="1",
            ),
        )

    @classmethod
    def disabled(cls, settings: AppSettings) -> AppMetrics:
        return cls(
            base_attributes={
                "service_name": settings.telemetry.service_name,
                "deployment_environment": settings.telemetry.environment,
                "cluster": settings.telemetry.cluster,
            },
            http_requests=NoOpCounter(),
            http_request_duration=NoOpHistogram(),
            conversation_turns=NoOpCounter(),
            conversation_turn_duration=NoOpHistogram(),
            odoo_operations=NoOpCounter(),
        )

    def start_timer(self) -> Callable[[], float]:
        started_at = time.perf_counter()
        return lambda: time.perf_counter() - started_at

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status: int,
        duration_seconds: float,
    ) -> None:
        attributes = self._attrs(
            method=method.upper(),
            route=_bounded_route(route),
            status=status,
        )
        self._http_requests.add(1, attributes=attributes)
        self._http_request_duration.record(duration_seconds, attributes=attributes)

    def record_conversation_turn(
        self,
        *,
        channel: str,
        mode: str,
        result: str,
        duration_seconds: float,
    ) -> None:
        attributes = self._attrs(
            channel=_bounded_value(channel),
            mode=_bounded_value(mode),
            result=_bounded_value(result),
        )
        self._conversation_turns.add(1, attributes=attributes)
        self._conversation_turn_duration.record(duration_seconds, attributes=attributes)

    def record_odoo_operation(self, *, operation: str, mode: str, result: str) -> None:
        self._odoo_operations.add(
            1,
            attributes=self._attrs(
                operation=_bounded_value(operation),
                mode=_bounded_value(mode),
                result=_bounded_value(result),
            ),
        )

    def _attrs(self, **attributes: str | int | float | bool) -> MetricAttributes:
        return {**self._base_attributes, **attributes}


def _bounded_route(route: str | None) -> str:
    if not route:
        return "unmatched"
    if "?" in route:
        return route.split("?", 1)[0]
    return route


def _bounded_value(value: str | None) -> str:
    if not value:
        return "unknown"
    return value
