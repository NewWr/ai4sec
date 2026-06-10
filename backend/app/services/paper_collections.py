from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from app.db import database as db
from app.models.paper_ir import Block, PaperIR, Section
from app.services import mineru_adapter
from app.services.llm_service import get_llm_service
from app.services.llm_runtime_config import get_llm_runtime_config
from app.services.paper_ir import build_and_store_paper_ir
from app.services.translation_cache import text_hash, translate_text

logger = logging.getLogger("scholar.collections")

DEFAULT_COLLECTION_ID = "unclassified"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _truncate(text: str, max_len: int) -> str:
    text = _normalize(text)
    return text[: max_len - 1] + "..." if len(text) > max_len else text


def _collection_id() -> str:
    return uuid.uuid4().hex[:12]


async def ensure_default_collection() -> None:
    row = await db.fetch_one("SELECT collection_id FROM paper_collections WHERE collection_id = ?", (DEFAULT_COLLECTION_ID,))
    if row:
        return
    await db.execute(
        """
        INSERT OR IGNORE INTO paper_collections (
            collection_id, parent_id, name, name_zh, description, description_zh, sort_order
        ) VALUES (?, '', ?, ?, ?, ?, 9999)
        """,
        (
            DEFAULT_COLLECTION_ID,
            "Unclassified",
            "未归类",
            "Papers that have not been assigned to a research structure.",
            "尚未确认研究结构归属的论文。",
        ),
    )


async def list_collection_rows() -> list[dict[str, Any]]:
    await ensure_default_collection()
    return await db.fetch_all(
        """
        SELECT
            c.*,
            COUNT(i.paper_id) AS paper_count
          FROM paper_collections c
          LEFT JOIN paper_collection_items i ON i.collection_id = c.collection_id
         GROUP BY c.collection_id
         ORDER BY c.sort_order ASC, c.name ASC
        """
    )


async def list_collection_items() -> list[dict[str, Any]]:
    return await db.fetch_all(
        """
        SELECT
            i.collection_id,
            i.paper_id,
            i.is_primary,
            i.note,
            i.note_zh,
            i.sort_order,
            i.updated_at
          FROM paper_collection_items i
         ORDER BY i.sort_order ASC, i.updated_at DESC
        """
    )


