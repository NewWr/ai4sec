from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.db import database as db
from app.models.paper_ir import Block, PaperIR
from app.services import dify_client
from app.services.knowledge_spaces import DIFY_SYNC_SKIP_DATASET_ID

logger = logging.getLogger("scholar.dify.sync")

SKIP_TYPES = {"header", "footer", "page_number", "aside_text"}


@dataclass(frozen=True)
class DifySyncResult:
    paper_id: str
    status: str
    message: str = ""
    document_id: str = ""
    run_id: str = ""


def paper_ir_to_markdown(paper_ir: PaperIR, max_chars: int = 0) -> str:
    parts: list[str] = []
    title = _clean_text(paper_ir.title)
    if title:
        parts.append(f"# {title}")

    last_section = ""
    blocks = sorted(paper_ir.blocks, key=lambda block: block.order_idx)
    for block in blocks:
        block_type = str(block.type or "").strip()
        if block_type in SKIP_TYPES:
            continue

        text = _clean_text(block.text)
        if not text:
            continue
        if block_type == "title" and parts and parts[-1].strip("# ") == text:
            last_section = _clean_text(block.section_path) or last_section
            continue

        section = _clean_text(block.section_path)
        if section and section != last_section and block_type != "title":
            heading = section.split("/")[-1].strip()
            if heading and (not parts or parts[-1].strip("# ") != heading):
                parts.append(f"## {heading}")
            last_section = section

        parts.append(_block_to_markdown(block, text, has_previous=bool(parts)))
        if block_type == "title":
            last_section = section or last_section

    text = "\n\n".join(part for part in parts if part.strip()).strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


async def sync_paper_ir_to_dify(
    paper_id: str,
    paper_ir: PaperIR,
    *,
    dataset_id: str | None = None,
    max_chars: int = 0,
    force: bool = False,
) -> DifySyncResult:
    settings = get_settings()
    if not settings.dify_enabled:
        return DifySyncResult(paper_id, "skipped", "DIFY_API_BASE is empty")

    if dataset_id == DIFY_SYNC_SKIP_DATASET_ID:
        return DifySyncResult(paper_id, "skipped", "knowledge space has no Dify dataset")

    effective_dataset = (dataset_id or settings.dify_default_dataset_id or "").strip()
    text = paper_ir_to_markdown(paper_ir, max_chars=max_chars)
    source_hash = _source_hash(text)
    name = _document_name(paper_id, paper_ir.title)
    if not text:
        await _mark_failed(paper_id, effective_dataset, source_hash, "empty document text")
        return DifySyncResult(paper_id, "failed", "empty document text")

    existing = await db.fetch_one(
        "SELECT status, source_hash, dify_document_id FROM dify_syncs WHERE paper_id = ? AND dataset_id = ?",
        (paper_id, effective_dataset),
    )
    if (
        existing
        and existing.get("status") == "synced"
        and existing.get("source_hash") == source_hash
        and not force
    ):
        doc_id = str(existing.get("dify_document_id") or "")
        return DifySyncResult(paper_id, "skipped", "source unchanged", doc_id)

    await _mark_running(paper_id, effective_dataset, source_hash)
    try:
        data = await dify_client.create_document_by_text(name, text, dataset_id=effective_dataset or None)
        doc_id = dify_client.extract_document_id(data)
        if not doc_id:
            raise dify_client.DifyError(f"Dify response did not include document id: {data}")
    except Exception as exc:
        await _mark_failed(paper_id, effective_dataset, source_hash, str(exc))
        logger.warning("[%s] dify_sync: failed: %s", paper_id, exc)
        return DifySyncResult(paper_id, "failed", str(exc))

    await _mark_synced(paper_id, effective_dataset, source_hash, doc_id)
    logger.info("[%s] dify_sync: synced document_id=%s text=%d chars", paper_id, doc_id, len(text))
    return DifySyncResult(paper_id, "synced", name, doc_id)


