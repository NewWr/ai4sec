from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.api.runs import start_background_run
from app.db import database as db
from app.models.schemas import (
    DailyRecommendationFeedbackRequest,
    DailyRecommendationIngestRequest,
    DailyRecommendationIngestResponse,
    DailyRecommendationItemResponse,
    DailyRecommendationListResponse,
    DailyRecommendationPromoteRequest,
    DailyRecommendationRefreshRequest,
    DailyRecommendationRefreshResponse,
    DailyRecommendationTopicResponse,
)
from app.rate_limit import limiter
from app.services.daily_recommendations import (
    ingest_item,
    list_items,
    list_topics,
    refresh_daily_recommendations,
    update_feedback,
)
from app.services.knowledge_spaces import (
    DAILY_ANALYSIS_SPACE_ID,
    DAILY_SOURCE_SPACE_ID,
    add_item_to_space,
    promote_daily_item,
)

router = APIRouter(tags=["daily"])

_daily_refresh_jobs: dict[str, dict[str, Any]] = {}
_active_daily_refresh_job_id = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    return dict(job)


async def _run_refresh_job(job_id: str, body: DailyRecommendationRefreshRequest, refresh_func=refresh_daily_recommendations) -> None:
    global _active_daily_refresh_job_id
    job = _daily_refresh_jobs[job_id]
    job["status"] = "running"
    job["started_at"] = _now_iso()
    try:
        result = await refresh_func(
            fetched_date=body.date,
            topic_id=body.topic_id,
            force=body.force,
        )
        job.update(result)
        job["status"] = "done"
        job["message"] = str(result.get("message") or "ok")
    except Exception as exc:
        job["status"] = "failed"
        job["message"] = str(exc)
    finally:
        job["finished_at"] = _now_iso()
        if _active_daily_refresh_job_id == job_id:
            _active_daily_refresh_job_id = ""


@router.get("/daily/topics", response_model=list[DailyRecommendationTopicResponse])
@limiter.limit("30/minute")
async def get_daily_topics(request: Request):
    del request
    return [DailyRecommendationTopicResponse(**topic) for topic in await list_topics()]


@router.get("/daily/items", response_model=DailyRecommendationListResponse)
@limiter.limit("30/minute")
async def get_daily_items(
    request: Request,
    date: str = "",
    topic_id: str = "",
    status: str = "",
    limit: int = 20,
    offset: int = 0,
):
    del request
    data = await list_items(fetched_date=date, topic_id=topic_id, status=status, limit=limit, offset=offset)
    return DailyRecommendationListResponse(
        date=data["date"],
        topics=[DailyRecommendationTopicResponse(**topic) for topic in data["topics"]],
        items=[DailyRecommendationItemResponse(**item) for item in data["items"]],
        total=data["total"],
        limit=data["limit"],
        offset=data["offset"],
        has_more=data["has_more"],
    )


@router.post("/daily/refresh", response_model=DailyRecommendationRefreshResponse)
@limiter.limit("5/minute")
async def refresh_daily(request: Request, body: DailyRecommendationRefreshRequest):
    del request
    global _active_daily_refresh_job_id
    if _active_daily_refresh_job_id:
        return DailyRecommendationRefreshResponse(**_job_public(_daily_refresh_jobs[_active_daily_refresh_job_id]))

    job_id = uuid.uuid4().hex[:16]
    job = {
        "job_id": job_id,
        "status": "started",
        "date": body.date,
        "fetched": 0,
        "inserted_or_updated": 0,
        "kept": 0,
        "skipped": 0,
        "message": "started",
        "errors": [],
        "started_at": _now_iso(),
        "finished_at": "",
    }
    _daily_refresh_jobs[job_id] = job
    _active_daily_refresh_job_id = job_id
    asyncio.create_task(_run_refresh_job(job_id, body, refresh_daily_recommendations))
    return DailyRecommendationRefreshResponse(**_job_public(job))


@router.get("/daily/refresh/{job_id}", response_model=DailyRecommendationRefreshResponse)
@limiter.limit("30/minute")
async def get_refresh_status(request: Request, job_id: str):
    del request
    job = _daily_refresh_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Refresh job not found")
    return DailyRecommendationRefreshResponse(**_job_public(job))


@router.post("/daily/items/{item_id}/feedback", response_model=DailyRecommendationItemResponse)
@limiter.limit("30/minute")
async def feedback_daily_item(request: Request, item_id: str, body: DailyRecommendationFeedbackRequest):
    del request
    try:
        return DailyRecommendationItemResponse(
            **await update_feedback(item_id, action=body.action, note=body.note)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/daily/items/{item_id}/ingest", response_model=DailyRecommendationIngestResponse)
@limiter.limit("5/minute")
async def ingest_daily_item(request: Request, item_id: str, body: DailyRecommendationIngestRequest):
    del request
    try:
        source_space_id = (body.source_space_id or DAILY_SOURCE_SPACE_ID).strip()
        analysis_space_id = (body.analysis_space_id or DAILY_ANALYSIS_SPACE_ID).strip()
        parse_mode = body.parse_mode or body.mode
        result = await ingest_item(
            item_id,
            collection_id=body.collection_id,
            source_space_id=source_space_id,
        )
        run_id = str(result.get("run_id") or "")
        if body.start_run and not body.ingest_source_only and not run_id:
            mode = parse_mode
            question = "请综合解读这篇从每日推荐导入的论文，重点说明问题、方法、实验结论、局限和是否值得深入阅读。"
            run = await start_background_run(
                paper_id=str(result["paper_id"]),
                mode=mode,
                llm_model=body.llm_model,
                language=body.language,
                question=question if mode == "auto" else "",
                owner_token=body.owner_token,
            )
            run_id = str(run.get("run_id") or "")
            await db.execute(
                "UPDATE daily_recommendation_items SET linked_run_id = ? WHERE item_id = ?",
                (run_id, item_id),
            )
            await add_item_to_space(
                space_id=analysis_space_id,
                item_kind="run",
                item_id=run_id,
                paper_id=str(result["paper_id"]),
                run_id=run_id,
                source_type="daily",
                sync_status="pending" if body.sync_to_dify else "skipped",
                note=f"Daily recommendation analysis mode={mode}",
            )
        return DailyRecommendationIngestResponse(
            item_id=item_id,
            paper_id=str(result["paper_id"]),
            run_id=run_id,
            status="ingested",
            message=(
                "Ingested source only"
                if body.ingest_source_only or not body.start_run
                else "Ingested and analysis started"
                if run_id
                else str(result.get("message") or "Ingested")
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/daily/items/{item_id}/ingest-status", response_model=DailyRecommendationItemResponse)
@limiter.limit("30/minute")
async def get_daily_ingest_status(request: Request, item_id: str):
    del request
    row = await db.fetch_one("SELECT * FROM daily_recommendation_items WHERE item_id = ?", (item_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Daily recommendation item not found")
    data = await list_items(fetched_date=str(row.get("fetched_date") or ""), limit=500)
    for item in data["items"]:
        if item["item_id"] == item_id:
            return DailyRecommendationItemResponse(**item)
    raise HTTPException(status_code=404, detail="Daily recommendation item not found")


@router.post("/daily/items/{item_id}/promote")
@limiter.limit("10/minute")
async def promote_daily_recommendation_item(request: Request, item_id: str, body: DailyRecommendationPromoteRequest):
    del request
    try:
        return await promote_daily_item(
            item_id,
            source_target_space_id=body.source_target_space_id,
            analysis_target_space_id=body.analysis_target_space_id,
            copy=body.copy_item,
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
