from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import (
    AiReviewMarkCreateRequest,
    AiReviewMarkResponse,
    AiReviewMarkUpdateRequest,
    ComparisonTableRequest,
    DuplicateCandidatesResponse,
    ExportResponse,
    HealthFixRequest,
    HealthFixResponse,
    ImportResponse,
    KnowledgeCardBatchMergeRequest,
    KnowledgeCardBatchStatusRequest,
    KnowledgeCardCreateRequest,
    KnowledgeCardGenerateRequest,
    KnowledgeCardGenerationResponse,
    KnowledgeCardMergeRequest,
    KnowledgeCardResponse,
    KnowledgeCardUpdateRequest,
    KnowledgeHealthResponse,
    LocalSearchResponse,
    PaperAnnotationCreateRequest,
    PaperAnnotationResponse,
    PaperAnnotationUpdateRequest,
    PaperBulkLifecycleUpdateRequest,
    PaperLifecycleUpdateRequest,
    PaperNoteResponse,
    PaperNoteUpdateRequest,
    PaperResponse,
    ReferenceImportRequest,
    RelatedWorkComposeRequest,
    WritingSnippetCreateRequest,
    WritingSnippetResponse,
    WritingSnippetUpdateRequest,
)
from app.rate_limit import limiter
from app.services import knowledge_assets as assets
from app.services import knowledge_card_generator

router = APIRouter(tags=["knowledge"])


def _bad_request(exc: ValueError) -> HTTPException:
    msg = str(exc)
    status = 404 if "not found" in msg.lower() else 400
    return HTTPException(status_code=status, detail=msg)


@router.patch("/papers/{paper_id}/lifecycle", response_model=PaperResponse)
@limiter.limit("30/minute")
async def update_paper_lifecycle(request: Request, paper_id: str, req: PaperLifecycleUpdateRequest):
    try:
        return PaperResponse(**await assets.update_paper_lifecycle(paper_id, req.model_dump(exclude_unset=True)))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/papers/lifecycle/bulk")
@limiter.limit("20/minute")
async def bulk_update_paper_lifecycle(request: Request, req: PaperBulkLifecycleUpdateRequest):
    count = await assets.bulk_update_paper_lifecycle(req.paper_ids, req.model_dump(exclude={"paper_ids"}, exclude_unset=True))
    return {"updated": count}


@router.get("/papers/{paper_id}/annotations", response_model=list[PaperAnnotationResponse])
@limiter.limit("60/minute")
async def list_paper_annotations(request: Request, paper_id: str):
    try:
        return [PaperAnnotationResponse(**row) for row in await assets.list_annotations(paper_id)]
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/papers/{paper_id}/annotations", response_model=PaperAnnotationResponse)
@limiter.limit("30/minute")
async def create_paper_annotation(request: Request, paper_id: str, req: PaperAnnotationCreateRequest):
    data = req.model_dump()
    data["paper_id"] = paper_id
    try:
        return PaperAnnotationResponse(**await assets.create_annotation(data))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.patch("/annotations/{annotation_id}", response_model=PaperAnnotationResponse)