async def sync_analysis_to_dify(
    *,
    run_id: str,
    paper_id: str,
    markdown: str,
    mode: str,
    language: str,
    title: str = "",
    dataset_id: str | None = None,
    max_chars: int = 0,
) -> DifySyncResult:
    settings = get_settings()
    if dataset_id == DIFY_SYNC_SKIP_DATASET_ID:
        return DifySyncResult(paper_id, "skipped", "knowledge space has no Dify dataset", run_id=run_id)
    effective_dataset = (dataset_id or settings.dify_analysis_dataset_id or "").strip()
    if not settings.dify_enabled:
        return DifySyncResult(paper_id, "skipped", "DIFY_API_BASE is empty", run_id=run_id)
    if not effective_dataset:
        return DifySyncResult(paper_id, "skipped", "DIFY_ANALYSIS_DATASET_ID is empty", run_id=run_id)

    text = analysis_to_markdown(
        markdown=markdown,
        run_id=run_id,
        paper_id=paper_id,
        mode=mode,
        language=language,
        title=title,
        max_chars=max_chars,
    )
    source_hash = _source_hash(text)
    name = _analysis_document_name(paper_id=paper_id, title=title, mode=mode, run_id=run_id)
    if not text:
        await _mark_analysis_failed(run_id, paper_id, effective_dataset, source_hash, "empty analysis text")
        return DifySyncResult(paper_id, "failed", "empty analysis text", run_id=run_id)

    existing = await db.fetch_one(
        "SELECT status, source_hash, dify_document_id FROM analysis_dify_syncs WHERE run_id = ? AND dataset_id = ?",
        (run_id, effective_dataset),
    )
    if existing and existing.get("status") == "synced" and existing.get("source_hash") == source_hash:
        doc_id = str(existing.get("dify_document_id") or "")
        return DifySyncResult(paper_id, "skipped", "source unchanged", doc_id, run_id=run_id)

    await _mark_analysis_running(run_id, paper_id, effective_dataset, source_hash)
    try:
        data = await dify_client.create_document_by_text(name, text, dataset_id=effective_dataset)
        doc_id = dify_client.extract_document_id(data)
        if not doc_id:
            raise dify_client.DifyError(f"Dify response did not include document id: {data}")
    except Exception as exc:
        await _mark_analysis_failed(run_id, paper_id, effective_dataset, source_hash, str(exc))
        logger.warning("[%s] analysis_dify_sync: failed run=%s: %s", paper_id, run_id, exc)
        return DifySyncResult(paper_id, "failed", str(exc), run_id=run_id)

    await _mark_analysis_synced(run_id, paper_id, effective_dataset, source_hash, doc_id)
    logger.info(
        "[%s] analysis_dify_sync: synced run=%s document_id=%s text=%d chars",
        paper_id,
        run_id,
        doc_id,
        len(text),
    )
    return DifySyncResult(paper_id, "synced", name, doc_id, run_id=run_id)


def analysis_to_markdown(
    *,
    markdown: str,
    run_id: str,
    paper_id: str,
    mode: str,
    language: str,
    title: str = "",
    max_chars: int = 0,
) -> str:
    body = markdown.strip()
    if max_chars > 0 and len(body) > max_chars:
        body = body[:max_chars].rstrip()
    if not body:
        return ""

    title_line = _clean_text(title) or paper_id
    header = "\n".join(
        [
            f"# {title_line} [{mode or 'analysis'}]",
            "",
            "source_type: analysis",
            f"paper_id: {paper_id}",
            f"run_id: {run_id}",
            f"mode: {mode or 'analysis'}",
            f"language: {language or 'en'}",
        ]
    )
    return f"{header}\n\n{body}".strip()


