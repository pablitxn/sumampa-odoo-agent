from __future__ import annotations

import pytest
from pydantic import ValidationError

from sumampa_odoo_agent.api.schemas import ConversationMessageRequest


def test_message_request_defaults_eval_tags_to_empty_list() -> None:
    request = ConversationMessageRequest(
        conversation_id="conversation-1",
        channel="whatsapp",
        user_id="user-1",
    )

    assert request.eval_tags == []


def test_message_request_normalizes_eval_tags() -> None:
    request = ConversationMessageRequest(
        conversation_id="conversation-1",
        channel="whatsapp",
        user_id="user-1",
        eval_tags=[" eval:candidate ", "eval:candidate", ""],
    )

    assert request.eval_tags == ["eval:candidate"]


def test_message_request_rejects_non_string_eval_tags() -> None:
    with pytest.raises(ValidationError):
        ConversationMessageRequest(
            conversation_id="conversation-1",
            channel="whatsapp",
            user_id="user-1",
            eval_tags=[123],
        )
