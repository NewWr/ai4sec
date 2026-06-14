"""Knowledge-base (Dify) API: browse, retrieve, and corpus-wide RAG Q&A.

Thin proxy in front of ``services.dify_client`` so the frontend talks only to
this backend (single origin, shared rate limiting, Dify host/key stay
server-side). ``POST /library/ask`` adds LLM synthesis over retrieved passages
(see ``services.corpus_qa``).
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.models.schemas import LibraryAskRequest, LibrarySearchRequest, LibraryStatusResponse
from app.rate_limit import limiter
from app.services import corpus_qa, dify_client
from app.services.dify_client import DifyError
from app.services.llm_runtime_config import get_llm_runtime_config

logger = logging.getLogger("scholar.library")

router = APIRouter(tags=["library"])

_MAX_QUESTION_LEN = 2000


def _ensure_enabled() -> None:
    if not get_settings().dify_enabled:
        raise HTTPException(status_code=503, detail="Knowledge base is not configured")


async def _call(coro):
    """Await a dify_client coroutine, mapping DifyError to an HTTP 502."""
    try:
        return await coro
    except DifyError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": exc.message,
                "upstream_status": exc.upstream_status,
                "upstream_detail": exc.detail,
            },
        )


@router.get("/library/status", response_model=LibraryStatusResponse)
@limiter.limit("60/minute")
async def library_status(request: Request) -> LibraryStatusResponse:
    settings = get_settings()
    return LibraryStatusResponse(
        enabled=settings.dify_enabled,
        search_method=settings.dify_search_method,
        default_dataset_configured=bool(settings.dify_default_dataset_id.strip()),
    )


@router.get("/library/datasets")
@limiter.limit("60/minute")
async def library_datasets(request: Request, page: int = 1, limit: int = 20):
    _ensure_enabled()
    return await _call(dify_client.list_datasets(page=page, limit=limit))


@router.get("/library/documents")
@limiter.limit("60/minute")
async def library_documents(request: Request, dataset_id: str = "", page: int = 1, limit: int = 20):
    _ensure_enabled()
    return await _call(dify_client.list_documents(dataset_id=dataset_id or None, page=page, limit=limit))


@router.get("/library/documents/{document_id}")
@limiter.limit("60/minute")
async def library_document(request: Request, document_id: str, dataset_id: str = ""):
    _ensure_enabled()
    return await _call(dify_client.get_document(document_id, dataset_id=dataset_id or None))


@router.get("/library/documents/{document_id}/segments")
@limiter.limit("60/minute")
async def library_segments(
    request: Request, document_id: str, dataset_id: str = "", page: int = 1, limit: int = 100
):
    _ensure_enabled()
    return await _call(
        dify_client.list_segments(document_id, dataset_id=dataset_id or None, page=page, limit=limit)
    )


@router.get("/library/documents/{document_id}/markdown")
@limiter.limit("30/minute")
async def library_markdown(request: Request, document_id: str, dataset_id: str = ""):
    _ensure_enabled()
    return await _call(dify_client.get_markdown(document_id, dataset_id=dataset_id or None))


@router.get("/library/documents/{document_id}/download")
@limiter.limit("30/minute")
async def library_download(request: Request, document_id: str, dataset_id: str = ""):
    _ensure_enabled()
    return await _call(dify_client.get_download_url(document_id, dataset_id=dataset_id or None))


@router.post("/library/search")
@limiter.limit("30/minute")
async def library_search(request: Request, req: LibrarySearchRequest):
    _ensure_enabled()
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must be non-empty")
    return await _call(
        dify_client.search(
            query,
            top_k=req.top_k,
            score_threshold=req.score_threshold,
            search_method=req.search_method,
            dataset_id=req.dataset_id or None,
        )
    )


@router.post("/library/ask")
@limiter.limit("10/minute")
async def library_ask(request: Request, req: LibraryAskRequest):
    """Corpus-wide RAG: retrieve passages, then LLM answers with `[L#]` citations."""
    question = (req.question or "").strip()[:_MAX_QUESTION_LEN]
    if not question:
        raise HTTPException(status_code=400, detail="question must be non-empty")

    language = req.language if req.language in ("en", "zh") else "en"

    # Mirror runs.py: only honour an explicitly-configured model; drop unknown
    # names to the default rather than forwarding an arbitrary/unauthorised model.
    allowed_models = get_llm_runtime_config().thinking_models
    llm_model = (req.llm_model or "").strip()
    if llm_model and allowed_models and llm_model not in allowed_models:
        logger.warning("library_ask: rejected unknown llm_model=%r; using default", llm_model)
        llm_model = ""

    try:
        return await corpus_qa.answer_corpus_question(
            question,
            top_k=req.top_k,
            search_method=req.search_method,
            language=language,
            llm_model=llm_model,
            dataset_id=req.dataset_id or None,
            dataset_ids=req.dataset_ids,
            graph_only=req.graph_only,
            force_refresh=req.force_refresh,
        )
    except DifyError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": exc.message,
                "upstream_status": exc.upstream_status,
                "upstream_detail": exc.detail,
            },
        )
    except httpx.TimeoutException as exc:
        logger.exception("library_ask: upstream timeout")
        raise HTTPException(status_code=504, detail="Question answering timed out") from exc
    except RuntimeError as exc:
        logger.exception("library_ask: answer generation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("library_ask: unexpected failure")
        raise HTTPException(status_code=500, detail=f"Question answering failed: {exc}") from exc


@router.get("/library/ask/history")
@limiter.limit("60/minute")
async def library_ask_history(request: Request, limit: int = 30, offset: int = 0, query: str = ""):
    return await corpus_qa.list_answer_records(limit=limit, offset=offset, query=query)


@router.get("/library/ask/history/{qa_id}")
@limiter.limit("60/minute")
async def library_ask_history_detail(request: Request, qa_id: str):
    record = await corpus_qa.get_answer_record(qa_id)
    if not record:
        raise HTTPException(status_code=404, detail="QA record not found")
    return record


@router.delete("/library/ask/history/{qa_id}")
@limiter.limit("60/minute")
async def delete_library_ask_history(request: Request, qa_id: str):
    deleted = await corpus_qa.delete_answer_record(qa_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="QA record not found")
    return {"qa_id": qa_id, "deleted": True}