def _block_to_markdown(block: Block, text: str, *, has_previous: bool) -> str:
    page_ref = f"[p.{block.page_idx + 1}]"
    if block.type == "title":
        level = 2 if has_previous else 1
        return f"{'#' * level} {text} {page_ref}"
    if block.type == "table":
        return f"[Table {page_ref}]\n{text}"
    if block.type == "image":
        return f"[Figure {page_ref}]\n{text}"
    if block.type == "equation":
        return f"{page_ref}\n$$\n{text}\n$$"
    return f"{page_ref} {text}"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value if str(item).strip())
    text = str(value).replace("\x00", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _source_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _document_name(paper_id: str, title: str) -> str:
    clean_title = " ".join(title.split()).strip()
    return clean_title or paper_id


def _analysis_document_name(*, paper_id: str, title: str, mode: str, run_id: str) -> str:
    clean_title = " ".join(title.split()).strip() or paper_id
    clean_mode = (mode or "analysis").strip() or "analysis"
    return f"{clean_title} [{clean_mode}] {run_id}"


async def _mark_running(paper_id: str, dataset_id: str, source_hash: str) -> None:
    await db.execute(
        """
        INSERT INTO dify_syncs
          (paper_id, dataset_id, source_hash, status, attempts, error_msg, updated_at)
        VALUES (?, ?, ?, 'running', 1, '', datetime('now'))
        ON CONFLICT(paper_id, dataset_id) DO UPDATE SET
          source_hash = excluded.source_hash,
          status = 'running',
          attempts = dify_syncs.attempts + 1,
          error_msg = '',
          updated_at = datetime('now')
        """,
        (paper_id, dataset_id, source_hash),
    )


async def _mark_synced(paper_id: str, dataset_id: str, source_hash: str, document_id: str) -> None:
    await db.execute(
        """
        INSERT INTO dify_syncs
          (paper_id, dataset_id, dify_document_id, source_hash, status, error_msg, updated_at)
        VALUES (?, ?, ?, ?, 'synced', '', datetime('now'))
        ON CONFLICT(paper_id, dataset_id) DO UPDATE SET
          dify_document_id = excluded.dify_document_id,
          source_hash = excluded.source_hash,
          status = 'synced',
          error_msg = '',
          updated_at = datetime('now')
        """,
        (paper_id, dataset_id, document_id, source_hash),
    )


async def _mark_failed(paper_id: str, dataset_id: str, source_hash: str, error_msg: str) -> None:
    existing = await db.fetch_one(
        "SELECT attempts, source_hash FROM dify_syncs WHERE paper_id = ? AND dataset_id = ?",
        (paper_id, dataset_id),
    )
    attempts = 1
    if existing:
        attempts = int(existing.get("attempts") or 0) + 1
        if existing.get("source_hash") != source_hash:
            attempts = 1
    await db.execute(
        """
        INSERT INTO dify_syncs
          (paper_id, dataset_id, source_hash, status, attempts, error_msg, updated_at)
        VALUES (?, ?, ?, 'failed', ?, ?, datetime('now'))
        ON CONFLICT(paper_id, dataset_id) DO UPDATE SET
          source_hash = excluded.source_hash,
          status = 'failed',
          attempts = excluded.attempts,
          error_msg = excluded.error_msg,
          updated_at = datetime('now')
        """,
        (paper_id, dataset_id, source_hash, attempts, error_msg[:1000]),
    )


async def _mark_analysis_running(run_id: str, paper_id: str, dataset_id: str, source_hash: str) -> None:
    await db.execute(
        """
        INSERT INTO analysis_dify_syncs
          (run_id, paper_id, dataset_id, source_hash, status, attempts, error_msg, updated_at)
        VALUES (?, ?, ?, ?, 'running', 1, '', datetime('now'))
        ON CONFLICT(run_id, dataset_id) DO UPDATE SET
          paper_id = excluded.paper_id,
          source_hash = excluded.source_hash,
          status = 'running',
          attempts = analysis_dify_syncs.attempts + 1,
          error_msg = '',
          updated_at = datetime('now')
        """,
        (run_id, paper_id, dataset_id, source_hash),
    )


async def _mark_analysis_synced(
    run_id: str,
    paper_id: str,
    dataset_id: str,
    source_hash: str,
    document_id: str,
) -> None:
    await db.execute(
        """
        INSERT INTO analysis_dify_syncs
          (run_id, paper_id, dataset_id, dify_document_id, source_hash, status, error_msg, updated_at)
        VALUES (?, ?, ?, ?, ?, 'synced', '', datetime('now'))
        ON CONFLICT(run_id, dataset_id) DO UPDATE SET
          paper_id = excluded.paper_id,
          dify_document_id = excluded.dify_document_id,
          source_hash = excluded.source_hash,
          status = 'synced',
          error_msg = '',
          updated_at = datetime('now')
        """,
        (run_id, paper_id, dataset_id, document_id, source_hash),
    )


async def _mark_analysis_failed(
    run_id: str,
    paper_id: str,
    dataset_id: str,
    source_hash: str,
    error_msg: str,
) -> None:
    existing = await db.fetch_one(
        "SELECT attempts, source_hash FROM analysis_dify_syncs WHERE run_id = ? AND dataset_id = ?",
        (run_id, dataset_id),
    )
    attempts = 1
    if existing:
        attempts = int(existing.get("attempts") or 0) + 1
        if existing.get("source_hash") != source_hash:
            attempts = 1
    await db.execute(
        """
        INSERT INTO analysis_dify_syncs
          (run_id, paper_id, dataset_id, source_hash, status, attempts, error_msg, updated_at)
        VALUES (?, ?, ?, ?, 'failed', ?, ?, datetime('now'))
        ON CONFLICT(run_id, dataset_id) DO UPDATE SET
          paper_id = excluded.paper_id,
          source_hash = excluded.source_hash,
          status = 'failed',
          attempts = excluded.attempts,
          error_msg = excluded.error_msg,
          updated_at = datetime('now')
        """,
        (run_id, paper_id, dataset_id, source_hash, attempts, error_msg[:1000]),
    )
