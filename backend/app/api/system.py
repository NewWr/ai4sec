from __future__ import annotations

from fastapi import APIRouter, Request

from app.models.schemas import ModelListResponse
from app.rate_limit import limiter
from app.services.llm_runtime_config import get_llm_runtime_config

router = APIRouter(tags=["system"])


@router.get("/system/health")
@limiter.limit("120/minute")
async def health(request: Request) -> dict[str, bool]:
    del request
    return {"ok": True}


@router.get("/models", response_model=ModelListResponse)
@limiter.limit("60/minute")
async def list_models(request: Request) -> ModelListResponse:
    """Return the selectable LLM models (from THINKING_MODELNAME) and the default.

    THINKING_MODELNAME may be a comma-separated list, e.g.
    ``qwen3.6-plus,qwen3.7-max``. The frontend renders these as a dropdown so the
    user picks instead of typing a model name.
    """
    config = get_llm_runtime_config()
    return ModelListResponse(
        models=config.thinking_models,
        default=config.default_thinking_model,
    )
