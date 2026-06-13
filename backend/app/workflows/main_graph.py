from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from langgraph.graph import END, StateGraph

from app.config import get_settings
from app.db import database as db
from app.services import mineru_adapter
from app.services.dify_sync import sync_analysis_to_dify, sync_paper_ir_to_dify
from app.services.http_clients import get_default_http_client
from app.services.knowledge_spaces import analysis_dataset_for_run, source_dataset_for_paper
from app.services.paper_ir import build_and_store_paper_ir, clear_cached_paper_ir, get_cached_paper_ir
from app.services.paper_collections import refresh_paper_display_cache
from app.services.paper_partitioner import partition_paper_ir, partitions_to_jsonable
from app.services.supplementary_indexer import build_supplementary_index
from app.workflows.progress import emit_progress as _emit_progress
from app.workflows.state import MainGraphState
from app.workflows.translate import translate_output

logger = logging.getLogger("scholar.graph")


async def ingest_pdf(state: MainGraphState) -> dict[str, Any]:
    """Verify PDF exists and set path."""
    t0 = time.perf_counter()
    paper_id = state["paper_id"]
    settings = get_settings()
    pdf_path = settings.data_dir / "papers" / paper_id / "original.pdf"

    if not pdf_path.exists():
        logger.error(f"[{paper_id}] ingest_pdf: PDF not found at {pdf_path}")
        return {"error": f"PDF not found: {pdf_path}"}

    size_mb = pdf_path.stat().st_size / 1024 / 1024
    logger.info(f"[{paper_id}] ingest_pdf: OK ({size_mb:.1f} MB) in {time.perf_counter()-t0:.2f}s")
    return {
        "pdf_path": str(pdf_path),
        "progress": state.get("progress", []) + [{"step": "ingest_pdf", "status": "done"}],
    }


async def mineru_parse(state: MainGraphState) -> dict[str, Any]:
    """Run MinerU parsing on the PDF."""
    if state.get("error"):
        return {}

    t0 = time.perf_counter()
    paper_id = state["paper_id"]

    # Check if already parsed
    existing = await db.fetch_one(
        "SELECT parse_id, status, output_dir FROM mineru_parses WHERE paper_id = ? AND status = 'done' ORDER BY created_at DESC LIMIT 1",
        (paper_id,),
    )
    if existing and existing["output_dir"]:
        output_dir = Path(existing["output_dir"])
        if output_dir.exists():
            logger.info(f"[{paper_id}] mineru_parse: CACHED (parse_id={existing['parse_id']}) in {time.perf_counter()-t0:.2f}s")
            return {
                "parse_id": existing["parse_id"],
                "output_dir": str(output_dir),
                "progress": state.get("progress", []) + [{"step": "mineru_parse", "status": "done", "cached": True}],
            }

    parse_id = uuid.uuid4().hex[:16]
    await db.execute(
        "INSERT INTO mineru_parses (parse_id, paper_id, status) VALUES (?, ?, 'pending')",
        (parse_id, paper_id),
    )

    logger.info(f"[{paper_id}] mineru_parse: Starting MinerU API parse (parse_id={parse_id})...")
    try:
        await _emit_progress(
            state.get("run_id", ""),
            "mineru_parse",
            "running",
            parse_id=parse_id,
        )
        output_dir = await mineru_adapter.parse_pdf(paper_id, parse_id)
        elapsed = time.perf_counter() - t0
        logger.info(f"[{paper_id}] mineru_parse: DONE in {elapsed:.1f}s -> {output_dir}")
        return {
            "parse_id": parse_id,
            "output_dir": str(output_dir),
            "progress": state.get("progress", []) + [{"step": "mineru_parse", "status": "done"}],
        }
    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.error(f"[{paper_id}] mineru_parse: FAILED in {elapsed:.1f}s — {e}")
        return {
            "error": f"MinerU parse failed: {e}",
            "progress": state.get("progress", []) + [{"step": "mineru_parse", "status": "failed", "error": str(e)}],
        }


