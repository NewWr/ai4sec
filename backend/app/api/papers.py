from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from app.config import get_settings
from app.db import database as db
from app.rate_limit import limiter
from app.models.paper_ir import Block, PaperIR, Section
from app.models.schemas import (
    AnalysisDifySyncStatusResponse,
    DifySyncStatusResponse,
    DiscoveryGapStatusRequest,
    DiscoveryRelationStatusRequest,
    PaperCollectionAssignRequest,
    PaperCollectionConfirmRequest,
    PaperCollectionConfirmResponse,
    PaperCollectionCreateRequest,
    PaperCollectionItemResponse,
    PaperCollectionResponse,
    PaperCollectionsResponse,
    PaperCollectionSuggestRequest,
    PaperCollectionSuggestResponse,
    PaperCollectionUpdateRequest,
    PaperDisplayResponse,
    PaperLibraryItemResponse,
    PapersDiscoveryResponse,
    PaperResponse,
    PaperRunSummary,
    PaperSyncStatusResponse,
    PaperUploadResponse,
    PaperUpdateRequest,
    ResearchConstructionFeedbackRequest,
    ResearchConstructionJobResponse,
    ResearchConstructionRequest,
)
from app.api.admin import require_admin_token
from app.services.dify_sync import sync_paper_ir_to_dify
from app.services.knowledge_spaces import MAIN_SOURCE_SPACE_ID, add_item_to_space
from app.services.paper_collections import (
    assign_paper_to_collection,
    confirm_collection_choice,
    create_collection,
    delete_collection,
    ensure_default_collection,
    ensure_unassigned_papers_default,
    list_collection_items,
    list_collection_rows,
    move_paper_to_collection,
    suggest_collection_for_paper,
    update_collection,
)
from app.services.research_discovery import build_research_discovery
from app.services import research_discovery
from app.services import research_construction

router = APIRouter(tags=["papers"])

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
PDF_PRIVATE_CACHE_SECONDS = 86400

