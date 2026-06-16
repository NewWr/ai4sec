from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import (
    ExternalNoteAddToDailyRequest,
    ExternalNoteGenerateCardsRequest,
    ExternalNoteLinkPaperRequest,
    ExternalNotePromoteRequest,
    ExternalNoteFacetsResponse,
    ExternalNoteStartRunRequest,
    ExternalNoteStatusRequest,
    ExternalNoteSyncSpaceRequest,
    ExternalNoteSyncRunResponse,
    ExternalPaperNoteListResponse,
    ExternalPaperNoteResponse,
    ExternalSourceResponse,
    PaperNotesSyncRequest,
)
from app.rate_limit import limiter
from app.services import external_paper_notes as notes
from app.services.external_note_matching import refresh_matches
from app.services.external_note_utility import refresh_utility_score

router = APIRouter(tags=["paper-notes"])


@router.get("/paper-notes/sources", response_model=list[ExternalSourceResponse])
@limiter.limit("30/minute")
async def list_paper_note_sources(request: Request):
    del request
    return [ExternalSourceResponse(**row) for row in await notes.list_sources()]


@router.get("/paper-notes/facets", response_model=ExternalNoteFacetsResponse)
@limiter.limit("30/minute")
async def list_paper_note_facets(request: Request):
    del request
    return ExternalNoteFacetsResponse(**await notes.list_facets())


@router.post("/paper-notes/sync", response_model=ExternalNoteSyncRunResponse)
@limiter.limit("3/minute")
async def sync_paper_notes(request: Request, body: PaperNotesSyncRequest):
    del request
    try:
        return ExternalNoteSyncRunResponse(**await notes.sync_paper_notes(force=body.force, max_files=body.max_files))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/paper-notes/sync/{sync_id}", response_model=ExternalNoteSyncRunResponse)
@limiter.limit("30/minute")
async def get_paper_notes_sync(request: Request, sync_id: str):
    del request
    try:
        return ExternalNoteSyncRunResponse(**await notes.get_sync_run(sync_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/paper-notes/items", response_model=ExternalPaperNoteListResponse)
@limiter.limit("30/minute")
async def list_paper_note_items(
    request: Request,
    conference: str = "",
    year: int = 0,
    domain: str = "",
    status: str = "",
    q: str = "",
    has_arxiv: bool | None = None,
    linked: bool | None = None,
    min_score: float = 0.0,
    sort: str = "utility",
    limit: int = 20,
    offset: int = 0,
):
    del request
    return ExternalPaperNoteListResponse(
        **await notes.list_items(
            conference=conference,
            year=year,
            domain=domain,
            status=status,
            q=q,
            has_arxiv=has_arxiv,
            linked=linked,
            min_score=min_score,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/paper-notes/items/{note_id}", response_model=ExternalPaperNoteResponse)
@limiter.limit("60/minute")
async def get_paper_note_item(request: Request, note_id: str):
    del request
    try:
        return ExternalPaperNoteResponse(**await notes.get_item(note_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/paper-notes/items/{note_id}/status", response_model=ExternalPaperNoteResponse)
@limiter.limit("30/minute")
async def update_paper_note_status(request: Request, note_id: str, body: ExternalNoteStatusRequest):
    del request
    try:
        return ExternalPaperNoteResponse(**await notes.update_status(note_id, body.status, note=body.note))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/paper-notes/items/{note_id}/refresh-score", response_model=ExternalPaperNoteResponse)
@limiter.limit("20/minute")
async def refresh_paper_note_score(request: Request, note_id: str):
    del request
    try:
        await refresh_matches(note_id)
        await refresh_utility_score(note_id)
        return ExternalPaperNoteResponse(**await notes.get_item(note_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/paper-notes/items/{note_id}/link-paper", response_model=ExternalPaperNoteResponse)
@limiter.limit("20/minute")
async def link_paper_note_to_paper(request: Request, note_id: str, body: ExternalNoteLinkPaperRequest):
    del request
    try:
        return ExternalPaperNoteResponse(**await notes.link_paper(note_id, body.paper_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/paper-notes/items/{note_id}/promote")
@limiter.limit("5/minute")
async def promote_paper_note(request: Request, note_id: str, body: ExternalNotePromoteRequest):
    del request
    try:
        return await notes.promote_note(note_id, collection_id=body.collection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/paper-notes/items/{note_id}/start-run")
@limiter.limit("5/minute")
async def start_paper_note_run(request: Request, note_id: str, body: ExternalNoteStartRunRequest):
    del request
    try:
        return await notes.start_note_run(
            note_id,
            mode=body.mode,
            llm_model=body.llm_model,
            language=body.language,
            question=body.question,
            owner_token=body.owner_token,
            auto_promote=body.auto_promote,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/paper-notes/items/{note_id}/add-to-daily")
@limiter.limit("10/minute")
async def add_paper_note_to_daily(request: Request, note_id: str, body: ExternalNoteAddToDailyRequest):
    del request
    try:
        return await notes.add_note_to_daily(note_id, topic_id=body.topic_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/paper-notes/items/{note_id}/sync-space")
@limiter.limit("10/minute")
async def sync_paper_note_to_space(request: Request, note_id: str, body: ExternalNoteSyncSpaceRequest):
    del request
    try:
        return await notes.sync_note_to_space(note_id, space_id=body.space_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/paper-notes/items/{note_id}/generate-cards")
@limiter.limit("10/minute")
async def generate_paper_note_cards(request: Request, note_id: str, body: ExternalNoteGenerateCardsRequest):
    del request
    try:
        return await notes.generate_note_cards(note_id, max_cards=body.max_cards)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
