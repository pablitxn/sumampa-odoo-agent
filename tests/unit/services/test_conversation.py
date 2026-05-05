"""Unit tests for the conversation service."""

from __future__ import annotations

import base64
from contextlib import AbstractContextManager
from typing import Any, Literal

import pytest

from sumampa_odoo_agent.config import AttachmentSettings
from sumampa_odoo_agent.integrations.sessions import InMemorySessionStore
from sumampa_odoo_agent.integrations.storage import InMemoryAttachmentObjectStore
from sumampa_odoo_agent.services.attachments import AttachmentIngestionService
from sumampa_odoo_agent.services.conversation import (
    ConversationService,
    ConversationTagsInput,
    ConversationTurnInput,
)
from sumampa_odoo_agent.services.models.attachments import AttachmentSource
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult
from sumampa_odoo_agent.services.observability import Observation
from sumampa_odoo_agent.services.session_state import AGENT_SESSION_NAMESPACE


class _FakeRuntime:
    def __init__(self) -> None:
        self.last_call: dict[str, object] | None = None

    async def run(self, request: AgentRunInput) -> AgentRunResult:
        self.last_call = {
            "prompt": request.prompt,
            "context": request.context.to_agent_context(),
            "attachments": request.attachments,
            "session_id": request.session_id,
            "eval_tags": request.eval_tags,
        }
        return AgentRunResult(
            mode="test",
            session_id=request.session_id or "generated-session",
            text="We are continuing with the request.",
        )


@pytest.mark.asyncio
async def test_conversation_service_passes_empty_text_and_runtime_context() -> None:
    runtime = _FakeRuntime()
    attachment_store = InMemoryAttachmentObjectStore()
    service = ConversationService(
        runtime,
        attachment_ingestion=AttachmentIngestionService(
            object_store=attachment_store,
            settings=AttachmentSettings(store_mode="memory"),
        ),
    )

    result = await service.run_turn(
        ConversationTurnInput(
            conversation_id="conv-1",
            channel="whatsapp",
            user_id="demo-user-001",
            text="",
            attachments=[
                AttachmentSource(
                    filename="attachment.jpg",
                    content_type="image/jpeg",
                    content_base64=base64.b64encode(b"fake-image").decode("ascii"),
                )
            ],
            context={"customer_name": "Demo Customer SRL"},
        )
    )

    assert result.conversation_id == "conv-1"
    assert result.assistant_text == "We are continuing with the request."
    assert runtime.last_call is not None
    assert runtime.last_call["prompt"] == ""
    runtime_context = runtime.last_call["context"]
    assert isinstance(runtime_context, dict)
    assert runtime_context["transport"]["channel"] == "whatsapp"
    assert runtime_context["context"]["customer_name"] == "Demo Customer SRL"
    assert len(runtime_context["attachments"]) == 1
    assert runtime_context["attachments"][0]["storage_uri"].startswith("memory://")
    runtime_attachments = runtime.last_call["attachments"]
    assert isinstance(runtime_attachments, list)
    assert len(runtime_attachments) == 1
    assert runtime_attachments[0].kind == "image"


@pytest.mark.asyncio
async def test_conversation_service_records_eval_tags_without_agent_context() -> None:
    runtime = _FakeRuntime()
    attachment_store = InMemoryAttachmentObjectStore()
    observability = _RecordingObservability()
    service = ConversationService(
        runtime,
        attachment_ingestion=AttachmentIngestionService(
            object_store=attachment_store,
            settings=AttachmentSettings(store_mode="memory"),
        ),
        observability=observability,
    )

    await service.run_turn(
        ConversationTurnInput(
            conversation_id="conv-1",
            channel="whatsapp",
            user_id="demo-user-001",
            text="hola",
            attachments=[],
            context={"customer_name": "Demo Customer SRL"},
            eval_tags=[" eval:candidate ", "eval:candidate"],
        )
    )

    turn_record = next(record for record in observability.records if record["name"] == "conversation.turn")
    assert turn_record["input"]["eval_tags"] == ["eval:candidate"]
    assert turn_record["metadata"]["eval.tags"] == ["eval:candidate"]
    assert turn_record["metadata"]["evalTags"] == "eval:candidate"
    assert "eval:candidate" in turn_record["tags"]
    assert runtime.last_call is not None
    assert runtime.last_call["eval_tags"] == ["eval:candidate"]
    runtime_context = runtime.last_call["context"]
    assert isinstance(runtime_context, dict)
    assert "eval_tags" not in runtime_context


@pytest.mark.asyncio
async def test_conversation_service_records_tag_update_without_runtime_call() -> None:
    runtime = _FakeRuntime()
    attachment_store = InMemoryAttachmentObjectStore()
    session_store = InMemorySessionStore()
    await session_store.save(
        namespace=AGENT_SESSION_NAMESPACE,
        session_id="conv-1",
        payload={
            "type": "session",
            "session_id": "conv-1",
            "service_session_id": None,
            "state": {"sumampa": {"eval_tags": ["eval:candidate"]}},
        },
    )
    observability = _RecordingObservability()
    service = ConversationService(
        runtime,
        attachment_ingestion=AttachmentIngestionService(
            object_store=attachment_store,
            settings=AttachmentSettings(store_mode="memory"),
        ),
        session_store=session_store,
        observability=observability,
    )

    result = await service.update_eval_tags(
        ConversationTagsInput(
            conversation_id="conv-1",
            channel="whatsapp",
            user_id="demo-user-001",
            eval_tags=["eval:discarded"],
            context={"demo": True},
        )
    )

    tag_record = next(record for record in observability.records if record["name"] == "conversation.tags")
    assert result.eval_tags == ["eval:discarded"]
    assert tag_record["input"]["eval_tags"] == ["eval:discarded"]
    assert tag_record["metadata"]["evalTags"] == "eval:discarded"
    assert "eval:discarded" in tag_record["tags"]
    assert runtime.last_call is None
    payload = await session_store.load(namespace=AGENT_SESSION_NAMESPACE, session_id="conv-1")
    assert payload is not None
    assert payload["state"]["sumampa"]["eval_tags"] == ["eval:discarded"]


class _RecordingObservation:
    def __init__(self, record: dict[str, Any]) -> None:
        self._record = record

    def update(self, **kwargs: Any) -> None:
        self._record["updates"].append(dict(kwargs))

    def score_trace(self, **kwargs: Any) -> None:
        self._record["scores"].append(dict(kwargs))


class _RecordingContext(AbstractContextManager[Observation]):
    def __init__(self, record: dict[str, Any]) -> None:
        self._record = record

    def __enter__(self) -> Observation:
        return _RecordingObservation(self._record)

    def __exit__(self, *args: Any) -> Literal[False]:
        del args
        return False


class _RecordingObservability:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def start_observation(self, **kwargs: Any) -> AbstractContextManager[Observation]:
        record = {
            **kwargs,
            "updates": [],
            "scores": [],
        }
        self.records.append(record)
        return _RecordingContext(record)

    def create_score(self, **kwargs: Any) -> None:
        del kwargs

    def flush(self) -> None:
        return None

    async def aclose(self) -> None:
        return None