# Figure images extracted by MinerU are named as a content hash + extension.
# Restrict to that shape so the filename can never contain path separators.
_SAFE_IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.(jpg|jpeg|png|gif|webp)$", re.IGNORECASE)
_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_status_from_row(paper_id: str, row: dict | None) -> DifySyncStatusResponse:
    if not row:
        return DifySyncStatusResponse(paper_id=paper_id)
    return DifySyncStatusResponse(
        paper_id=paper_id,
        dataset_id=str(row.get("dataset_id") or ""),
        document_id=str(row.get("dify_document_id") or ""),
        source_hash=str(row.get("source_hash") or ""),
        status=str(row.get("status") or "not_synced"),
        attempts=int(row.get("attempts") or 0),
        error_msg=str(row.get("error_msg") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _analysis_sync_status_from_row(row: dict) -> AnalysisDifySyncStatusResponse:
    return AnalysisDifySyncStatusResponse(
        run_id=str(row.get("run_id") or ""),
        paper_id=str(row.get("paper_id") or ""),
        dataset_id=str(row.get("dataset_id") or ""),
        document_id=str(row.get("dify_document_id") or ""),
        source_hash=str(row.get("source_hash") or ""),
        status=str(row.get("status") or "not_synced"),
        attempts=int(row.get("attempts") or 0),
        error_msg=str(row.get("error_msg") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


async def _latest_dify_sync(paper_id: str) -> dict | None:
    return await db.fetch_one(
        """
        SELECT * FROM dify_syncs
         WHERE paper_id = ?
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        (paper_id,),
    )


async def _load_paper_ir_from_blocks(paper_id: str) -> PaperIR:
    rows = await db.fetch_all(
        "SELECT * FROM blocks WHERE paper_id = ? ORDER BY order_idx ASC",
        (paper_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="PaperIR blocks not found; run analysis first")

    blocks: list[Block] = []
    title = ""
    for row in rows:
        block = Block(
            type=str(row.get("type") or ""),
            sub_type=str(row.get("sub_type") or ""),
            page_idx=int(row.get("page_idx") or 0),
            bbox=[],
            text=str(row.get("text") or ""),
            section_path=str(row.get("section_path") or ""),
            order_idx=int(row.get("order_idx") or 0),
        )
        if not title and block.type == "title" and block.text.strip():
            title = block.text.strip()
        blocks.append(block)

    paper = await db.fetch_one("SELECT title FROM papers WHERE paper_id = ?", (paper_id,))
    title = str((paper or {}).get("title") or title or "")

    sections: list[Section] = []
    by_path: dict[str, list[Block]] = {}
    for block in blocks:
        key = block.section_path or ""
        by_path.setdefault(key, []).append(block)
    for path, section_blocks in by_path.items():
        heading = path.split("/")[-1] if path else ""
        sections.append(Section(path=path, title=heading, blocks=section_blocks))

    return PaperIR(paper_id=paper_id, title=title, sections=sections, blocks=blocks)


def _collection_response(row: dict) -> PaperCollectionResponse:
    return PaperCollectionResponse(
        collection_id=str(row.get("collection_id") or ""),
        parent_id=str(row.get("parent_id") or ""),
        name=str(row.get("name") or ""),
        name_zh=str(row.get("name_zh") or ""),
        description=str(row.get("description") or ""),
        description_zh=str(row.get("description_zh") or ""),
        sort_order=int(row.get("sort_order") or 0),
        paper_count=int(row.get("paper_count") or 0),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _collection_item_response(row: dict) -> PaperCollectionItemResponse:
    return PaperCollectionItemResponse(
        collection_id=str(row.get("collection_id") or ""),
        paper_id=str(row.get("paper_id") or ""),
        is_primary=bool(row.get("is_primary") or 0),
        note=str(row.get("note") or ""),
        note_zh=str(row.get("note_zh") or ""),
        sort_order=int(row.get("sort_order") or 0),
        updated_at=str(row.get("updated_at") or ""),
    )


def _display_response(row: dict | None) -> PaperDisplayResponse:
    if not row:
        return PaperDisplayResponse()
    return PaperDisplayResponse(
        title_zh=str(row.get("title_zh") or ""),
        summary_en=str(row.get("summary_en") or ""),
        summary_zh=str(row.get("summary_zh") or ""),
        translation_status=str(row.get("translation_status") or "pending"),
        updated_at=str(row.get("updated_at") or ""),
    )


def _clean_paper_update(req: PaperUpdateRequest) -> tuple[str, str, str, int, str, str, str]:
    title = (req.title or "").strip() if req.title is not None else ""
    doi = (req.doi or "").strip() if req.doi is not None else ""
    venue = (req.venue or "").strip() if req.venue is not None else ""
    sci_rank = (req.sci_rank or "").strip() if req.sci_rank is not None else ""
    ccf_rank = (req.ccf_rank or "").strip() if req.ccf_rank is not None else ""
    citation_key = (req.citation_key or "").strip() if req.citation_key is not None else ""
    year = int(req.year or 0) if req.year is not None else 0
    if year < 0 or year > 3000:
        raise ValueError("Invalid publication year")
    return title, doi, venue, year, sci_rank, ccf_rank, citation_key


@router.post("/papers/upload", response_model=PaperUploadResponse)
@limiter.limit("5/minute")
async def upload_paper(request: Request, file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    header = b""
    total = 0
    tmp_path = Path(tempfile.mkstemp(prefix="paper-", suffix=".pdf.part", dir=upload_dir)[1])
    try:
        with tmp_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if len(header) < 1024:
                    header += chunk[: 1024 - len(header)]
                total += len(chunk)
                if total > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (max {MAX_UPLOAD_SIZE // (1024 * 1024)} MB)",
                    )
                out.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="Empty file")
        if not header.lstrip().startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="File is not a valid PDF")

        paper_id = await asyncio.to_thread(_sha1_file, tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    paper_dir = settings.data_dir / "papers" / paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = paper_dir / "original.pdf"
    if not pdf_path.exists():
        tmp_path.replace(pdf_path)
    else:
        tmp_path.unlink(missing_ok=True)

    existing = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (paper_id,))
    if existing:
        await add_item_to_space(
            space_id=MAIN_SOURCE_SPACE_ID,
            item_kind="paper",
            item_id=paper_id,
            paper_id=paper_id,
            source_type="upload",
            sync_status="pending",
            note="User uploaded PDF",
        )
        return PaperUploadResponse(paper_id=paper_id, message="Paper already exists")

    rel_path = f"papers/{paper_id}/original.pdf"
    await db.execute(
        "INSERT INTO papers (paper_id, file_path, original_filename) VALUES (?, ?, ?)",
        (paper_id, rel_path, file.filename),
    )
    await ensure_default_collection()
    await assign_paper_to_collection(
        paper_id=paper_id,
        collection_id="unclassified",
        is_primary=True,
    )
    await add_item_to_space(
        space_id=MAIN_SOURCE_SPACE_ID,
        item_kind="paper",
        item_id=paper_id,
        paper_id=paper_id,
        source_type="upload",
        sync_status="pending",
        note="User uploaded PDF",
    )
    return PaperUploadResponse(paper_id=paper_id, message="Upload successful")


@router.get("/papers", response_model=list[PaperLibraryItemResponse])
@limiter.limit("30/minute")
async def list_papers(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    reading_status: str = "",
    priority: str = "",
    decision: str = "",
    collection_id: str = "",
    sync_status: str = "",
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    await ensure_unassigned_papers_default()
    clauses: list[str] = []
    params: list[object] = []
    if reading_status:
        clauses.append("p.reading_status = ?")
        params.append(reading_status)
    if priority:
        clauses.append("p.priority = ?")
        params.append(priority)
    if decision:
        clauses.append("p.decision = ?")
        params.append(decision)
    if collection_id:
        clauses.append(
            "EXISTS (SELECT 1 FROM paper_collection_items pci_filter "
            "WHERE pci_filter.paper_id = p.paper_id AND pci_filter.collection_id = ?)"
        )
        params.append(collection_id)
    if sync_status:
        clauses.append("COALESCE(ds.status, 'not_synced') = ?")
        params.append(sync_status)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.fetch_all(
        f"""
        SELECT
            p.*,
            COALESCE(mp.status, '') AS parse_status,
            COALESCE(mp.updated_at, '') AS parse_updated_at,
            COALESCE(ds.dataset_id, '') AS dify_dataset_id,
            COALESCE(ds.dify_document_id, '') AS dify_document_id,
            COALESCE(ds.source_hash, '') AS dify_source_hash,
            COALESCE(ds.status, '') AS dify_status,
            COALESCE(ds.attempts, 0) AS dify_attempts,
            COALESCE(ds.error_msg, '') AS dify_error_msg,
            COALESCE(ds.updated_at, '') AS dify_updated_at,
            lr.run_id AS latest_run_id,
            lr.mode AS latest_run_mode,
            lr.status AS latest_run_status,
            lr.started_at AS latest_run_started_at,
            lr.finished_at AS latest_run_finished_at,
            COALESCE(lr.current_step, '') AS latest_run_current_step,
            COALESCE(lr.user_question, '') AS latest_run_user_question,
            COALESCE(pc.collection_id, '') AS primary_collection_id,
            COALESCE(dc.title_zh, '') AS display_title_zh,
            COALESCE(dc.summary_en, '') AS display_summary_en,
            COALESCE(dc.summary_zh, '') AS display_summary_zh,
            COALESCE(dc.translation_status, 'pending') AS display_translation_status,
            COALESCE(dc.updated_at, '') AS display_updated_at
          FROM papers p
          LEFT JOIN (
            SELECT m1.*
              FROM mineru_parses m1
              JOIN (
                SELECT paper_id, MAX(created_at) AS max_created_at
                  FROM mineru_parses
                 GROUP BY paper_id
              ) mx
                ON mx.paper_id = m1.paper_id AND mx.max_created_at = m1.created_at
          ) mp ON mp.paper_id = p.paper_id
          LEFT JOIN (
            SELECT d1.*
              FROM dify_syncs d1
              JOIN (
                SELECT paper_id, MAX(updated_at) AS max_updated_at
                  FROM dify_syncs
                 GROUP BY paper_id
              ) dx
                ON dx.paper_id = d1.paper_id AND dx.max_updated_at = d1.updated_at
          ) ds ON ds.paper_id = p.paper_id
          LEFT JOIN (
            SELECT r1.*
              FROM runs r1
              JOIN (
                SELECT paper_id, MAX(started_at) AS max_started_at
                  FROM runs
                 GROUP BY paper_id
              ) rx
                ON rx.paper_id = r1.paper_id AND rx.max_started_at = r1.started_at
          ) lr ON lr.paper_id = p.paper_id
          LEFT JOIN paper_collection_items pc
            ON pc.paper_id = p.paper_id AND pc.is_primary = 1
          LEFT JOIN paper_display_cache dc
            ON dc.paper_id = p.paper_id
         {where_sql}
         ORDER BY p.created_at DESC
         LIMIT ? OFFSET ?
        """,
        tuple(params + [limit, offset]),
    )

    paper_ids = [str(row["paper_id"]) for row in rows]
    collection_rows = await db.fetch_all(
        f"""
        SELECT paper_id, collection_id
          FROM paper_collection_items
         WHERE paper_id IN ({','.join('?' for _ in paper_ids) if paper_ids else "''"})
         ORDER BY is_primary DESC, sort_order ASC
        """,
        tuple(paper_ids),
    ) if paper_ids else []
    collection_ids_by_paper: dict[str, list[str]] = {}
    for row in collection_rows:
        collection_ids_by_paper.setdefault(str(row["paper_id"]), []).append(str(row["collection_id"]))

    run_rows = await db.fetch_all(
        f"""
        SELECT *
          FROM runs
         WHERE paper_id IN ({','.join('?' for _ in paper_ids) if paper_ids else "''"})
         ORDER BY started_at DESC
        """,
        tuple(paper_ids),
    ) if paper_ids else []
    runs_by_paper: dict[str, list[PaperRunSummary]] = {}
    for row in run_rows:
        paper_id = str(row.get("paper_id") or "")
        bucket = runs_by_paper.setdefault(paper_id, [])
        if len(bucket) >= 8:
            continue
        bucket.append(
            PaperRunSummary(
                run_id=row["run_id"],
                mode=row.get("mode") or "",
                status=row.get("status") or "",
                started_at=row.get("started_at") or "",
                finished_at=row.get("finished_at"),
                current_step=row.get("current_step") or "",
                user_question=row.get("user_question") or "",
            )
        )

    items: list[PaperLibraryItemResponse] = []
    for row in rows:
        latest_run = None
        if row.get("latest_run_id"):
            latest_run = PaperRunSummary(
                run_id=row["latest_run_id"],
                mode=row.get("latest_run_mode") or "",
                status=row.get("latest_run_status") or "",
                started_at=row.get("latest_run_started_at") or "",
                finished_at=row.get("latest_run_finished_at"),
                current_step=row.get("latest_run_current_step") or "",
                user_question=row.get("latest_run_user_question") or "",
            )
        items.append(
            PaperLibraryItemResponse(
                paper_id=row["paper_id"],
                title=row.get("title") or "",
                doi=row.get("doi") or "",
                venue=row.get("venue") or "",
                year=row.get("year") or 0,
                sci_rank=row.get("sci_rank") or "",
                ccf_rank=row.get("ccf_rank") or "",
                citation_key=row.get("citation_key") or "",
                reading_status=row.get("reading_status") or "unread",
                priority=row.get("priority") or "medium",
                decision=row.get("decision") or "",
                personal_rating=row.get("personal_rating") or 0,
                read_progress=float(row.get("read_progress") or 0.0),
                last_read_at=row.get("last_read_at") or "",
                created_at=row["created_at"],
                parse_status=row.get("parse_status") or "",
                parse_updated_at=row.get("parse_updated_at") or "",
                primary_collection_id=row.get("primary_collection_id") or "",
                collection_ids=collection_ids_by_paper.get(str(row["paper_id"]), []),
                display=PaperDisplayResponse(
                    title_zh=row.get("display_title_zh") or "",
                    summary_en=row.get("display_summary_en") or "",
                    summary_zh=row.get("display_summary_zh") or "",
                    translation_status=row.get("display_translation_status") or "pending",
                    updated_at=row.get("display_updated_at") or "",
                ),
                latest_run=latest_run,
                runs=runs_by_paper.get(str(row["paper_id"]), []),
                dify_sync=DifySyncStatusResponse(
                    paper_id=row["paper_id"],
                    dataset_id=row.get("dify_dataset_id") or "",
                    document_id=row.get("dify_document_id") or "",
                    source_hash=row.get("dify_source_hash") or "",
                    status=row.get("dify_status") or "not_synced",
                    attempts=row.get("dify_attempts") or 0,
                    error_msg=row.get("dify_error_msg") or "",
                    updated_at=row.get("dify_updated_at") or "",
                ),
            )
        )
    return items


@router.get("/papers/collections", response_model=PaperCollectionsResponse)
@limiter.limit("30/minute")
async def get_paper_collections(request: Request):
    await ensure_unassigned_papers_default()
    return PaperCollectionsResponse(
        collections=[_collection_response(row) for row in await list_collection_rows()],
        items=[_collection_item_response(row) for row in await list_collection_items()],
    )


@router.post("/papers/collections", response_model=PaperCollectionResponse)
@limiter.limit("20/minute")
async def create_paper_collection(request: Request, req: PaperCollectionCreateRequest):
    try:
        row = await create_collection(
            name=req.name,
            name_zh=req.name_zh,
            description=req.description,
            description_zh=req.description_zh,
            parent_id=req.parent_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _collection_response(row)


@router.patch("/papers/collections/{collection_id}", response_model=PaperCollectionResponse)
@limiter.limit("20/minute")
async def update_paper_collection(request: Request, collection_id: str, req: PaperCollectionUpdateRequest):
    try:
        row = await update_collection(
            collection_id=collection_id,
            name=req.name,
            name_zh=req.name_zh,
            description=req.description,
            description_zh=req.description_zh,
            parent_id=req.parent_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _collection_response(row)


@router.delete("/papers/collections/{collection_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_paper_collection(request: Request, collection_id: str):
    try:
        await delete_collection(collection_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None


@router.post("/papers/{paper_id}/collection-suggestion", response_model=PaperCollectionSuggestResponse)
@limiter.limit("5/minute")
async def suggest_paper_collection(request: Request, paper_id: str, req: PaperCollectionSuggestRequest | None = None):
    try:
        data = await suggest_collection_for_paper(paper_id, (req.llm_model if req else "") or "")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    data["collections"] = [_collection_response(row) for row in data.get("collections", [])]
    return PaperCollectionSuggestResponse(**data)


@router.post("/papers/{paper_id}/collection-confirm", response_model=PaperCollectionConfirmResponse)
@limiter.limit("20/minute")
async def confirm_paper_collection(request: Request, paper_id: str, req: PaperCollectionConfirmRequest):
    try:
        data = await confirm_collection_choice(
            paper_id=paper_id,
            collection_id=req.collection_id,
            new_name=req.new_name,
            new_name_zh=req.new_name_zh,
            new_description=req.new_description,
            new_description_zh=req.new_description_zh,
            parent_id=req.parent_id,
            note=req.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PaperCollectionConfirmResponse(
        collection=_collection_response(data["collection"]),
        item=_collection_item_response(data["item"]),
    )


@router.post("/papers/{paper_id}/collection", response_model=PaperCollectionItemResponse)
@limiter.limit("20/minute")
async def assign_paper_collection(request: Request, paper_id: str, req: PaperCollectionAssignRequest):
    try:
        row = await assign_paper_to_collection(
            paper_id=paper_id,
            collection_id=req.collection_id,
            is_primary=req.is_primary,
            note=req.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _collection_item_response(row)


@router.post("/papers/{paper_id}/collection/move", response_model=PaperCollectionItemResponse)
@limiter.limit("20/minute")
async def move_paper_collection(request: Request, paper_id: str, req: PaperCollectionAssignRequest):
    try:
        row = await move_paper_to_collection(
            paper_id=paper_id,
            collection_id=req.collection_id,
            note=req.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _collection_item_response(row)


@router.get("/papers/discovery", response_model=PapersDiscoveryResponse)
@limiter.limit("30/minute")
async def get_papers_discovery(request: Request, limit: int = 200):
    limit = max(1, min(limit, 500))
    return await build_research_discovery(limit)


@router.post("/papers/discovery/gaps/{gap_id}/status", response_model=PapersDiscoveryResponse)
@limiter.limit("30/minute")
async def update_discovery_gap_status(request: Request, gap_id: str, req: DiscoveryGapStatusRequest):
    try:
        await research_discovery.update_gap_status(gap_id, req.model_dump())
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return await build_research_discovery(200)


@router.post("/papers/discovery/relations/{relation_id}/status", response_model=PapersDiscoveryResponse)
@limiter.limit("30/minute")
async def update_discovery_relation_status(request: Request, relation_id: str, req: DiscoveryRelationStatusRequest):
    row = await db.fetch_one("SELECT relation_id FROM research_relation_edges WHERE relation_id = ?", (relation_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Relation not found")
    await db.execute(
        """
        UPDATE research_relation_edges
           SET status = ?,
               updated_at = datetime('now')
         WHERE relation_id = ?
        """,
        (req.status, relation_id),
    )
    return await build_research_discovery(200)


@router.post(
    "/discovery/construct",
    response_model=ResearchConstructionJobResponse,
    dependencies=[Depends(require_admin_token)],
)
@limiter.limit("10/minute")
async def start_research_construction(
    request: Request,
    req: ResearchConstructionRequest | None = None,
    dry_run: int = 0,
):
    body = req or ResearchConstructionRequest()
    job = await research_construction.start_construction_job(
        dry_run=bool(dry_run) or body.dry_run,
        force=body.force,
        trigger_source="manual",
    )
    return ResearchConstructionJobResponse(**job)


@router.get("/discovery/construct/{job_id}", response_model=ResearchConstructionJobResponse)
@limiter.limit("30/minute")
async def get_research_construction_job(request: Request, job_id: str):
    try:
        return ResearchConstructionJobResponse(**await research_construction.get_job(job_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/discovery/construct-state")
@limiter.limit("30/minute")
async def get_research_construction_state(request: Request):
    estimate, state = await asyncio.gather(
        research_construction.estimate_plan(),
        research_construction.get_state(),
    )
    return {"estimate": estimate, "state": state}


@router.post("/discovery/gaps/{gap_id}/feedback")
@limiter.limit("30/minute")
async def record_research_idea_feedback(
    request: Request,
    gap_id: str,
    req: ResearchConstructionFeedbackRequest,
):
    try:
        return await research_construction.record_idea_feedback(gap_id, req.verdict, req.reason)
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.patch("/papers/{paper_id}", response_model=PaperResponse)
@limiter.limit("20/minute")
async def update_paper_metadata(request: Request, paper_id: str, req: PaperUpdateRequest):
    paper = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (paper_id,))
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        title, doi, venue, year, sci_rank, ccf_rank, citation_key = _clean_paper_update(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    fields: list[str] = []
    params: list[object] = []
    for column, value, provided in (
        ("title", title, req.title is not None),
        ("doi", doi, req.doi is not None),
        ("venue", venue, req.venue is not None),
        ("year", year, req.year is not None),
        ("sci_rank", sci_rank, req.sci_rank is not None),
        ("ccf_rank", ccf_rank, req.ccf_rank is not None),
        ("citation_key", citation_key, req.citation_key is not None),
    ):
        if provided:
            fields.append(f"{column} = ?")
            params.append(value)
    if fields:
        await db.execute(
            f"UPDATE papers SET {', '.join(fields)} WHERE paper_id = ?",
            tuple(params + [paper_id]),
        )

    if req.title_zh is not None or req.summary_zh is not None:
        current = await db.fetch_one("SELECT * FROM paper_display_cache WHERE paper_id = ?", (paper_id,))
        await db.execute(
            """
            INSERT INTO paper_display_cache (
                paper_id, title_zh, summary_source, summary_en, summary_zh,
                source_hash, translation_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'manual', datetime('now'))
            ON CONFLICT(paper_id) DO UPDATE SET
                title_zh = excluded.title_zh,
                summary_zh = excluded.summary_zh,
                translation_status = 'manual',
                updated_at = datetime('now')
            """,
            (
                paper_id,
                req.title_zh.strip() if req.title_zh is not None else str((current or {}).get("title_zh") or ""),
                str((current or {}).get("summary_source") or ""),
                str((current or {}).get("summary_en") or ""),
                req.summary_zh.strip() if req.summary_zh is not None else str((current or {}).get("summary_zh") or ""),
                str((current or {}).get("source_hash") or "manual"),
            ),
        )
    updated = await db.fetch_one("SELECT * FROM papers WHERE paper_id = ?", (paper_id,))
    if not updated:
        raise HTTPException(status_code=404, detail="Paper not found")
    return PaperResponse(**updated)


@router.delete("/papers/{paper_id}", status_code=204)
@limiter.limit("10/minute")
async def delete_paper(request: Request, paper_id: str):
    row = await db.fetch_one("SELECT file_path FROM papers WHERE paper_id = ?", (paper_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Paper not found")

    run_rows = await db.fetch_all("SELECT run_id FROM runs WHERE paper_id = ?", (paper_id,))
    run_ids = [str(run["run_id"]) for run in run_rows]
    if run_ids:
        run_placeholders = ",".join("?" for _ in run_ids)
        card_rows = await db.fetch_all(
            f"SELECT card_id FROM knowledge_cards WHERE paper_id = ? OR run_id IN ({run_placeholders})",
            tuple([paper_id, *run_ids]),
        )
    else:
        card_rows = await db.fetch_all("SELECT card_id FROM knowledge_cards WHERE paper_id = ?", (paper_id,))
    card_ids = [str(card["card_id"]) for card in card_rows]
    if card_ids:
        card_placeholders = ",".join("?" for _ in card_ids)
        snippet_rows = await db.fetch_all(
            f"SELECT snippet_id FROM writing_snippets WHERE paper_id = ? OR source_card_id IN ({card_placeholders})",
            tuple([paper_id, *card_ids]),
        )
    else:
        snippet_rows = await db.fetch_all("SELECT snippet_id FROM writing_snippets WHERE paper_id = ?", (paper_id,))
    snippet_ids = [str(snippet["snippet_id"]) for snippet in snippet_rows]
    evidence_rows = await db.fetch_all("SELECT evidence_id FROM research_evidence_items WHERE paper_id = ?", (paper_id,))
    evidence_ids = [str(evidence["evidence_id"]) for evidence in evidence_rows]
    async with db.transaction() as conn:
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            await conn.execute(f"DELETE FROM sphere_edges WHERE run_id IN ({placeholders})", tuple(run_ids))
            await conn.execute(f"DELETE FROM sphere_nodes WHERE run_id IN ({placeholders})", tuple(run_ids))
            await conn.execute(f"DELETE FROM run_outputs WHERE run_id IN ({placeholders})", tuple(run_ids))
            await conn.execute(f"DELETE FROM run_progress_events WHERE run_id IN ({placeholders})", tuple(run_ids))
            await conn.execute(f"DELETE FROM analysis_dify_syncs WHERE paper_id = ? OR run_id IN ({placeholders})", tuple([paper_id, *run_ids]))
            await conn.execute(f"DELETE FROM ai_review_marks WHERE paper_id = ? OR run_id IN ({placeholders})", tuple([paper_id, *run_ids]))
            await conn.execute(f"DELETE FROM knowledge_card_generations WHERE paper_id = ? OR run_id IN ({placeholders})", tuple([paper_id, *run_ids]))
            await conn.execute(
                f"""
                UPDATE daily_recommendation_items
                   SET linked_paper_id = '',
                       linked_run_id = '',
                       status = CASE WHEN status IN ('ingested', 'promoted') THEN 'candidate' ELSE status END,
                       error_msg = ''
                 WHERE linked_paper_id = ? OR linked_run_id IN ({placeholders})
                """,
                tuple([paper_id, *run_ids]),
            )
            await conn.execute(f"DELETE FROM knowledge_space_items WHERE paper_id = ? OR run_id IN ({placeholders})", tuple([paper_id, *run_ids]))
        else:
            await conn.execute(
                """
                UPDATE daily_recommendation_items
                   SET linked_paper_id = '',
                       linked_run_id = '',
                       status = CASE WHEN status IN ('ingested', 'promoted') THEN 'candidate' ELSE status END,
                       error_msg = ''
                 WHERE linked_paper_id = ?
                """,
                (paper_id,),
            )
            await conn.execute("DELETE FROM knowledge_space_items WHERE paper_id = ? OR item_id = ?", (paper_id, paper_id))

        await conn.execute("DELETE FROM analysis_dify_syncs WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM paper_annotations WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM paper_notes WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM ai_review_marks WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM knowledge_card_generations WHERE paper_id = ?", (paper_id,))
        if card_ids:
            placeholders = ",".join("?" for _ in card_ids)
            await conn.execute(f"DELETE FROM research_evidence_cards WHERE card_id IN ({placeholders})", tuple(card_ids))
            await conn.execute(f"DELETE FROM knowledge_space_items WHERE item_id IN ({placeholders})", tuple(card_ids))
        if snippet_ids:
            placeholders = ",".join("?" for _ in snippet_ids)
            await conn.execute(f"DELETE FROM knowledge_space_items WHERE item_id IN ({placeholders})", tuple(snippet_ids))
        if evidence_ids:
            placeholders = ",".join("?" for _ in evidence_ids)
            await conn.execute(f"DELETE FROM research_evidence_cards WHERE evidence_id IN ({placeholders})", tuple(evidence_ids))
        if card_ids:
            placeholders = ",".join("?" for _ in card_ids)
            await conn.execute(f"DELETE FROM writing_snippets WHERE paper_id = ? OR source_card_id IN ({placeholders})", tuple([paper_id, *card_ids]))
        else:
            await conn.execute("DELETE FROM writing_snippets WHERE paper_id = ?", (paper_id,))
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            await conn.execute(f"DELETE FROM knowledge_cards WHERE paper_id = ? OR run_id IN ({placeholders})", tuple([paper_id, *run_ids]))
        else:
            await conn.execute("DELETE FROM knowledge_cards WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM runs WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM research_relation_edges WHERE source_paper_id = ? OR target_paper_id = ?", (paper_id, paper_id))
        await conn.execute("DELETE FROM research_evidence_items WHERE paper_id = ?", (paper_id,))
        try:
            await conn.execute("DELETE FROM paper_node_fts WHERE paper_id = ?", (paper_id,))
        except Exception:
            pass
        await conn.execute("DELETE FROM paper_nodes WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM blocks WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM mineru_parses WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM dify_syncs WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM paper_collection_items WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM paper_display_cache WHERE paper_id = ?", (paper_id,))
        await conn.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))

    settings = get_settings()
    stored_path = (settings.data_dir / str(row.get("file_path") or "")).resolve()
    paper_dir = (settings.data_dir / "papers" / paper_id).resolve()
    data_root = settings.data_dir.resolve()
    for path in (paper_dir, stored_path.parent):
        if path.is_relative_to(data_root) and path.name == paper_id and path.exists():
            shutil.rmtree(path, ignore_errors=True)
    return None


@router.get("/papers/{paper_id}", response_model=PaperResponse)
@limiter.limit("30/minute")
async def get_paper(request: Request, paper_id: str):
    row = await db.fetch_one("SELECT * FROM papers WHERE paper_id = ?", (paper_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Paper not found")
    return PaperResponse(**row)


@router.get("/papers/{paper_id}/sync-status", response_model=PaperSyncStatusResponse)
@limiter.limit("30/minute")
async def get_paper_sync_status(request: Request, paper_id: str):
    paper = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (paper_id,))
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    paper_sync = _sync_status_from_row(paper_id, await _latest_dify_sync(paper_id))
    analysis_rows = await db.fetch_all(
        """
        SELECT * FROM analysis_dify_syncs
         WHERE paper_id = ?
         ORDER BY updated_at DESC
        """,
        (paper_id,),
    )
    return PaperSyncStatusResponse(
        paper=paper_sync,
        analysis=[_analysis_sync_status_from_row(row) for row in analysis_rows],
    )


@router.post("/papers/{paper_id}/sync-dify", response_model=DifySyncStatusResponse)
@limiter.limit("10/minute")
async def retry_paper_dify_sync(request: Request, paper_id: str):
    paper = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (paper_id,))
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    paper_ir = await _load_paper_ir_from_blocks(paper_id)
    result = await sync_paper_ir_to_dify(paper_id, paper_ir, force=True)
    row = await _latest_dify_sync(paper_id)
    status = _sync_status_from_row(paper_id, row)
    if result.status == "skipped" and not row:
        return DifySyncStatusResponse(paper_id=paper_id, status="skipped", error_msg=result.message)
    return status


@router.get("/papers/{paper_id}/pdf")
@limiter.limit("600/minute")
async def get_paper_pdf(request: Request, paper_id: str):
    row = await db.fetch_one("SELECT file_path FROM papers WHERE paper_id = ?", (paper_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Paper not found")

    settings = get_settings()
    pdf_path = (settings.data_dir / row["file_path"]).resolve()

    # Path traversal guard: resolved path must stay inside data_dir
    if not pdf_path.is_relative_to(settings.data_dir.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    stat = pdf_path.stat()
    etag = f'"{paper_id}-{stat.st_size}-{int(stat.st_mtime)}"'
    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": f"private, max-age={PDF_PRIVATE_CACHE_SECONDS}, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{paper_id}.pdf"',
            "Cache-Control": f"private, max-age={PDF_PRIVATE_CACHE_SECONDS}, immutable",
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/papers/{paper_id}/images/{filename}")
@limiter.limit("120/minute")
async def get_paper_image(request: Request, paper_id: str, filename: str):
    """Serve a MinerU-extracted figure image so reports can embed it inline.

    The file is located under the paper's own MinerU output (``.../images/``);
    the filename is restricted to a safe pattern and the resolved path is
    confirmed to stay inside ``data_dir`` to prevent path traversal.
    """
    if not _SAFE_IMAGE_NAME_RE.match(filename):
        raise HTTPException(status_code=404, detail="Image not found")

    settings = get_settings()
    data_root = settings.data_dir.resolve()
    mineru_dir = (settings.data_dir / "papers" / paper_id / "mineru").resolve()
    if not mineru_dir.is_relative_to(data_root) or not mineru_dir.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    match: Path | None = None
    for cand in mineru_dir.rglob(filename):
        if cand.is_file() and cand.parent.name == "images":
            match = cand.resolve()
            break
    if match is None or not match.is_relative_to(data_root):
        raise HTTPException(status_code=404, detail="Image not found")

    media_type = _IMAGE_MEDIA_TYPES.get(match.suffix.lower(), "application/octet-stream")
    return FileResponse(path=str(match), media_type=media_type)