async def build_paper_ir(state: MainGraphState) -> dict[str, Any]:
    """Build PaperIR from MinerU output."""
    if state.get("error"):
        return {}

    t0 = time.perf_counter()
    output_dir = Path(state["output_dir"])
    paper_id = state["paper_id"]

    logger.info(f"[{paper_id}] build_paper_ir: Parsing content_list from {output_dir}...")
    try:
        paper_ir = await build_and_store_paper_ir(output_dir, paper_id)
        elapsed = time.perf_counter() - t0
        logger.info(
            f"[{paper_id}] build_paper_ir: DONE in {elapsed:.2f}s — "
            f"title='{paper_ir.title[:60]}' blocks={len(paper_ir.blocks)} sections={len(paper_ir.sections)}"
        )
        return {
            "paper_ir_json": paper_ir.model_dump_json(),
            "progress": state.get("progress", []) + [{"step": "build_paper_ir", "status": "done"}],
        }
    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.error(f"[{paper_id}] build_paper_ir: FAILED in {elapsed:.2f}s — {e}")
        return {
            "error": f"PaperIR build failed: {e}",
            "progress": state.get("progress", []) + [{"step": "build_paper_ir", "status": "failed", "error": str(e)}],
        }


async def detect_document_parts(state: MainGraphState) -> dict[str, Any]:
    """Detect main body, References, Appendix, and Supplementary partitions."""
    if state.get("error"):
        return {}

    paper_id = state["paper_id"]
    settings = get_settings()
    if not settings.document_partition_enabled:
        return {
            "document_partitions_json": "[]",
            "supplementary_index_json": json.dumps({"paper_id": paper_id, "sections": []}, ensure_ascii=False),
            "progress": state.get("progress", []) + [{"step": "detect_document_parts", "status": "skipped"}],
        }

    t0 = time.perf_counter()
    try:
        paper_ir = get_cached_paper_ir(state)
        partitions = partition_paper_ir(paper_ir)
        partitions_json = json.dumps(partitions_to_jsonable(partitions), ensure_ascii=False)
        supplementary_index = None
        if settings.supplementary_index_enabled:
            supplementary_index = build_supplementary_index(
                paper_ir,
                partitions,
                max_chars=settings.supplementary_max_index_chars,
            )
        supplementary_index_json = (
            supplementary_index.model_dump_json()
            if supplementary_index
            else json.dumps({"paper_id": paper_id, "sections": []}, ensure_ascii=False)
        )
        logger.info(
            "[%s] detect_document_parts: parts=%s supp_sections=%d in %.2fs",
            paper_id,
            [(p.part, p.page_start, p.page_end, round(p.confidence, 2)) for p in partitions],
            len(supplementary_index.sections) if supplementary_index else 0,
            time.perf_counter() - t0,
        )
        return {
            "document_partitions_json": partitions_json,
            "supplementary_index_json": supplementary_index_json,
            "progress": state.get("progress", []) + [
                {
                    "step": "detect_document_parts",
                    "status": "done",
                    "parts": len(partitions),
                    "supplementary_sections": len(supplementary_index.sections) if supplementary_index else 0,
                }
            ],
        }
    except Exception as e:
        logger.warning("[%s] detect_document_parts: failed in %.2fs — %s", paper_id, time.perf_counter() - t0, e)
        return {
            "document_partitions_json": "[]",
            "supplementary_index_json": json.dumps({"paper_id": paper_id, "sections": []}, ensure_ascii=False),
            "progress": state.get("progress", []) + [
                {"step": "detect_document_parts", "status": "failed", "error": str(e)}
            ],
        }


async def sync_dify_library(state: MainGraphState) -> dict[str, Any]:
    """Upload normalized PaperIR text into the configured Dify dataset.

    This node is non-blocking for paper analysis: Dify failures are persisted in
    dify_syncs and progress, but they do not stop Lens/Snap/Sphere.
    """
    if state.get("error"):
        return {}

    t0 = time.perf_counter()
    paper_id = state["paper_id"]
    try:
        paper_ir_json = state.get("paper_ir_json") or ""
        if not paper_ir_json:
            raise ValueError("paper_ir_json is empty")
        paper_ir = get_cached_paper_ir(state)
        dataset_id = await source_dataset_for_paper(paper_id)
        result = await sync_paper_ir_to_dify(paper_id, paper_ir, dataset_id=dataset_id)
        logger.info(
            "[%s] dify_sync: %s document_id=%s in %.2fs",
            paper_id,
            result.status,
            result.document_id or "-",
            time.perf_counter() - t0,
        )
        return {
            "dify_sync_json": json.dumps(
                {
                    "status": result.status,
                    "document_id": result.document_id,
                    "message": result.message,
                },
                ensure_ascii=False,
            ),
            "progress": state.get("progress", [])
            + [
                {
                    "step": "dify_sync",
                    "status": result.status,
                    "document_id": result.document_id,
                    "message": result.message,
                }
            ],
        }
    except Exception as e:
        logger.warning("[%s] dify_sync: failed in %.2fs — %s", paper_id, time.perf_counter() - t0, e)
        return {
            "dify_sync_json": json.dumps({"status": "failed", "document_id": "", "message": str(e)}),
            "progress": state.get("progress", []) + [{"step": "dify_sync", "status": "failed", "error": str(e)}],
        }