@limiter.limit("30/minute")
async def update_paper_annotation(request: Request, annotation_id: str, req: PaperAnnotationUpdateRequest):
    try:
        return PaperAnnotationResponse(**await assets.update_annotation(annotation_id, req.model_dump(exclude_unset=True)))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete("/annotations/{annotation_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_paper_annotation(request: Request, annotation_id: str):
    await assets.delete_annotation(annotation_id)
    return None


@router.get("/papers/{paper_id}/note", response_model=PaperNoteResponse)
@limiter.limit("60/minute")
async def get_paper_note(request: Request, paper_id: str):
    try:
        return PaperNoteResponse(**await assets.get_note(paper_id))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.put("/papers/{paper_id}/note", response_model=PaperNoteResponse)
@limiter.limit("30/minute")
async def update_paper_note(request: Request, paper_id: str, req: PaperNoteUpdateRequest):
    try:
        return PaperNoteResponse(**await assets.update_note(paper_id, req.model_dump()))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/papers/{paper_id}/review-marks", response_model=list[AiReviewMarkResponse])
@limiter.limit("60/minute")
async def list_review_marks(request: Request, paper_id: str, run_id: str = ""):
    try:
        return [AiReviewMarkResponse(**row) for row in await assets.list_review_marks(paper_id, run_id)]
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/review-marks", response_model=AiReviewMarkResponse)
@limiter.limit("30/minute")
async def create_review_mark(request: Request, req: AiReviewMarkCreateRequest):
    try:
        return AiReviewMarkResponse(**await assets.create_review_mark(req.model_dump()))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.patch("/review-marks/{mark_id}", response_model=AiReviewMarkResponse)
@limiter.limit("30/minute")
async def update_review_mark(request: Request, mark_id: str, req: AiReviewMarkUpdateRequest):
    try:
        return AiReviewMarkResponse(**await assets.update_review_mark(mark_id, req.model_dump(exclude_unset=True)))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/knowledge/cards", response_model=list[KnowledgeCardResponse])
@limiter.limit("60/minute")
async def list_knowledge_cards(
    request: Request,
    query: str = "",
    card_type: str = "",
    status: str = "",
    paper_id: str = "",
    created_by: str = "",
    run_id: str = "",
    asset_level: str = "",
    action_type: str = "",
    priority: str = "",
    has_source: str = "",
    quality_flag: str = "",
    min_confidence: float | None = None,
    limit: int = 100,
    offset: int = 0,
):
    return [
        KnowledgeCardResponse(**row)
        for row in await assets.list_cards(
            query=query,
            card_type=card_type,
            status=status,
            paper_id=paper_id,
            created_by=created_by,
            run_id=run_id,
            asset_level=asset_level,
            action_type=action_type,
            priority=priority,
            has_source=has_source,
            quality_flag=quality_flag,
            min_confidence=min_confidence,
            limit=limit,
            offset=offset,
        )
    ]


@router.post("/knowledge/cards/generate", response_model=KnowledgeCardGenerationResponse)
@limiter.limit("10/minute")
async def generate_knowledge_cards(request: Request, req: KnowledgeCardGenerateRequest):
    try:
        return KnowledgeCardGenerationResponse(
            **await knowledge_card_generator.generate_cards_for_run(
                req.run_id,
                paper_id=req.paper_id,
                model=req.model,
                force=req.force,
                max_cards=req.max_cards,
                trigger_source="manual",
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/knowledge/cards/generations", response_model=list[KnowledgeCardGenerationResponse])
@limiter.limit("30/minute")
async def list_knowledge_card_generations(request: Request, paper_id: str = "", run_id: str = "", limit: int = 50):
    return [
        KnowledgeCardGenerationResponse(**row)
        for row in await assets.list_card_generations(paper_id=paper_id, run_id=run_id, limit=limit)
    ]


@router.patch("/knowledge/cards/batch-status", response_model=list[KnowledgeCardResponse])
@limiter.limit("20/minute")
async def batch_update_knowledge_card_status(request: Request, req: KnowledgeCardBatchStatusRequest):
    try:
        return [
            KnowledgeCardResponse(**row)
            for row in await assets.batch_update_card_status(
                req.card_ids,
                req.status,
                allow_untraceable=req.allow_untraceable,
                reviewed_by=req.reviewed_by,
            )
        ]
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/knowledge/cards/batch-merge", response_model=list[KnowledgeCardResponse])
@limiter.limit("20/minute")
async def batch_merge_knowledge_cards(request: Request, req: KnowledgeCardBatchMergeRequest):
    try:
        return [
            KnowledgeCardResponse(**row)
            for row in await assets.batch_merge_cards(req.source_card_ids, req.target_card_id)
        ]
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/knowledge/cards", response_model=KnowledgeCardResponse)
@limiter.limit("30/minute")
async def create_knowledge_card(request: Request, req: KnowledgeCardCreateRequest):
    try:
        return KnowledgeCardResponse(**await assets.create_card(req.model_dump()))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.patch("/knowledge/cards/{card_id}", response_model=KnowledgeCardResponse)
@limiter.limit("30/minute")
async def update_knowledge_card(request: Request, card_id: str, req: KnowledgeCardUpdateRequest):
    try:
        return KnowledgeCardResponse(**await assets.update_card(card_id, req.model_dump(exclude_unset=True)))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/knowledge/cards/{card_id}/merge", response_model=KnowledgeCardResponse)
@limiter.limit("20/minute")
async def merge_knowledge_card(request: Request, card_id: str, req: KnowledgeCardMergeRequest):
    try:
        return KnowledgeCardResponse(**await assets.merge_card(card_id, req.target_card_id))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete("/knowledge/cards/{card_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_knowledge_card(request: Request, card_id: str):
    await assets.delete_card(card_id)
    return None


@router.get("/writing/snippets", response_model=list[WritingSnippetResponse])
@limiter.limit("60/minute")
async def list_writing_snippets(request: Request, section_hint: str = "", paper_id: str = ""):
    return [WritingSnippetResponse(**row) for row in await assets.list_snippets(section_hint, paper_id)]


@router.post("/writing/snippets", response_model=WritingSnippetResponse)
@limiter.limit("30/minute")
async def create_writing_snippet(request: Request, req: WritingSnippetCreateRequest):
    try:
        return WritingSnippetResponse(**await assets.create_snippet(req.model_dump()))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.patch("/writing/snippets/{snippet_id}", response_model=WritingSnippetResponse)
@limiter.limit("30/minute")
async def update_writing_snippet(request: Request, snippet_id: str, req: WritingSnippetUpdateRequest):
    try:
        return WritingSnippetResponse(**await assets.update_snippet(snippet_id, req.model_dump(exclude_unset=True)))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete("/writing/snippets/{snippet_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_writing_snippet(request: Request, snippet_id: str):
    await assets.delete_snippet(snippet_id)
    return None


@router.get("/library/local-search", response_model=LocalSearchResponse)
@limiter.limit("60/minute")
async def local_library_search(request: Request, mode: str = "cards", query: str = "", limit: int = 20):
    return LocalSearchResponse(**await assets.local_search(mode, query, limit))


@router.get("/writing/export/markdown", response_model=ExportResponse)
@limiter.limit("30/minute")
async def export_writing_markdown(request: Request, section_hint: str = "", mode: str = "traceable"):
    return ExportResponse(content=await assets.export_snippets_markdown(section_hint, mode=mode))


@router.post("/writing/compose-related-work", response_model=WritingSnippetResponse)
@limiter.limit("20/minute")
async def compose_related_work(request: Request, req: RelatedWorkComposeRequest):
    try:
        return WritingSnippetResponse(
            **await assets.compose_related_work_snippet(req.card_ids, section_hint=req.section_hint)
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/writing/comparison-table")
@limiter.limit("30/minute")
async def build_comparison_table(request: Request, req: ComparisonTableRequest):
    try:
        return await assets.build_comparison_table(req.paper_ids)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/writing/export/obsidian", response_model=ExportResponse)
@limiter.limit("30/minute")
async def export_obsidian_markdown(request: Request):
    return ExportResponse(content=await assets.export_obsidian_markdown())


@router.get("/papers/export/bibtex", response_model=ExportResponse)
@limiter.limit("30/minute")
async def export_papers_bibtex(request: Request, collection_id: str = ""):
    return ExportResponse(content=await assets.export_bibtex(collection_id))


@router.get("/papers/export/ris", response_model=ExportResponse)
@limiter.limit("30/minute")
async def export_papers_ris(request: Request, collection_id: str = ""):
    return ExportResponse(content=await assets.export_ris(collection_id))


@router.get("/papers/export/zotero-csl-json", response_model=ExportResponse)
@limiter.limit("30/minute")
async def export_papers_zotero_csl_json(request: Request, collection_id: str = ""):
    return ExportResponse(content=await assets.export_zotero_csl_json(collection_id))


@router.post("/papers/import-references", response_model=ImportResponse)
@limiter.limit("10/minute")
async def import_paper_references(request: Request, req: ReferenceImportRequest):
    return ImportResponse(**await assets.import_references(req.content, req.format))


@router.get("/knowledge/duplicates", response_model=DuplicateCandidatesResponse)
@limiter.limit("30/minute")
async def get_duplicate_candidates(request: Request):
    return DuplicateCandidatesResponse(candidates=await assets.duplicate_candidates())


@router.get("/health/knowledge", response_model=KnowledgeHealthResponse)
@limiter.limit("30/minute")
async def knowledge_health(request: Request):
    return KnowledgeHealthResponse(**await assets.health_report())


@router.post("/health/knowledge/fix", response_model=HealthFixResponse)
@limiter.limit("10/minute")
async def fix_knowledge_health_issue(request: Request, req: HealthFixRequest):
    return HealthFixResponse(**await assets.fix_health_issue(req.issue_type, req.paper_ids))
