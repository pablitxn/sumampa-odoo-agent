"""Demo sales routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.responses import Response

from sumampa_odoo_agent.api.dependencies import ServicesDep
from sumampa_odoo_agent.api.schemas import (
    ConversationTagsResponse,
    DemoSalesConversationTagsRequest,
    DemoSalesFeedbackRequest,
    DemoSalesFeedbackResponse,
    DemoSalesMessageRequest,
    DemoSalesMessageResponse,
    DemoSalesResetResponse,
    DemoSalesScenariosResponse,
)
from sumampa_odoo_agent.services.demo_sales import (
    DemoSalesConversationNotFoundError,
    DemoSalesError,
    DemoSalesFeedbackInput,
    DemoSalesScenarioLockedError,
    DemoSalesScenarioNotFoundError,
    DemoSalesTagsInput,
    DemoSalesTurnInput,
    DemoSalesValidationError,
)

router = APIRouter(prefix="/demo/api", tags=["demo"])


@router.get("/scenarios", response_model=DemoSalesScenariosResponse)
async def get_demo_scenarios(services: ServicesDep) -> DemoSalesScenariosResponse:
    return DemoSalesScenariosResponse.model_validate(services.demo_sales.list_scenarios())


@router.post("/messages", response_model=DemoSalesMessageResponse)
async def post_demo_message(
    request: DemoSalesMessageRequest,
    services: ServicesDep,
) -> DemoSalesMessageResponse:
    try:
        result = await services.demo_sales.run_turn(
            DemoSalesTurnInput(
                conversation_id=request.conversation_id,
                channel=request.channel,
                user_id=request.user_id,
                text=request.text,
                scenario_id=request.scenario_id,
                scenario_params=request.scenario_params,
                context=request.context,
                eval_tags=request.eval_tags,
            )
        )
    except DemoSalesError as exc:
        raise _demo_sales_http_error(exc) from exc

    return DemoSalesMessageResponse(
        conversation_id=result.conversation_id,
        messages=[{"role": "assistant", "text": message} for message in result.messages],
        scenario=result.scenario,
        state=result.state,
        recent_tool_calls=result.recent_tool_calls,
    )


@router.post("/conversation-tags", response_model=ConversationTagsResponse)
async def post_demo_conversation_tags(
    request: DemoSalesConversationTagsRequest,
    services: ServicesDep,
) -> ConversationTagsResponse:
    try:
        result = await services.demo_sales.update_eval_tags(
            DemoSalesTagsInput(
                conversation_id=request.conversation_id,
                channel=request.channel,
                user_id=request.user_id,
                eval_tags=request.eval_tags,
                scenario_id=request.scenario_id,
                scenario_params=request.scenario_params,
                context=request.context,
            )
        )
    except DemoSalesError as exc:
        raise _demo_sales_http_error(exc) from exc
    return ConversationTagsResponse(
        conversation_id=result.conversation_id,
        eval_tags=result.eval_tags,
    )


@router.post("/conversations/{conversation_id}/reset", response_model=DemoSalesResetResponse)
async def reset_demo_conversation(
    conversation_id: str,
    services: ServicesDep,
) -> DemoSalesResetResponse:
    return DemoSalesResetResponse(
        conversation_id=conversation_id,
        reset=services.demo_sales.reset_conversation(conversation_id),
    )


@router.get("/conversations/{conversation_id}/export.jsonl")
async def export_demo_conversation_jsonl(
    conversation_id: str,
    services: ServicesDep,
) -> Response:
    try:
        body = services.demo_sales.export_conversation_jsonl(conversation_id)
    except DemoSalesError as exc:
        raise _demo_sales_http_error(exc) from exc
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": (
                f'attachment; filename="sumampa-demo-{conversation_id}.jsonl"'
            )
        },
    )


@router.post(
    "/conversations/{conversation_id}/feedback",
    response_model=DemoSalesFeedbackResponse,
)
async def post_demo_conversation_feedback(
    conversation_id: str,
    request: DemoSalesFeedbackRequest,
    services: ServicesDep,
) -> DemoSalesFeedbackResponse:
    try:
        result = await services.demo_sales.record_manual_feedback(
            DemoSalesFeedbackInput(
                conversation_id=conversation_id,
                channel=request.channel,
                user_id=request.user_id,
                feedback_tags=request.feedback_tags,
                feedback_text=request.feedback_text,
                context=request.context,
            )
        )
    except DemoSalesError as exc:
        raise _demo_sales_http_error(exc) from exc
    return DemoSalesFeedbackResponse(
        conversation_id=result.conversation_id,
        feedback_tags=result.feedback_tags,
        feedback_count=result.feedback_count,
    )


def _demo_sales_http_error(exc: DemoSalesError) -> HTTPException:
    if isinstance(exc, DemoSalesConversationNotFoundError):
        return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, DemoSalesScenarioNotFoundError):
        return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, DemoSalesScenarioLockedError):
        return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, DemoSalesValidationError):
        return HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})