_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;\"')\]>]+)", re.ASCII)
_ARXIV_RE = re.compile(r"arXiv[:\s]*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)


async def _extract_doi_from_ir(state: MainGraphState) -> str:
    """Extract DOI from paper text blocks (prefer first few pages)."""
    ir = get_cached_paper_ir(state)
    # Search text blocks from early pages first
    for block in sorted(ir.blocks, key=lambda b: (b.page_idx, b.order_idx)):
        if block.page_idx > 3:
            break
        m = _DOI_RE.search(block.text)
        if m:
            doi = m.group(1).rstrip(".")
            return doi
    # Fallback: scan all blocks
    for block in ir.blocks:
        m = _DOI_RE.search(block.text)
        if m:
            doi = m.group(1).rstrip(".")
            return doi
    return ""


async def _extract_arxiv_id_from_ir(state: MainGraphState) -> str:
    """Extract arXiv ID (e.g. 2301.12345) from paper text blocks."""
    ir = get_cached_paper_ir(state)
    for block in sorted(ir.blocks, key=lambda b: (b.page_idx, b.order_idx)):
        if block.page_idx > 3:
            break
        m = _ARXIV_RE.search(block.text)
        if m:
            return m.group(1)
    for block in ir.blocks:
        m = _ARXIV_RE.search(block.text)
        if m:
            return m.group(1)
    return ""


async def _crossref_lookup(doi: str) -> dict[str, Any]:
    """Query Crossref API for venue and year. Returns {"venue": ..., "year": ...}."""
    if not doi:
        return {}
    settings = get_settings()
    url = f"{settings.crossref_api_base.rstrip('/')}/works/{doi}"
    try:
        client = get_default_http_client()
        resp = await client.get(url, headers={"User-Agent": "ScholarApp/1.0 (mailto:scholar@example.com)"}, timeout=15.0)
        resp.raise_for_status()
        data = resp.json().get("message", {})

        venue = ""
        container = data.get("container-title", [])
        if container:
            venue = container[0]

        year = 0
        for date_field in ("published-print", "published-online", "issued"):
            date_parts = data.get(date_field, {}).get("date-parts", [])
            if date_parts and date_parts[0] and date_parts[0][0]:
                year = int(date_parts[0][0])
                break

        return {"venue": venue, "year": year}
    except Exception as e:
        logger.warning("Crossref lookup failed for DOI %s: %s", doi, e)
        return {}


def _parse_s2_response(data: dict) -> dict[str, Any]:
    """Extract venue + year from Semantic Scholar paper record."""
    venue = ""
    pub_venue = data.get("publicationVenue") or {}
    if pub_venue.get("name"):
        venue = pub_venue["name"]
    if not venue:
        venue = data.get("venue", "")
    return {"venue": venue, "year": data.get("year", 0)}


async def _s2_lookup(doi: str = "", arxiv_id: str = "", title: str = "") -> dict[str, Any]:
    """Query Semantic Scholar for venue and year. Tries DOI -> arXiv -> title match."""
    fields = "venue,year,externalIds,publicationVenue"
    settings = get_settings()
    base_url = settings.semantic_scholar_api_base.rstrip("/")
    headers = {"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else {}

    client = get_default_http_client()
    if doi:
        try:
            resp = await client.get(
                f"{base_url}/graph/v1/paper/DOI:{doi}",
                params={"fields": fields},
                headers=headers,
                timeout=15.0,
            )
            if resp.status_code == 200:
                return _parse_s2_response(resp.json())
        except Exception as e:
            logger.warning("S2 DOI lookup failed: %s", e)

    if arxiv_id:
        try:
            resp = await client.get(
                f"{base_url}/graph/v1/paper/ARXIV:{arxiv_id}",
                params={"fields": fields},
                headers=headers,
                timeout=15.0,
            )
            if resp.status_code == 200:
                return _parse_s2_response(resp.json())
        except Exception as e:
            logger.warning("S2 arXiv lookup failed: %s", e)

    if title:
        try:
            resp = await client.get(
                f"{base_url}/graph/v1/paper/search/match",
                params={"query": title[:200], "fields": fields},
                headers=headers,
                timeout=15.0,
            )
            if resp.status_code == 200:
                matches = resp.json().get("data", [])
                if matches:
                    return _parse_s2_response(matches[0])
        except Exception as e:
            logger.warning("S2 title match failed: %s", e)

    return {}


async def enrich_metadata(state: MainGraphState) -> dict[str, Any]:
    """Extract DOI/arXiv from paper text, query Crossref → Semantic Scholar for venue,
    then publication_rank for SCI/CCF.

    Multi-source fallback chain:
      Level 1: DOI → Crossref
      Level 2: DOI/arXiv → Semantic Scholar
      Level 3: Title → Semantic Scholar /paper/search/match

    This node is fault-tolerant: any failure logs a warning but does not block the pipeline.
    """
    if state.get("error"):
        return {}

    paper_id = state["paper_id"]
    t0 = time.perf_counter()

    try:
        # 1. Check if paper already has full rank data (venue + at least one rank)
        existing = await db.fetch_one(
            "SELECT doi, venue, year, sci_rank, ccf_rank FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        if existing and existing.get("venue") and (existing.get("sci_rank") or existing.get("ccf_rank")):
            pub_rank = {
                "venue": existing["venue"],
                "year": existing.get("year", 0) or 0,
                "sci": existing.get("sci_rank", ""),
                "ccf": existing.get("ccf_rank", ""),
            }
            logger.info("[%s] enrich_metadata: CACHED from DB (venue=%s sci=%s ccf=%s) in %.2fs",
                         paper_id, existing["venue"], existing.get("sci_rank", "-"), existing.get("ccf_rank", "-"),
                         time.perf_counter() - t0)
            return {
                "pub_rank_json": json.dumps(pub_rank),
                "progress": state.get("progress", []) + [{"step": "enrich_metadata", "status": "done", "cached": True}],
            }

        # 2. Extract DOI + arXiv ID from paper text (or reuse DOI from DB)
        doi = ""
        arxiv_id = ""
        if existing and existing.get("doi"):
            doi = existing["doi"]
        if not doi and state.get("paper_ir_json"):
            doi = await _extract_doi_from_ir(state)
        if state.get("paper_ir_json"):
            arxiv_id = await _extract_arxiv_id_from_ir(state)
        logger.info("[%s] enrich_metadata: DOI=%s arXiv=%s", paper_id, doi or "-", arxiv_id or "-")

        # 3. Multi-source venue + year lookup
        venue = ""
        year = 0

        # Reuse venue from DB if already stored (skip external queries for venue)
        if existing and existing.get("venue"):
            venue = existing["venue"]
            year = existing.get("year", 0) or 0
            logger.info("[%s] enrich_metadata: venue=%s (cached from DB)", paper_id, venue)
        else:
            # Level 1: Crossref (by DOI) — most authoritative for journals
            if doi:
                crossref = await _crossref_lookup(doi)
                venue = crossref.get("venue", "")
                year = crossref.get("year", 0)
                if venue:
                    logger.info("[%s] enrich_metadata: Crossref -> venue=%s year=%d", paper_id, venue, year)

            # Level 2+3: Semantic Scholar (by DOI/arXiv/title) — stronger for conferences
            if not venue:
                title = ""
                if state.get("paper_ir_json"):
                    title = get_cached_paper_ir(state).title
                s2 = await _s2_lookup(doi=doi, arxiv_id=arxiv_id, title=title)
                if s2.get("venue"):
                    venue = s2["venue"]
                    year = s2.get("year", 0) or year
                    logger.info("[%s] enrich_metadata: S2 -> venue=%s year=%d", paper_id, venue, year)
                elif s2.get("year"):
                    year = s2["year"] or year

            if not venue:
                logger.warning("[%s] enrich_metadata: No venue found from any source", paper_id)

        # 4. Query publication_rank for SCI/CCF
        sci_rank = ""
        ccf_rank = ""
        if venue:
            try:
                logger.info("[%s] enrich_metadata: Querying publication_rank for '%s'...", paper_id, venue)
                from app.services.publication_rank import UnifiedRankClient
                async with UnifiedRankClient() as rank_client:
                    result = await rank_client.query(venue)
                    logger.info("[%s] enrich_metadata: publication_rank result: success=%s sci=%s ccf=%s error=%s",
                                 paper_id, result.success, result.sci, result.ccf, result.error)
                    if result.success:
                        sci_rank = result.sci or ""
                        ccf_rank = result.ccf or ""
                    else:
                        logger.warning("[%s] enrich_metadata: publication_rank query failed for '%s': %s", paper_id, venue, result.error)
            except Exception as e:
                logger.warning("[%s] enrich_metadata: publication_rank import/call error: %s", paper_id, e, exc_info=True)
        else:
            logger.info("[%s] enrich_metadata: No venue found, skipping publication_rank query", paper_id)

        # 5. Persist to DB
        if doi or venue or arxiv_id:
            await db.execute(
                "UPDATE papers SET doi = ?, venue = ?, year = ?, sci_rank = ?, ccf_rank = ? WHERE paper_id = ?",
                (doi, venue, year, sci_rank, ccf_rank, paper_id),
            )

        pub_rank = {"venue": venue, "year": year, "sci": sci_rank, "ccf": ccf_rank}
        elapsed = time.perf_counter() - t0
        logger.info("[%s] enrich_metadata: DONE in %.1fs — venue=%s year=%d sci=%s ccf=%s",
                     paper_id, elapsed, venue or "(none)", year, sci_rank or "-", ccf_rank or "-")
        return {
            "pub_rank_json": json.dumps(pub_rank),
            "progress": state.get("progress", []) + [{"step": "enrich_metadata", "status": "done"}],
        }

    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.warning("[%s] enrich_metadata: FAILED in %.1fs — %s (non-blocking)", paper_id, elapsed, e)
        return {
            "pub_rank_json": json.dumps({}),
            "progress": state.get("progress", []) + [{"step": "enrich_metadata", "status": "skipped", "error": str(e)}],
        }


def route_by_mode(state: MainGraphState) -> str:
    """Route to appropriate subgraph based on mode.

    Reads the (possibly classifier-mutated) `mode`. Valid values at this point
    are snap | lens | sphere | qa. If we still see `auto` (classifier no-op),
    fall back to snap so the run produces something useful.
    """
    if state.get("error"):
        return "persist_output"

    mode = state.get("mode", "snap")
    logger.info(f"[{state['paper_id']}] route_by_mode: -> {mode}")
    if mode == "lens":
        return "run_lens"
    if mode == "sphere":
        return "run_sphere"
    if mode == "qa":
        return "run_qa"
    return "run_snap"


async def run_snap(state: MainGraphState) -> dict[str, Any]:
    """Run Insight Snap analysis."""
    t0 = time.perf_counter()
    logger.info(f"[{state['paper_id']}] run_snap: Starting Insight Snap...")
    from app.workflows.snap_subgraph import run_insight_snap
    result = await run_insight_snap(state)
    elapsed = time.perf_counter() - t0
    md_len = len(result.get("final_markdown", ""))
    logger.info(f"[{state['paper_id']}] run_snap: DONE in {elapsed:.1f}s — markdown={md_len} chars")
    return result


async def run_lens(state: MainGraphState) -> dict[str, Any]:
    """Run Logic Lens analysis."""
    t0 = time.perf_counter()
    logger.info(f"[{state['paper_id']}] run_lens: Starting Logic Lens...")
    from app.workflows.lens_subgraph import run_logic_lens
    result = await run_logic_lens(state)
    elapsed = time.perf_counter() - t0
    md_len = len(result.get("final_markdown", ""))
    logger.info(f"[{state['paper_id']}] run_lens: DONE in {elapsed:.1f}s — markdown={md_len} chars")
    return result


async def run_sphere(state: MainGraphState) -> dict[str, Any]:
    """Run Research Sphere analysis."""
    t0 = time.perf_counter()
    logger.info(f"[{state['paper_id']}] run_sphere: Starting Research Sphere...")
    from app.workflows.sphere_subgraph import run_research_sphere
    result = await run_research_sphere(state)
    elapsed = time.perf_counter() - t0
    md_len = len(result.get("final_markdown", ""))
    logger.info(f"[{state['paper_id']}] run_sphere: DONE in {elapsed:.1f}s — markdown={md_len} chars")
    return result


async def run_qa(state: MainGraphState) -> dict[str, Any]:
    """Run direct Q&A subgraph (reached only via classify_intent)."""
    t0 = time.perf_counter()
    logger.info(f"[{state['paper_id']}] run_qa: Starting Direct Q&A...")
    from app.workflows.qa_subgraph import run_qa as _run_qa
    result = await _run_qa(state)
    elapsed = time.perf_counter() - t0
    md_len = len(result.get("final_markdown", ""))
    logger.info(f"[{state['paper_id']}] run_qa: DONE in {elapsed:.1f}s — markdown={md_len} chars")
    return result


async def classify_intent_node(state: MainGraphState) -> dict[str, Any]:
    """Classify user question into snap|lens|sphere|qa when mode == 'auto'."""
    from app.workflows.intent_classifier import classify_intent
    return await classify_intent(state)


async def persist_output(state: MainGraphState) -> dict[str, Any]:
    """Save results to DB."""
    t0 = time.perf_counter()
    run_id = state["run_id"]
    paper_id = state["paper_id"]

    detected_intent = state.get("detected_intent", "")
    final_mode = state.get("mode", "")
    run_row = await db.fetch_one("SELECT status FROM runs WHERE run_id = ?", (run_id,))
    run_status = str((run_row or {}).get("status") or "")
    if run_status not in ("pending", "running"):
        logger.info(
            "[%s] persist_output: skipped run_id=%s because status is %s",
            paper_id,
            run_id,
            run_status or "missing",
        )
        return {
            "persist_skipped": True,
            "progress": state.get("progress", []) + [{"step": "persist_output", "status": "skipped"}],
        }

    if state.get("error"):
        await db.execute(
            "UPDATE runs SET status = 'failed', error_msg = ?, mode = ?, detected_intent = ?, finished_at = datetime('now') "
            "WHERE run_id = ? AND status IN ('pending', 'running')",
            (state["error"], final_mode, detected_intent, run_id),
        )
        logger.info(f"[{paper_id}] persist_output: Saved FAILED status in {time.perf_counter()-t0:.2f}s")
        return {"progress": state.get("progress", []) + [{"step": "persist_output", "status": "failed"}]}

    markdown = state.get("final_markdown", "")
    json_data = state.get("final_json", "{}")
    if state.get("document_partitions_json") or state.get("supplementary_index_json"):
        try:
            payload = json.loads(json_data) if json_data else {}
            if state.get("document_partitions_json"):
                payload.setdefault("document_partitions", json.loads(state["document_partitions_json"]))
            if state.get("supplementary_index_json"):
                payload.setdefault("supplementary_index", json.loads(state["supplementary_index_json"]))
            json_data = json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            logger.warning("[%s] persist_output: failed to merge partition metadata — %s", paper_id, e)
    language = state.get("language", "en")

    await db.execute(
        "INSERT OR REPLACE INTO run_outputs (run_id, markdown, json_data) VALUES (?, ?, ?)",
        (run_id, markdown, json_data),
    )

    analysis_sync = None
    if markdown.strip():
        try:
            paper = await db.fetch_one("SELECT title FROM papers WHERE paper_id = ?", (paper_id,))
            analysis_sync = await sync_analysis_to_dify(
                run_id=run_id,
                paper_id=paper_id,
                markdown=markdown,
                mode=final_mode,
                language=language,
                title=str((paper or {}).get("title") or ""),
                dataset_id=await analysis_dataset_for_run(run_id, paper_id),
            )
        except Exception as e:
            logger.warning("[%s] persist_output: analysis Dify sync failed run=%s — %s", paper_id, run_id, e)

    await db.execute(
        "UPDATE runs SET status = 'done', mode = ?, detected_intent = ?, finished_at = datetime('now') "
        "WHERE run_id = ? AND status IN ('pending', 'running')",
        (final_mode, detected_intent, run_id),
    )
    try:
        paper_ir_json = state.get("paper_ir_json") or ""
        if paper_ir_json:
            await refresh_paper_display_cache(paper_id, get_cached_paper_ir(state))
    except Exception as e:
        logger.warning("[%s] persist_output: display cache refresh failed — %s", paper_id, e)

    logger.info(
        f"[{paper_id}] persist_output: Saved run_id={run_id} mode={final_mode} "
        f"intent={detected_intent or '-'} markdown={len(markdown)} chars "
        f"analysis_dify={(analysis_sync.status if analysis_sync else '-')} "
        f"in {time.perf_counter()-t0:.2f}s"
    )
    progress = state.get("progress", [])
    if analysis_sync:
        progress = progress + [
            {
                "step": "analysis_dify_sync",
                "status": analysis_sync.status,
                "document_id": analysis_sync.document_id,
                "message": analysis_sync.message,
            }
        ]
    clear_cached_paper_ir(run_id)
    return {"progress": progress + [{"step": "persist_output", "status": "done"}]}


async def generate_knowledge_cards(state: MainGraphState) -> dict[str, Any]:
    """Best-effort automatic AI draft card generation after run output is saved."""
    if state.get("error"):
        return {}
    if state.get("persist_skipped"):
        return {
            "progress": state.get("progress", []) + [
                {"step": "generate_knowledge_cards", "status": "skipped"}
            ]
        }
    t0 = time.perf_counter()
    paper_id = state["paper_id"]
    try:
        from app.services.knowledge_card_generator import generate_cards_from_state

        result = await generate_cards_from_state(state)
        status = str(result.get("status") or "skipped")
        logger.info(
            "[%s] generate_knowledge_cards: %s created=%s skipped=%s in %.2fs",
            paper_id,
            status,
            result.get("cards_created", 0),
            result.get("cards_skipped", 0),
            time.perf_counter() - t0,
        )
        return {
            "auto_knowledge_cards_json": json.dumps(result, ensure_ascii=False),
            "progress": state.get("progress", []) + [
                {
                    "step": "generate_knowledge_cards",
                    "status": status,
                    "cards_created": result.get("cards_created", 0),
                    "cards_skipped": result.get("cards_skipped", 0),
                    "message": result.get("error_msg", ""),
                }
            ],
        }
    except Exception as e:
        logger.warning("[%s] generate_knowledge_cards: failed in %.2fs — %s", paper_id, time.perf_counter() - t0, e)
        return {
            "auto_knowledge_cards_json": json.dumps({"status": "failed", "error_msg": str(e)}, ensure_ascii=False),
            "progress": state.get("progress", []) + [
                {"step": "generate_knowledge_cards", "status": "failed", "error": str(e)}
            ],
        }


def build_main_graph() -> StateGraph:
    """Build the main LangGraph workflow."""
    graph = StateGraph(MainGraphState)

    graph.add_node("ingest_pdf", ingest_pdf)
    graph.add_node("mineru_parse", mineru_parse)
    graph.add_node("build_paper_ir", build_paper_ir)
    graph.add_node("detect_document_parts", detect_document_parts)
    graph.add_node("sync_dify_library", sync_dify_library)
    graph.add_node("enrich_metadata", enrich_metadata)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("run_snap", run_snap)
    graph.add_node("run_lens", run_lens)
    graph.add_node("run_sphere", run_sphere)
    graph.add_node("run_qa", run_qa)
    graph.add_node("translate_output", translate_output)
    graph.add_node("persist_output", persist_output)
    graph.add_node("generate_knowledge_cards", generate_knowledge_cards)

    graph.set_entry_point("ingest_pdf")
    graph.add_edge("ingest_pdf", "mineru_parse")
    graph.add_edge("mineru_parse", "build_paper_ir")
    graph.add_edge("build_paper_ir", "detect_document_parts")
    graph.add_edge("detect_document_parts", "sync_dify_library")
    graph.add_edge("sync_dify_library", "enrich_metadata")
    graph.add_edge("enrich_metadata", "classify_intent")
    graph.add_conditional_edges("classify_intent", route_by_mode, {
        "run_snap": "run_snap",
        "run_lens": "run_lens",
        "run_sphere": "run_sphere",
        "run_qa": "run_qa",
        "persist_output": "persist_output",
    })
    graph.add_edge("run_snap", "translate_output")
    graph.add_edge("run_lens", "translate_output")
    graph.add_edge("run_sphere", "translate_output")
    graph.add_edge("run_qa", "translate_output")
    graph.add_edge("translate_output", "persist_output")
    graph.add_edge("persist_output", "generate_knowledge_cards")
    graph.add_edge("generate_knowledge_cards", END)

    return graph
