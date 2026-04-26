"""Conversation service used by the WhatsApp-facing bridge API."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sumampa_odoo_agent.services.attachments import AttachmentIngestionService
from sumampa_odoo_agent.services.contracts import AgentRuntime, SessionStore
from sumampa_odoo_agent.services.metrics import AppMetrics
from sumampa_odoo_agent.services.models.attachments import AttachmentSource
from sumampa_odoo_agent.services.models.runtime import (
    AgentRunInput,
    ConversationRuntimeContext,
    TransportContext,
)
from sumampa_odoo_agent.services.observability import (
    NoOpObservabilityProvider,
    ObservabilityProvider,
    to_observability_payload,
)
from sumampa_odoo_agent.services.session_state import (
    AGENT_SESSION_NAMESPACE,
    normalize_eval_tags,
    with_current_eval_tags,
)


@dataclass(slots=True)
class ConversationTurnInput:
    conversation_id: str
    channel: str
    user_id: str
    text: str
    attachments: list[AttachmentSource]
    context: dict[str, Any]
    eval_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConversationTurnResult:
    conversation_id: str
    assistant_text: str


@dataclass(slots=True)
class ConversationTagsInput:
    conversation_id: str
    channel: str
    user_id: str
    eval_tags: list[str]
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConversationTagsResult:
    conversation_id: str
    eval_tags: list[str]


class ConversationService:
    """Service that normalizes transport events before delegating to the agent runtime."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        attachment_ingestion: AttachmentIngestionService,
        session_store: SessionStore | None = None,
        observability: ObservabilityProvider | None = None,
        metrics: AppMetrics | None = None,
        trace_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._runtime = runtime
        self._attachment_ingestion = attachment_ingestion
        self._session_store = session_store
        self._observability = observability or NoOpObservabilityProvider()
        self._metrics = metrics
        self._trace_metadata = trace_metadata or {}

    async def run_turn(self, request: ConversationTurnInput) -> ConversationTurnResult:
        started_at = time.perf_counter()
        eval_tags = normalize_eval_tags(request.eval_tags)
        trace_metadata = {
            **self._trace_metadata,
            "transport.channel": request.channel,
            "transport.user_id": request.user_id,
            "transport.conversation_id": request.conversation_id,
            "eval.tags": eval_tags,
        }
        if eval_tags:
            trace_metadata["evalTags"] = ",".join(eval_tags)
        with self._observability.start_observation(
            name="conversation.turn",
            as_type="agent",
            input={
                "text": request.text,
                "context": request.context,
                "eval_tags": eval_tags,
                "attachments": [
                    _attachment_source_trace_payload(attachment)
                    for attachment in request.attachments
                ],
            },
            metadata=trace_metadata,
            user_id=request.user_id,
            session_id=request.conversation_id,
            tags=[
                "conversation",
                f"channel:{request.channel}",
                f"agent:{self._trace_metadata.get('agent.mode', 'unknown')}",
                f"odoo:{self._trace_metadata.get('odoo.mode', 'unknown')}",
                *eval_tags,
            ],
            version=str(self._trace_metadata.get("service.version", "")) or None,
            model=_optional_string(self._trace_metadata.get("agent.model")),
        ) as turn_observation:
            try:
                with self._observability.start_observation(
                    name="attachments.prepare",
                    as_type="span",
                    input={
                        "attachments": [
                            _attachment_source_trace_payload(attachment)
                            for attachment in request.attachments
                        ],
                    },
                    metadata={"attachment.count": len(request.attachments)},
                ) as attachment_observation:
                    prepared_attachments = await self._attachment_ingestion.prepare_attachments(
                        request.attachments,
                        conversation_id=request.conversation_id,
                        channel=request.channel,
                        user_id=request.user_id,
                    )
                    attachment_observation.update(
                        output={
                            "attachments": [
                                _prepared_attachment_trace_payload(prepared_attachment)
                                for prepared_attachment in prepared_attachments
                            ],
                        },
                        metadata={"attachment.count": len(prepared_attachments)},
                    )

                context = ConversationRuntimeContext(
                    transport=TransportContext(
                        channel=request.channel,
                        user_id=request.user_id,
                        conversation_id=request.conversation_id,
                    ),
                    context=request.context,
                    attachments=[
                        prepared_attachment.to_runtime_manifest()
                        for prepared_attachment in prepared_attachments
                    ],
                )

                result = await self._runtime.run(
                    AgentRunInput(
                        prompt=request.text.strip(),
                        context=context,
                        attachments=[
                            artifact
                            for prepared_attachment in prepared_attachments
                            for artifact in prepared_attachment.artifacts
                        ],
                        session_id=request.conversation_id,
                        eval_tags=eval_tags,
                    )
                )
            except Exception as exc:
                self._record_turn_metric(
                    channel=request.channel,
                    mode="unknown",
                    result="error",
                    started_at=started_at,
                )
                turn_observation.update(
                    level="ERROR",
                    status_message=f"{exc.__class__.__name__}: {exc}",
                    output={"error": exc.__class__.__name__},
                )
                turn_observation.score_trace(
                    name="error",
                    value=1.0,
                    data_type="NUMERIC",
                    comment=f"{exc.__class__.__name__}: {exc}",
                )
                raise

            turn_observation.update(
                output={
                    "conversation_id": result.session_id,
                    "assistant_text": result.text,
                },
                metadata={
                    **trace_metadata,
                    "runtime.mode": result.mode,
                },
            )
            turn_observation.score_trace(
                name="error",
                value=0.0,
                data_type="NUMERIC",
                comment="Turn completed without exception.",
            )
            self._record_turn_metric(
                channel=request.channel,
                mode=result.mode,
                result="success",
                started_at=started_at,
            )

        return ConversationTurnResult(
            conversation_id=result.session_id,
            assistant_text=result.text,
        )

    async def update_eval_tags(self, request: ConversationTagsInput) -> ConversationTagsResult:
        eval_tags = normalize_eval_tags(request.eval_tags)
        trace_metadata = {
            **self._trace_metadata,
            "transport.channel": request.channel,
            "transport.user_id": request.user_id,
            "transport.conversation_id": request.conversation_id,
            "eval.tags": eval_tags,
        }
        if eval_tags:
            trace_metadata["evalTags"] = ",".join(eval_tags)

        with self._observability.start_observation(
            name="conversation.tags",
            as_type="span",
            input={
                "conversation_id": request.conversation_id,
                "context": request.context,
                "eval_tags": eval_tags,
            },
            output={
                "conversation_id": request.conversation_id,
                "eval_tags": eval_tags,
            },
            metadata=trace_metadata,
            user_id=request.user_id,
            session_id=request.conversation_id,
            tags=[
                "conversation",
                "eval-tags",
                f"channel:{request.channel}",
                *eval_tags,
            ],
            version=str(self._trace_metadata.get("service.version", "")) or None,
            model=_optional_string(self._trace_metadata.get("agent.model")),
        ) as observation:
            if self._session_store is not None:
                try:
                    payload = await self._session_store.load(
                        namespace=AGENT_SESSION_NAMESPACE,
                        session_id=request.conversation_id,
                    )
                    session_payload = with_current_eval_tags(
                        payload,
                        session_id=request.conversation_id,
                        eval_tags=eval_tags,
                    )
                    await self._session_store.save(
                        namespace=AGENT_SESSION_NAMESPACE,
                        session_id=request.conversation_id,
                        payload=session_payload,
                    )
                except Exception as exc:
                    observation.update(
                        level="ERROR",
                        status_message=f"{exc.__class__.__name__}: {exc}",
                    )
                    raise

        return ConversationTagsResult(
            conversation_id=request.conversation_id,
            eval_tags=eval_tags,
        )

    def _record_turn_metric(
        self,
        *,
        channel: str,
        mode: str,
        result: str,
        started_at: float,
    ) -> None:
        if self._metrics is None:
            return
        self._metrics.record_conversation_turn(
            channel=channel,
            mode=mode,
            result=result,
            duration_seconds=time.perf_counter() - started_at,
        )


def _attachment_source_trace_payload(attachment: AttachmentSource) -> dict[str, Any]:
    return {
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "has_content_base64": bool(attachment.content_base64),
        "has_download_url": bool(attachment.download_url),
    }


def _prepared_attachment_trace_payload(prepared_attachment: Any) -> dict[str, Any]:
    manifest = prepared_attachment.to_runtime_manifest().model_dump(mode="json")
    artifacts = []
    for artifact in prepared_attachment.artifacts:
        artifact_payload = artifact.model_dump(exclude={"content_bytes"}, mode="json")
        content_bytes = artifact.content_bytes
        if content_bytes is not None:
            artifact_payload["content_bytes"] = to_observability_payload(content_bytes)
        artifacts.append(artifact_payload)
    return {
        "manifest": manifest,
        "artifacts": artifacts,
    }


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