async def ensure_paper_parsed(paper_id: str) -> PaperIR:
    existing_blocks = await db.fetch_all(
        "SELECT * FROM blocks WHERE paper_id = ? ORDER BY order_idx ASC LIMIT 5000",
        (paper_id,),
    )
    if existing_blocks:
        return await load_paper_ir_from_blocks(paper_id)

    parse = await db.fetch_one(
        """
        SELECT parse_id, output_dir
          FROM mineru_parses
         WHERE paper_id = ? AND status = 'done'
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (paper_id,),
    )
    if parse and parse.get("output_dir") and Path(str(parse["output_dir"])).exists():
        return await build_and_store_paper_ir(Path(str(parse["output_dir"])), paper_id)

    parse_id = uuid.uuid4().hex[:16]
    await db.execute(
        "INSERT INTO mineru_parses (parse_id, paper_id, status) VALUES (?, ?, 'pending')",
        (parse_id, paper_id),
    )
    output_dir = await mineru_adapter.parse_pdf(paper_id, parse_id)
    return await build_and_store_paper_ir(output_dir, paper_id)


async def load_paper_ir_from_blocks(paper_id: str) -> PaperIR:
    rows = await db.fetch_all(
        "SELECT * FROM blocks WHERE paper_id = ? ORDER BY order_idx ASC",
        (paper_id,),
    )
    blocks = [
        Block(
            type=str(row.get("type") or ""),
            sub_type=str(row.get("sub_type") or ""),
            page_idx=int(row.get("page_idx") or 0),
            bbox=json.loads(str(row.get("bbox_json") or "[]")),
            text=str(row.get("text") or ""),
            section_path=str(row.get("section_path") or ""),
            order_idx=int(row.get("order_idx") or 0),
        )
        for row in rows
    ]
    paper = await db.fetch_one("SELECT title FROM papers WHERE paper_id = ?", (paper_id,))
    title = str((paper or {}).get("title") or "")
    if not title:
        title = next((block.text for block in blocks if block.type == "title" and block.text.strip()), "")

    by_path: dict[str, list[Block]] = {}
    for block in blocks:
        by_path.setdefault(block.section_path or "", []).append(block)
    sections = [
        Section(path=path, title=path.split("/")[-1] if path else "", blocks=section_blocks)
        for path, section_blocks in by_path.items()
    ]
    return PaperIR(paper_id=paper_id, title=title, sections=sections, blocks=blocks)


def build_summary_source(paper_ir: PaperIR) -> str:
    abstract_parts: list[str] = []
    intro_parts: list[str] = []
    fallback_parts: list[str] = []
    for block in paper_ir.blocks:
        if block.type not in {"text", "title"} or not block.text.strip():
            continue
        section = (block.section_path or "").lower()
        text = _normalize(block.text)
        if not text or len(text) < 40:
            continue
        if "abstract" in section:
            abstract_parts.append(text)
        elif "introduction" in section or "intro" in section:
            intro_parts.append(text)
        elif len(fallback_parts) < 4:
            fallback_parts.append(text)
    source = " ".join(abstract_parts) or " ".join(intro_parts[:3]) or " ".join(fallback_parts[:3])
    return _truncate(source, 900)


async def refresh_paper_display_cache(paper_id: str, paper_ir: PaperIR | None = None) -> dict[str, Any]:
    if paper_ir is None:
        paper_ir = await load_paper_ir_from_blocks(paper_id)
    paper = await db.fetch_one("SELECT title FROM papers WHERE paper_id = ?", (paper_id,))
    title = str((paper or {}).get("title") or paper_ir.title or paper_id)
    source = build_summary_source(paper_ir)
    digest = text_hash(f"{title}\n{source}")

    cached = await db.fetch_one(
        "SELECT * FROM paper_display_cache WHERE paper_id = ? AND source_hash = ?",
        (paper_id, digest),
    )
    if cached:
        return cached

    title_zh = (await translate_text(title)).translated_text if title else ""
    summary_result = await translate_text(source) if source else None
    summary_zh = summary_result.translated_text if summary_result else ""
    status = summary_result.status if summary_result else "skipped"
    await db.execute(
        """
        INSERT INTO paper_display_cache (
            paper_id, title_zh, summary_source, summary_en, summary_zh,
            source_hash, translation_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(paper_id) DO UPDATE SET
            title_zh = excluded.title_zh,
            summary_source = excluded.summary_source,
            summary_en = excluded.summary_en,
            summary_zh = excluded.summary_zh,
            source_hash = excluded.source_hash,
            translation_status = excluded.translation_status,
            updated_at = datetime('now')
        """,
        (paper_id, title_zh, source, source, summary_zh, digest, status),
    )
    return await db.fetch_one("SELECT * FROM paper_display_cache WHERE paper_id = ?", (paper_id,)) or {}


def _collection_prompt(collections: list[dict[str, Any]], paper_ir: PaperIR, summary: str) -> str:
    collection_lines = []
    for row in collections:
        if str(row.get("collection_id") or "") == DEFAULT_COLLECTION_ID:
            continue
        collection_lines.append(
            json.dumps(
                {
                    "collection_id": row.get("collection_id"),
                    "name": row.get("name"),
                    "name_zh": row.get("name_zh"),
                    "description": row.get("description"),
                    "parent_id": row.get("parent_id"),
                },
                ensure_ascii=False,
            )
        )
    context_blocks = []
    for block in paper_ir.blocks[:80]:
        if block.type in {"text", "title"} and block.text.strip():
            context_blocks.append(f"[{block.section_path or block.type}] {_truncate(block.text, 260)}")
        if len("\n".join(context_blocks)) > 4500:
            break
    return f"""Classify this academic paper into an existing collection or propose one new collection.

Existing collections, one JSON object per line:
{chr(10).join(collection_lines) or "(none)"}

Paper title:
{paper_ir.title}

Paper short summary:
{summary}

Paper text evidence:
{chr(10).join(context_blocks)}

Return strict JSON only:
{{
  "mode": "existing" | "new",
  "collection_id": "existing collection id or empty",
  "new_name": "short English collection name if mode is new",
  "new_name_zh": "short Simplified Chinese collection name if mode is new",
  "new_description": "one sentence",
  "new_description_zh": "one Chinese sentence",
  "confidence": 0.0,
  "reason": "brief reason in Chinese"
}}"""


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _fallback_suggestion(collections: list[dict[str, Any]], paper_ir: PaperIR, summary: str) -> dict[str, Any]:
    text = f"{paper_ir.title} {summary}".lower()
    best: tuple[int, dict[str, Any] | None] = (0, None)
    for row in collections:
        if str(row.get("collection_id") or "") == DEFAULT_COLLECTION_ID:
            continue
        keywords = _normalize(f"{row.get('name') or ''} {row.get('name_zh') or ''} {row.get('description') or ''}").lower().split()
        score = sum(1 for word in keywords if len(word) >= 4 and word in text)
        if score > best[0]:
            best = (score, row)
    if best[1] is not None and best[0] > 0:
        return {
            "mode": "existing",
            "collection_id": best[1]["collection_id"],
            "new_name": "",
            "new_name_zh": "",
            "new_description": "",
            "new_description_zh": "",
            "confidence": min(0.72, 0.38 + best[0] * 0.08),
            "reason": "根据标题和简介中的关键词匹配到现有结构。",
        }
    title_tokens = [token for token in re.findall(r"[A-Za-z][A-Za-z0-9+-]{2,}", paper_ir.title)[:4]]
    name = " ".join(title_tokens) or "New Research Topic"
    return {
        "mode": "new",
        "collection_id": "",
        "new_name": name,
        "new_name_zh": name,
        "new_description": "Automatically proposed from the uploaded paper.",
        "new_description_zh": "根据当前上传论文自动建议的新研究结构。",
        "confidence": 0.35,
        "reason": "没有足够证据匹配现有结构，建议先建立新结构并由用户确认。",
    }


async def suggest_collection_for_paper(paper_id: str, llm_model: str = "") -> dict[str, Any]:
    t0 = time.perf_counter()
    paper = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (paper_id,))
    if not paper:
        raise ValueError("Paper not found")
    await ensure_default_collection()
    paper_ir = await ensure_paper_parsed(paper_id)
    display = await refresh_paper_display_cache(paper_id, paper_ir)
    summary = str(display.get("summary_en") or build_summary_source(paper_ir))
    collections = await list_collection_rows()

    suggestion = _fallback_suggestion(collections, paper_ir, summary)
    try:
        runtime_config = get_llm_runtime_config()
        if runtime_config.default_thinking_model or llm_model:
            raw = await get_llm_service().chat(
                [{"role": "user", "content": _collection_prompt(collections, paper_ir, summary)}],
                model=llm_model,
                temperature=0.1,
            )
            parsed = _parse_json_object(raw)
            if parsed:
                known_ids = {str(row.get("collection_id") or "") for row in collections}
                mode = str(parsed.get("mode") or "existing").lower()
                collection_id = str(parsed.get("collection_id") or "")
                if mode == "existing" and collection_id not in known_ids:
                    mode = "new"
                    collection_id = ""
                suggestion = {
                    "mode": mode if mode in {"existing", "new"} else "new",
                    "collection_id": collection_id,
                    "new_name": str(parsed.get("new_name") or ""),
                    "new_name_zh": str(parsed.get("new_name_zh") or parsed.get("new_name") or ""),
                    "new_description": str(parsed.get("new_description") or ""),
                    "new_description_zh": str(parsed.get("new_description_zh") or parsed.get("new_description") or ""),
                    "confidence": float(parsed.get("confidence") or 0.0),
                    "reason": str(parsed.get("reason") or ""),
                }
    except Exception as exc:
        logger.warning("Collection LLM suggestion failed paper=%s: %s", paper_id, exc)

    if suggestion["mode"] == "new" and not suggestion["new_name_zh"]:
        suggestion["new_name_zh"] = (await translate_text(suggestion["new_name"])).translated_text
    if suggestion["mode"] == "new" and suggestion["new_description"] and not suggestion["new_description_zh"]:
        suggestion["new_description_zh"] = (await translate_text(suggestion["new_description"])).translated_text

    logger.info("Collection suggestion paper=%s mode=%s in %.1fs", paper_id, suggestion["mode"], time.perf_counter() - t0)
    return {
        "paper_id": paper_id,
        "paper_title": paper_ir.title or paper_id,
        "paper_title_zh": str(display.get("title_zh") or paper_ir.title or paper_id),
        "summary_zh": str(display.get("summary_zh") or display.get("summary_en") or ""),
        "summary_en": str(display.get("summary_en") or ""),
        "suggestion": suggestion,
        "collections": collections,
    }


async def create_collection(
    *,
    name: str,
    name_zh: str = "",
    description: str = "",
    description_zh: str = "",
    parent_id: str = "",
) -> dict[str, Any]:
    await ensure_default_collection()
    name = _normalize(name)
    if not name:
        raise ValueError("Collection name is required")
    if parent_id:
        parent = await db.fetch_one("SELECT collection_id FROM paper_collections WHERE collection_id = ?", (parent_id,))
        if not parent:
            raise ValueError("Parent collection not found")
    if not name_zh:
        name_zh = (await translate_text(name)).translated_text
    if description and not description_zh:
        description_zh = (await translate_text(description)).translated_text
    row = await db.fetch_one("SELECT COALESCE(MAX(sort_order), 0) AS max_sort FROM paper_collections")
    sort_order = int((row or {}).get("max_sort") or 0) + 10
    collection_id = _collection_id()
    await db.execute(
        """
        INSERT INTO paper_collections (
            collection_id, parent_id, name, name_zh, description, description_zh, sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (collection_id, parent_id, name, name_zh, description, description_zh, sort_order),
    )
    return await db.fetch_one("SELECT *, 0 AS paper_count FROM paper_collections WHERE collection_id = ?", (collection_id,)) or {}


async def _collection_exists(collection_id: str) -> bool:
    row = await db.fetch_one(
        "SELECT collection_id FROM paper_collections WHERE collection_id = ?",
        (collection_id,),
    )
    return bool(row)


async def _is_descendant(collection_id: str, candidate_parent_id: str) -> bool:
    current = candidate_parent_id
    seen: set[str] = set()
    while current:
        if current == collection_id:
            return True
        if current in seen:
            return True
        seen.add(current)
        row = await db.fetch_one(
            "SELECT parent_id FROM paper_collections WHERE collection_id = ?",
            (current,),
        )
        current = str((row or {}).get("parent_id") or "")
    return False


async def update_collection(
    *,
    collection_id: str,
    name: str | None = None,
    name_zh: str | None = None,
    description: str | None = None,
    description_zh: str | None = None,
    parent_id: str | None = None,
) -> dict[str, Any]:
    await ensure_default_collection()
    current = await db.fetch_one(
        "SELECT * FROM paper_collections WHERE collection_id = ?",
        (collection_id,),
    )
    if not current:
        raise ValueError("Collection not found")

    next_parent_id = str(current.get("parent_id") or "")
    if parent_id is not None:
        next_parent_id = _normalize(parent_id)
        if collection_id == DEFAULT_COLLECTION_ID and next_parent_id:
            raise ValueError("Default collection cannot be moved")
        if next_parent_id:
            if not await _collection_exists(next_parent_id):
                raise ValueError("Parent collection not found")
            if next_parent_id == collection_id or await _is_descendant(collection_id, next_parent_id):
                raise ValueError("Collection cannot be moved into itself or its child")

    next_name = _normalize(str(current.get("name") or ""))
    if name is not None:
        next_name = _normalize(name)
    if not next_name:
        raise ValueError("Collection name is required")

    next_name_zh = str(current.get("name_zh") or "")
    if name_zh is not None:
        next_name_zh = _normalize(name_zh)
    elif name is not None and not next_name_zh:
        next_name_zh = (await translate_text(next_name)).translated_text

    next_description = str(current.get("description") or "")
    if description is not None:
        next_description = _normalize(description)

    next_description_zh = str(current.get("description_zh") or "")
    if description_zh is not None:
        next_description_zh = _normalize(description_zh)
    elif description is not None and next_description and not next_description_zh:
        next_description_zh = (await translate_text(next_description)).translated_text

    await db.execute(
        """
        UPDATE paper_collections
           SET parent_id = ?,
               name = ?,
               name_zh = ?,
               description = ?,
               description_zh = ?,
               updated_at = datetime('now')
         WHERE collection_id = ?
        """,
        (
            next_parent_id,
            next_name,
            next_name_zh,
            next_description,
            next_description_zh,
            collection_id,
        ),
    )
    return await db.fetch_one(
        "SELECT *, 0 AS paper_count FROM paper_collections WHERE collection_id = ?",
        (collection_id,),
    ) or {}


async def delete_collection(collection_id: str) -> None:
    await ensure_default_collection()
    if collection_id == DEFAULT_COLLECTION_ID:
        raise ValueError("Default collection cannot be deleted")
    row = await db.fetch_one(
        "SELECT collection_id FROM paper_collections WHERE collection_id = ?",
        (collection_id,),
    )
    if not row:
        raise ValueError("Collection not found")
    child = await db.fetch_one(
        "SELECT collection_id FROM paper_collections WHERE parent_id = ? LIMIT 1",
        (collection_id,),
    )
    if child:
        raise ValueError("Only empty leaf collections can be deleted")
    item = await db.fetch_one(
        "SELECT paper_id FROM paper_collection_items WHERE collection_id = ? LIMIT 1",
        (collection_id,),
    )
    if item:
        raise ValueError("Only empty collections can be deleted")
    await db.execute("DELETE FROM paper_collections WHERE collection_id = ?", (collection_id,))


async def assign_paper_to_collection(
    *,
    paper_id: str,
    collection_id: str,
    is_primary: bool = True,
    note: str = "",
    note_zh: str = "",
) -> dict[str, Any]:
    paper = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (paper_id,))
    if not paper:
        raise ValueError("Paper not found")
    collection = await db.fetch_one("SELECT collection_id FROM paper_collections WHERE collection_id = ?", (collection_id,))
    if not collection:
        raise ValueError("Collection not found")
    if is_primary:
        await db.execute(
            "UPDATE paper_collection_items SET is_primary = 0 WHERE paper_id = ? AND is_primary = 1",
            (paper_id,),
        )
        if collection_id != DEFAULT_COLLECTION_ID:
            await db.execute(
                "DELETE FROM paper_collection_items WHERE paper_id = ? AND collection_id = ?",
                (paper_id, DEFAULT_COLLECTION_ID),
            )
    if note and not note_zh:
        note_zh = (await translate_text(note)).translated_text
    await db.execute(
        """
        INSERT INTO paper_collection_items (
            collection_id, paper_id, is_primary, note, note_zh, updated_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(collection_id, paper_id) DO UPDATE SET
            is_primary = excluded.is_primary,
            note = excluded.note,
            note_zh = excluded.note_zh,
            updated_at = datetime('now')
        """,
        (collection_id, paper_id, 1 if is_primary else 0, note, note_zh),
    )
    return await db.fetch_one(
        "SELECT * FROM paper_collection_items WHERE paper_id = ? AND collection_id = ?",
        (paper_id, collection_id),
    ) or {}


async def move_paper_to_collection(
    *,
    paper_id: str,
    collection_id: str,
    note: str = "",
) -> dict[str, Any]:
    return await assign_paper_to_collection(
        paper_id=paper_id,
        collection_id=collection_id,
        is_primary=True,
        note=note,
    )


async def confirm_collection_choice(
    *,
    paper_id: str,
    collection_id: str = "",
    new_name: str = "",
    new_name_zh: str = "",
    new_description: str = "",
    new_description_zh: str = "",
    parent_id: str = "",
    note: str = "",
) -> dict[str, Any]:
    if not collection_id:
        collection = await create_collection(
            name=new_name,
            name_zh=new_name_zh,
            description=new_description,
            description_zh=new_description_zh,
            parent_id=parent_id,
        )
        collection_id = str(collection["collection_id"])
    item = await assign_paper_to_collection(
        paper_id=paper_id,
        collection_id=collection_id,
        is_primary=True,
        note=note,
    )
    collection = await db.fetch_one("SELECT *, 0 AS paper_count FROM paper_collections WHERE collection_id = ?", (collection_id,))
    return {"collection": collection, "item": item}


async def ensure_unassigned_papers_default() -> None:
    await ensure_default_collection()
    rows = await db.fetch_all(
        """
        SELECT p.paper_id
          FROM papers p
          LEFT JOIN paper_collection_items i ON i.paper_id = p.paper_id
         WHERE i.paper_id IS NULL
        """
    )
    for row in rows:
        await assign_paper_to_collection(
            paper_id=str(row["paper_id"]),
            collection_id=DEFAULT_COLLECTION_ID,
            is_primary=True,
        )
