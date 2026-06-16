from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.admin import require_admin_token
from app.models.schemas import (
    LLMConnectionTestRequest,
    LLMConnectionTestResponse,
    LLMSettingsResponse,
    LLMSettingsUpdateRequest,
    DailyRecommendationTopicResponse,
    DailyRecommendationTopicsUpdateRequest,
)
from app.rate_limit import limiter
from app.services.llm_runtime_config import (
    llm_config_response,
    resolve_test_config,
    test_llm_connection,
    update_llm_runtime_config,
)
from app.services.daily_recommendations import list_topics, update_topics

logger = logging.getLogger("scholar.settings")

router = APIRouter(tags=["settings"], prefix="/settings")


@router.get("/llm", response_model=LLMSettingsResponse)
@limiter.limit("30/minute")
async def get_llm_settings(request: Request) -> LLMSettingsResponse:
    del request
    return LLMSettingsResponse(**llm_config_response())


@router.patch("/llm", response_model=LLMSettingsResponse, dependencies=[Depends(require_admin_token)])
@limiter.limit("10/minute")
async def update_llm_settings(request: Request, body: LLMSettingsUpdateRequest) -> LLMSettingsResponse:
    del request
    try:
        data = update_llm_runtime_config(
            base_url=body.base_url,
            thinking_model=body.thinking_model,
            reasoning_effort=body.reasoning_effort,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(
        "LLM runtime settings updated base_url=%s models=%s reasoning_effort=%s api_key=%s",
        data.get("base_url"),
        data.get("thinking_model"),
        data.get("reasoning_effort"),
        "configured" if data.get("api_key_configured") else "empty",
    )
    return LLMSettingsResponse(**data)


@router.post("/llm/test", response_model=LLMConnectionTestResponse, dependencies=[Depends(require_admin_token)])
@limiter.limit("10/minute")
async def test_llm_settings(request: Request, body: LLMConnectionTestRequest) -> LLMConnectionTestResponse:
    del request
    try:
        config = resolve_test_config(
            base_url=body.base_url,
            thinking_model=body.thinking_model,
            reasoning_effort=body.reasoning_effort,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
            use_saved_api_key=body.use_saved_api_key,
        )
        data = await test_llm_connection(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LLMConnectionTestResponse(**data)


@router.get("/daily-topics", response_model=list[DailyRecommendationTopicResponse])
@limiter.limit("30/minute")
async def get_daily_topic_settings(request: Request) -> list[DailyRecommendationTopicResponse]:
    del request
    return [DailyRecommendationTopicResponse(**topic) for topic in await list_topics()]


@router.put("/daily-topics", response_model=list[DailyRecommendationTopicResponse], dependencies=[Depends(require_admin_token)])
@limiter.limit("10/minute")
async def update_daily_topic_settings(
    request: Request,
    body: DailyRecommendationTopicsUpdateRequest,
) -> list[DailyRecommendationTopicResponse]:
    del request
    try:
        topics = await update_topics([topic.model_dump() for topic in body.topics])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [DailyRecommendationTopicResponse(**topic) for topic in topics]
