"""Conversation routes."""

from __future__ import annotations

from fastapi import APIRouter

from sumampa_odoo_agent.api.dependencies import ServicesDep
from sumampa_odoo_agent.api.schemas import ConversationMessageRequest, ConversationMessageResponse
from sumampa_odoo_agent.services.conversation import ConversationTurnInput
from sumampa_odoo_agent.services.models.attachments import AttachmentSource

router = APIRouter(prefix="/api/v1", tags=["messages"])


@router.post("/messages", response_model=ConversationMessageResponse)
async def post_message(
    request: ConversationMessageRequest,
    services: ServicesDep,
) -> ConversationMessageResponse:
    attachments = [
        AttachmentSource(
            filename=attachment.filename,
            content_type=attachment.mime_type,
            content_base64=attachment.content_base64,
            download_url=attachment.download_url,
        )
        for attachment in request.attachments
    ]

    result = await services.conversation.run_turn(
        ConversationTurnInput(
            conversation_id=request.conversation_id,
            channel=request.channel,
            user_id=request.user_id,
            text=request.text,
            attachments=attachments,
            context=request.context,
        )
    )
    return ConversationMessageResponse(
        conversation_id=result.conversation_id,
        messages=[{"role": "assistant", "text": result.assistant_text}],
    )
