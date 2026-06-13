from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from app.db import database as db
from app.services import evidence_store

logger = logging.getLogger("scholar.knowledge_assets")

_LIKE_ESCAPE_RE = re.compile(r"([%_\\])")
_CITE_KEY_RE = re.compile(r"[^A-Za-z0-9]+")
_ARXIV_RE = re.compile(r"(?:arxiv[:/ ]*)?(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_BIB_ENTRY_START_RE = re.compile(r"@(?P<type>\w+)\s*\{", re.IGNORECASE)

READING_STATUSES = {"unread", "skimmed", "reading", "read", "archived"}
PAPER_PRIORITIES = {"high", "medium", "low"}
READING_DECISIONS = {"", "must_read", "useful", "background", "discard"}
ANNOTATION_TYPES = {"highlight", "note", "question", "correction"}
CARD_TYPES = {"claim", "method", "dataset", "metric", "result", "limitation", "question", "idea"}
FACT_CARD_TYPES = {"claim", "method", "dataset", "metric", "result", "limitation"}
CARD_STATUSES = {"draft", "verified", "rejected", "merged"}
CREATED_BY = {"user", "ai"}
ASSET_LEVELS = {"evidence", "synthesis", "action"}
PRIORITIES = {"high", "medium", "low"}
AI_REVIEW_STATUSES = {"trusted", "pending", "error", "valuable"}
SECTION_HINTS = {"related_work", "method", "experiment", "limitation"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _like(query: str) -> str:
    escaped = _LIKE_ESCAPE_RE.sub(r"\\\1", query.strip())
    return f"%{escaped}%"


def _citation_key(row: dict[str, Any]) -> str:
    existing = str(row.get("citation_key") or "").strip()
    if existing:
        return existing
    title = str(row.get("title") or "paper")
    first = _CITE_KEY_RE.sub("", title.split()[0] if title.split() else "paper")[:24] or "paper"
    year = int(row.get("year") or 0)
    suffix = str(row.get("paper_id") or "")[:6]
    return f"{first}{year or ''}{suffix}"


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()


def _title_similarity(left: str, right: str) -> float:
    left_norm = _normalize_title(left)
    right_norm = _normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _extract_arxiv(*values: str) -> str:
    for value in values:
        match = _ARXIV_RE.search(value or "")
        if match:
            return match.group(1)
    return ""


def _clean_ref_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\n", " ")).strip().strip("{}")


def _paper_id_from_reference(ref: dict[str, Any]) -> str:
    seed = "|".join(
        str(ref.get(key) or "").strip().lower()
        for key in ("doi", "arxiv_id", "title", "year")
    )
    return "ref_" + uuid.uuid5(uuid.NAMESPACE_URL, seed or uuid.uuid4().hex).hex


def _require_choice(name: str, value: str, choices: set[str]) -> str:
    value = str(value or "").strip()
    if value not in choices:
        allowed = ", ".join(sorted(item or "<empty>" for item in choices))
        raise ValueError(f"Invalid {name}: {value or '<empty>'}. Allowed values: {allowed}")
    return value


def _short_quote(value: str, limit: int = 300) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value if len(value) <= limit else f"{value[:limit - 3]}..."


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            return [item.strip() for item in text.split(",") if item.strip()]
    return []


def _json_list_text(value: Any) -> str:
    return json.dumps(_json_list(value), ensure_ascii=False)


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_dict_text(value: Any) -> str:
    return json.dumps(_json_dict(value), ensure_ascii=False)


def _append_revision(raw: Any, entry: dict[str, Any], *, limit: int = 50) -> str:
    try:
        history = json.loads(raw) if isinstance(raw, str) else (raw or [])
        if not isinstance(history, list):
            history = []
    except Exception:
        history = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    history.append({"at": stamp, **entry})
    return json.dumps(history[-limit:], ensure_ascii=False)


async def record_asset_event(
    event_type: str,
    asset_type: str,
    asset_id: str,
    *,
    paper_id: str = "",
    source: str = "",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_id = _new_id("evt")
    await db.execute(
        """
        INSERT INTO research_asset_events (
            event_id, event_type, asset_type, asset_id, paper_id, source, detail_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            str(event_type or "").strip(),
            str(asset_type or "").strip(),
            str(asset_id or "").strip(),
            str(paper_id or "").strip(),
            str(source or "").strip(),
            json.dumps(detail or {}, ensure_ascii=False),
        ),
    )
    return {
        "event_id": event_id,
        "event_type": event_type,
        "asset_type": asset_type,
        "asset_id": asset_id,
        "paper_id": paper_id,
        "source": source,
        "detail": detail or {},
    }


def normalize_card_key(card_type: str, paper_id: str, title: str = "", content: str = "", source_quote: str = "") -> str:
    seed = source_quote or content or title
    norm = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", seed.lower())).strip()
    return f"{card_type}:{paper_id}:{norm[:180]}"


def _has_traceable_source(card: dict[str, Any]) -> bool:
    # Fact-style Claim cards must trace to source text regardless of asset_level
    # (ADR-2): require paper_id plus a bound evidence row. A raw source_quote is
    # only acceptable after it has been anchored into research_evidence_items and
    # linked through research_evidence_cards.
    card_type = str(card.get("card_type") or "")
    if card_type not in FACT_CARD_TYPES:
        return True
    return bool(str(card.get("paper_id") or "").strip() and _json_list(card.get("evidence_ids")))


def _validate_card_status(card: dict[str, Any], *, allow_untraceable: bool = False) -> None:
    if str(card.get("status") or "") != "verified":
        return
    if str(card.get("title") or "").strip() == "":
        raise ValueError("Verified knowledge cards require a title")
    if str(card.get("content") or "").strip() == "":
        raise ValueError("Verified knowledge cards require content")
    if not allow_untraceable and not _has_traceable_source(card):
        raise ValueError("Verified factual knowledge cards require paper_id plus source_quote or evidence_ids")


async def ensure_paper(paper_id: str) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM papers WHERE paper_id = ?", (paper_id,))
    if not row:
        raise ValueError("Paper not found")
    return row


async def _validate_evidence_ids(evidence_ids: list[str], paper_id: str) -> None:
    for evidence_id in evidence_ids:
        row = await db.fetch_one(
            "SELECT evidence_id, paper_id FROM research_evidence_items WHERE evidence_id = ?",
            (evidence_id,),
        )
        if not row:
            raise ValueError(f"Evidence not found: {evidence_id}")
        if paper_id and str(row.get("paper_id") or "") != paper_id:
            raise ValueError("Card evidence must belong to the same paper")


async def _prepare_card_evidence(
    card: dict[str, Any],
    *,
    force_reanchor: bool = False,
) -> tuple[list[str], int]:
    """Resolve a fact card's source quote into evidence ids before validation.

    This keeps the Evidence -> Claim invariant in the service layer, so manual
    cards and AI cards use the same bridge-writing path.
    """
    source_page = max(0, int(card.get("source_page") or 0))
    paper_id = str(card.get("paper_id") or "").strip()
    card_type = str(card.get("card_type") or "").strip()
    explicit_ids = [] if force_reanchor else _json_list(card.get("evidence_ids"))
    if explicit_ids:
        if str(card.get("asset_level") or "") == "synthesis":
            for evidence_id in explicit_ids:
                if not await db.fetch_one("SELECT evidence_id FROM research_evidence_items WHERE evidence_id = ?", (evidence_id,)):
                    raise ValueError(f"Evidence not found: {evidence_id}")
        else:
            await _validate_evidence_ids(explicit_ids, paper_id)
        return explicit_ids, source_page
    if card_type not in FACT_CARD_TYPES:
        return _json_list(card.get("evidence_ids")), source_page
    quote = str(card.get("source_quote") or "").strip()
    if not paper_id or not quote:
        return [], source_page
    anchored = await evidence_store.anchor_quote(paper_id, quote)
    if not anchored.ok:
        return [], source_page
    source_page = anchored.page or source_page
    evidence_id = await evidence_store.upsert_evidence(
        paper_id,
        quote,
        evidence_type=card_type,
        page=source_page,
        block_id=anchored.block_id,
        source_run_id=str(card.get("run_id") or ""),
        confidence=max(0.0, min(1.0, float(card.get("confidence") or 0.0))),
        extractor=str(card.get("extractor_version") or "manual_card_v1"),
        prompt_version=str(card.get("prompt_version") or ""),
        anchor=False,
    )
    return [evidence_id], source_page


async def update_paper_lifecycle(paper_id: str, values: dict[str, Any]) -> dict[str, Any]:
    await ensure_paper(paper_id)
    allowed = {
        "reading_status",
        "priority",
        "decision",
        "personal_rating",
        "read_progress",
        "last_read_at",
    }
    fields: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key not in values or values[key] is None:
            continue
        value = values[key]
        if key == "reading_status":
            value = _require_choice(key, value, READING_STATUSES)
        if key == "priority":
            value = _require_choice(key, value, PAPER_PRIORITIES)
        if key == "decision":
            value = _require_choice(key, value, READING_DECISIONS)
        if key == "personal_rating":
            value = max(0, min(5, int(value)))
        if key == "read_progress":
            value = max(0.0, min(100.0, float(value)))
        fields.append(f"{key} = ?")
        params.append(value)
    if fields:
        await db.execute(f"UPDATE papers SET {', '.join(fields)} WHERE paper_id = ?", tuple(params + [paper_id]))
    return await ensure_paper(paper_id)


async def bulk_update_paper_lifecycle(paper_ids: list[str], values: dict[str, Any]) -> int:
    paper_ids = [paper_id for paper_id in dict.fromkeys(paper_ids) if paper_id]
    if not paper_ids:
        return 0
    allowed = {"reading_status", "priority", "decision"}
    fields: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key in values and values[key] is not None:
            value = values[key]
            if key == "reading_status":
                value = _require_choice(key, value, READING_STATUSES)
            if key == "priority":
                value = _require_choice(key, value, PAPER_PRIORITIES)
            if key == "decision":
                value = _require_choice(key, value, READING_DECISIONS)
            fields.append(f"{key} = ?")
            params.append(value)
    if not fields:
        return 0
    placeholders = ",".join("?" for _ in paper_ids)
    await db.execute(
        f"UPDATE papers SET {', '.join(fields)} WHERE paper_id IN ({placeholders})",
        tuple(params + paper_ids),
    )
    return len(paper_ids)


async def list_annotations(paper_id: str) -> list[dict[str, Any]]:
    await ensure_paper(paper_id)
    return await db.fetch_all(
        """
        SELECT * FROM paper_annotations
         WHERE paper_id = ?
         ORDER BY page ASC, updated_at DESC
        """,
        (paper_id,),
    )


async def create_annotation(data: dict[str, Any]) -> dict[str, Any]:
    await ensure_paper(str(data.get("paper_id") or ""))
    annotation_id = _new_id("ann")
    annotation_type = _require_choice("annotation_type", str(data.get("annotation_type") or "highlight"), ANNOTATION_TYPES)
    await db.execute(
        """
        INSERT INTO paper_annotations (
            annotation_id, paper_id, page, quote, note, annotation_type, color, bbox_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            annotation_id,
            str(data.get("paper_id") or ""),
            max(1, int(data.get("page") or 1)),
            str(data.get("quote") or "").strip(),
            str(data.get("note") or "").strip(),
            annotation_type,
            str(data.get("color") or "yellow").strip()[:32] or "yellow",
            str(data.get("bbox_json") or "[]"),
        ),
    )
    row = await db.fetch_one("SELECT * FROM paper_annotations WHERE annotation_id = ?", (annotation_id,))
    if not row:
        raise RuntimeError("Annotation creation failed")
    return row


async def update_annotation(annotation_id: str, data: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM paper_annotations WHERE annotation_id = ?", (annotation_id,))
    if not row:
        raise ValueError("Annotation not found")
    allowed = {"page", "quote", "note", "annotation_type", "color", "bbox_json"}
    fields: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key in data and data[key] is not None:
            value = data[key]
            if key == "page":
                value = max(1, int(value))
            if key == "annotation_type":
                value = _require_choice(key, value, ANNOTATION_TYPES)
            if key == "color":
                value = str(value).strip()[:32] or "yellow"
            fields.append(f"{key} = ?")
            params.append(value)
    if fields:
        fields.append("updated_at = datetime('now')")
        await db.execute(
            f"UPDATE paper_annotations SET {', '.join(fields)} WHERE annotation_id = ?",
            tuple(params + [annotation_id]),
        )
    updated = await db.fetch_one("SELECT * FROM paper_annotations WHERE annotation_id = ?", (annotation_id,))
    if not updated:
        raise ValueError("Annotation not found")
    return updated


async def delete_annotation(annotation_id: str) -> None:
    await db.execute("DELETE FROM paper_annotations WHERE annotation_id = ?", (annotation_id,))


async def get_note(paper_id: str) -> dict[str, Any]:
    await ensure_paper(paper_id)
    row = await db.fetch_one("SELECT * FROM paper_notes WHERE paper_id = ?", (paper_id,))
    if row:
        return row
    return {
        "paper_id": paper_id,
        "summary_user": "",
        "key_takeaways": "",
        "open_questions": "",
        "reading_decision": "",
        "created_at": "",
        "updated_at": "",
    }


async def update_note(paper_id: str, data: dict[str, Any]) -> dict[str, Any]:
    await ensure_paper(paper_id)
    await db.execute(
        """
        INSERT INTO paper_notes (
            paper_id, summary_user, key_takeaways, open_questions, reading_decision, updated_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(paper_id) DO UPDATE SET
            summary_user = excluded.summary_user,
            key_takeaways = excluded.key_takeaways,
            open_questions = excluded.open_questions,
            reading_decision = excluded.reading_decision,
            updated_at = datetime('now')
        """,
        (
            paper_id,
            str(data.get("summary_user") or "").strip(),
            str(data.get("key_takeaways") or "").strip(),
            str(data.get("open_questions") or "").strip(),
            str(data.get("reading_decision") or "").strip(),
        ),
    )
    return await get_note(paper_id)


async def list_review_marks(paper_id: str, run_id: str = "") -> list[dict[str, Any]]:
    await ensure_paper(paper_id)
    if run_id:
        return await db.fetch_all(
            """
            SELECT * FROM ai_review_marks
             WHERE paper_id = ? AND run_id = ?
             ORDER BY updated_at DESC
            """,
            (paper_id, run_id),
        )
    return await db.fetch_all(
        "SELECT * FROM ai_review_marks WHERE paper_id = ? ORDER BY updated_at DESC",
        (paper_id,),
    )


async def create_review_mark(data: dict[str, Any]) -> dict[str, Any]:
    await ensure_paper(str(data.get("paper_id") or ""))
    mark_id = _new_id("mark")
    status = _require_choice("status", str(data.get("status") or "pending"), AI_REVIEW_STATUSES)
    await db.execute(
        """
        INSERT INTO ai_review_marks (mark_id, paper_id, run_id, source_ref, quote, status, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mark_id,
            str(data.get("paper_id") or ""),
            str(data.get("run_id") or ""),
            str(data.get("source_ref") or ""),
            str(data.get("quote") or ""),
            status,
            str(data.get("note") or ""),
        ),
    )
    row = await db.fetch_one("SELECT * FROM ai_review_marks WHERE mark_id = ?", (mark_id,))
    if not row:
        raise RuntimeError("Review mark creation failed")
    return row


async def update_review_mark(mark_id: str, data: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM ai_review_marks WHERE mark_id = ?", (mark_id,))
    if not row:
        raise ValueError("Review mark not found")
    fields: list[str] = []
    params: list[Any] = []
    for key in ("status", "note"):
        if key in data and data[key] is not None:
            value = str(data[key])
            if key == "status":
                value = _require_choice(key, value, AI_REVIEW_STATUSES)
            fields.append(f"{key} = ?")
            params.append(value)
    if fields:
        fields.append("updated_at = datetime('now')")
        await db.execute(
            f"UPDATE ai_review_marks SET {', '.join(fields)} WHERE mark_id = ?",
            tuple(params + [mark_id]),
        )
    updated = await db.fetch_one("SELECT * FROM ai_review_marks WHERE mark_id = ?", (mark_id,))
    if not updated:
        raise ValueError("Review mark not found")
    return updated


async def list_cards(
    *,
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
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if query.strip():
        clauses.append(
            "(kc.title LIKE ? ESCAPE '\\' OR kc.content LIKE ? ESCAPE '\\' "
            "OR kc.source_quote LIKE ? ESCAPE '\\' OR kc.tags LIKE ? ESCAPE '\\')"
        )
        term = _like(query)
        params.extend([term, term, term, term])
    if card_type:
        clauses.append("kc.card_type = ?")
        params.append(card_type)
    if status:
        clauses.append("kc.status = ?")
        params.append(status)
    if paper_id:
        clauses.append("kc.paper_id = ?")
        params.append(paper_id)
    if created_by:
        clauses.append("kc.created_by = ?")
        params.append(_require_choice("created_by", created_by, CREATED_BY))
    if run_id:
        clauses.append("kc.run_id = ?")
        params.append(run_id)
    if asset_level:
        clauses.append("kc.asset_level = ?")
        params.append(_require_choice("asset_level", asset_level, ASSET_LEVELS))
    if action_type:
        clauses.append("kc.action_type = ?")
        params.append(action_type)
    if priority:
        clauses.append("kc.priority = ?")
        params.append(_require_choice("priority", priority, PRIORITIES))
    if has_source in {"true", "false"}:
        if has_source == "true":
            clauses.append("(kc.asset_level != 'evidence' OR kc.card_type NOT IN ('claim', 'method', 'dataset', 'metric', 'result', 'limitation') OR (kc.paper_id != '' AND kc.source_quote != ''))")
        else:
            clauses.append("(kc.asset_level = 'evidence' AND kc.card_type IN ('claim', 'method', 'dataset', 'metric', 'result', 'limitation') AND (kc.paper_id = '' OR kc.source_quote = ''))")
    if quality_flag:
        clauses.append("kc.quality_flags LIKE ? ESCAPE '\\'")
        params.append(_like(quality_flag))
    if min_confidence is not None:
        clauses.append("kc.confidence >= ?")
        params.append(float(min_confidence))
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.fetch_all(
        f"""
        SELECT kc.*, COALESCE(p.title, '') AS paper_title, COALESCE(p.citation_key, '') AS citation_key,
               COALESCE(evt.event_count, 0) AS event_count
          FROM knowledge_cards kc
          LEFT JOIN papers p ON p.paper_id = kc.paper_id
          LEFT JOIN (
              SELECT asset_id, COUNT(*) AS event_count
                FROM research_asset_events
               WHERE asset_type = 'card'
               GROUP BY asset_id
          ) evt ON evt.asset_id = kc.card_id
          {where_sql}
         ORDER BY
            CASE kc.status
                WHEN 'verified' THEN 0
                WHEN 'draft' THEN 1
                WHEN 'merged' THEN 2
                WHEN 'rejected' THEN 3
                ELSE 4
            END,
            CASE kc.asset_level
                WHEN 'action' THEN 0
                WHEN 'synthesis' THEN 1
                WHEN 'evidence' THEN 2
                ELSE 3
            END,
            CASE kc.priority
                WHEN 'high' THEN 0
                WHEN 'medium' THEN 1
                WHEN 'low' THEN 2
                ELSE 3
            END,
            COALESCE(evt.event_count, 0) DESC,
            kc.updated_at DESC
         LIMIT ? OFFSET ?
        """,
        tuple(params + [max(1, min(limit, 500)), max(0, offset)]),
    )
    return [await _card_with_evidence(row) for row in rows]


async def _card_with_evidence(row: dict[str, Any]) -> dict[str, Any]:
    evidence_rows = await db.fetch_all(
        "SELECT evidence_id FROM research_evidence_cards WHERE card_id = ? ORDER BY created_at ASC",
        (str(row.get("card_id") or ""),),
    )
    row["evidence_ids"] = [str(item.get("evidence_id") or "") for item in evidence_rows]
    row["citation_key"] = _citation_key(row)
    row["quality_flags"] = _json_list(row.get("quality_flags"))
    row["supporting_card_ids"] = _json_list(row.get("supporting_card_ids"))
    row["supporting_paper_ids"] = _json_list(row.get("supporting_paper_ids"))
    return row


async def _after_action_card_verified(card_id: str) -> None:
    from app.services import knowledge_synthesis, research_discovery

    await knowledge_synthesis.rebuild_synthesis_cards(limit=500)
    try:
        await research_discovery.rebuild_discovery_for_card(card_id)
    except Exception as exc:
        logger.warning("Incremental research discovery failed for card=%s: %s", card_id, exc)


async def create_card(data: dict[str, Any]) -> dict[str, Any]:
    paper_id = str(data.get("paper_id") or "")
    if paper_id:
        await ensure_paper(paper_id)
    card_id = _new_id("card")
    card_type = _require_choice("card_type", str(data.get("card_type") or "claim"), CARD_TYPES)
    status = _require_choice("status", str(data.get("status") or "draft"), CARD_STATUSES)
    created_by = _require_choice("created_by", str(data.get("created_by") or "user"), CREATED_BY)
    asset_level = _require_choice("asset_level", str(data.get("asset_level") or "evidence"), ASSET_LEVELS)
    priority = _require_choice("priority", str(data.get("priority") or "medium"), PRIORITIES)
    title = str(data.get("title") or "").strip()
    content = str(data.get("content") or "").strip()
    source_quote = str(data.get("source_quote") or "").strip()
    confidence = max(0.0, min(1.0, float(data.get("confidence") or 0.0)))
    source_page = max(0, int(data.get("source_page") or 0))
    normalized_key = str(data.get("normalized_key") or "").strip() or normalize_card_key(card_type, paper_id, title, content, source_quote)
    preview = {
        "card_type": card_type,
        "title": title,
        "content": content,
        "paper_id": paper_id,
        "source_page": source_page,
        "source_quote": source_quote,
        "evidence_ids": data.get("evidence_ids") or [],
        "status": status,
        "asset_level": asset_level,
        "run_id": str(data.get("run_id") or "").strip(),
        "confidence": confidence,
        "extractor_version": str(data.get("extractor_version") or "").strip(),
        "prompt_version": str(data.get("prompt_version") or "").strip(),
    }
    evidence_ids, source_page = await _prepare_card_evidence(preview)
    preview["evidence_ids"] = evidence_ids
    preview["source_page"] = source_page
    _validate_card_status(preview, allow_untraceable=bool(data.get("allow_untraceable")))
    await db.execute(
        """
        INSERT INTO knowledge_cards (
            card_id, card_type, title, content, paper_id, source_page, source_quote,
            confidence, status, tags, created_by, run_id, source_kind, source_ref,
            normalized_key, quality_flags, prompt_version, extractor_version,
            asset_level, synthesis_type, action_type, why_useful, use_case,
            next_action, expected_output, risk_or_caveat, priority,
            supporting_card_ids, supporting_paper_ids, evidence_strength
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            card_id,
            card_type,
            title,
            content,
            paper_id,
            source_page,
            source_quote,
            confidence,
            status,
            str(data.get("tags") or "").strip(),
            created_by,
            str(data.get("run_id") or "").strip(),
            str(data.get("source_kind") or "").strip(),
            str(data.get("source_ref") or "").strip(),
            normalized_key,
            _json_list_text(data.get("quality_flags") or []),
            str(data.get("prompt_version") or "").strip(),
            str(data.get("extractor_version") or "").strip(),
            asset_level,
            str(data.get("synthesis_type") or "").strip(),
            str(data.get("action_type") or "").strip(),
            str(data.get("why_useful") or "").strip(),
            str(data.get("use_case") or "").strip(),
            str(data.get("next_action") or "").strip(),
            str(data.get("expected_output") or "").strip(),
            str(data.get("risk_or_caveat") or "").strip(),
            priority,
            _json_list_text(data.get("supporting_card_ids") or []),
            _json_list_text(data.get("supporting_paper_ids") or []),
            str(data.get("evidence_strength") or "").strip(),
        ),
    )
    await _replace_card_evidence(card_id, evidence_ids)
    await record_asset_event(
        "card_created",
        "card",
        card_id,
        paper_id=paper_id,
        source=str(data.get("created_by") or created_by),
        detail={"status": status, "asset_level": asset_level, "card_type": card_type},
    )
    if status == "verified" and asset_level == "action":
        await _after_action_card_verified(card_id)
    return await get_card(card_id)


async def get_card(card_id: str) -> dict[str, Any]:
    row = await db.fetch_one(
        """
        SELECT kc.*, COALESCE(p.title, '') AS paper_title, COALESCE(p.citation_key, '') AS citation_key
          FROM knowledge_cards kc
          LEFT JOIN papers p ON p.paper_id = kc.paper_id
         WHERE kc.card_id = ?
        """,
        (card_id,),
    )
    if not row:
        raise ValueError("Knowledge card not found")
    return await _card_with_evidence(row)


async def update_card(card_id: str, data: dict[str, Any]) -> dict[str, Any]:
    current = await get_card(card_id)
    allowed = {
        "card_type",
        "title",
        "content",
        "paper_id",
        "source_page",
        "source_quote",
        "confidence",
        "status",
        "tags",
        "merged_into_id",
        "run_id",
        "source_kind",
        "source_ref",
        "normalized_key",
        "quality_flags",
        "prompt_version",
        "extractor_version",
        "asset_level",
        "synthesis_type",
        "action_type",
        "why_useful",
        "use_case",
        "next_action",
        "expected_output",
        "risk_or_caveat",
        "priority",
        "supporting_card_ids",
        "supporting_paper_ids",
        "evidence_strength",
    }
    fields: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key not in data or data[key] is None:
            continue
        value = data[key]
        if key == "card_type":
            value = _require_choice(key, value, CARD_TYPES)
        if key == "paper_id" and value:
            await ensure_paper(str(value))
        if key == "source_page":
            value = max(0, int(value))
        if key == "confidence":
            value = max(0.0, min(1.0, float(value)))
        if key == "status":
            value = _require_choice(key, value, CARD_STATUSES)
        if key == "asset_level":
            value = _require_choice(key, value, ASSET_LEVELS)
        if key == "priority":
            value = _require_choice(key, value, PRIORITIES)
        if key == "quality_flags":
            value = _json_list_text(value)
        if key in {"supporting_card_ids", "supporting_paper_ids"}:
            value = _json_list_text(value)
        fields.append(f"{key} = ?")
        params.append(value)
    next_card = dict(current)
    for key in allowed:
        if key not in data or data[key] is None:
            continue
        next_card[key] = data[key]
    if "quality_flags" in next_card:
        next_card["quality_flags"] = _json_list(next_card.get("quality_flags"))
    if data.get("source_page") is not None:
        next_card["source_page"] = max(0, int(data.get("source_page") or 0))
    existing_evidence_ids = _json_list(current.get("evidence_ids"))
    next_card["evidence_ids"] = existing_evidence_ids
    should_reanchor = any(key in data for key in ("paper_id", "source_quote", "source_page", "card_type"))
    if should_reanchor:
        next_card["evidence_ids"] = []
    if "evidence_ids" in data and data["evidence_ids"] is not None:
        next_card["evidence_ids"] = _json_list(data.get("evidence_ids"))
        should_reanchor = False
    prepared_evidence_ids, prepared_source_page = await _prepare_card_evidence(
        next_card,
        force_reanchor=should_reanchor,
    )
    next_card["evidence_ids"] = prepared_evidence_ids
    evidence_changed = prepared_evidence_ids != existing_evidence_ids
    if prepared_source_page and prepared_source_page != int(next_card.get("source_page") or 0):
        next_card["source_page"] = prepared_source_page
        if "source_page" not in data:
            fields.append("source_page = ?")
            params.append(prepared_source_page)
    _validate_card_status(next_card, allow_untraceable=bool(data.get("allow_untraceable")))
    new_status = data.get("status")
    if new_status is not None and str(new_status) != str(current.get("status") or ""):
        fields.append("revision_history = ?")
        params.append(
            _append_revision(
                current.get("revision_history"),
                {
                    "action": "status_change",
                    "from": str(current.get("status") or ""),
                    "to": str(new_status),
                    "by": str(data.get("reviewed_by") or ""),
                },
            )
        )
        fields.append("card_version = card_version + 1")
    if data.get("status") == "verified":
        fields.append("reviewed_at = datetime('now')")
        fields.append("reviewed_by = ?")
        params.append(str(data.get("reviewed_by") or current.get("reviewed_by") or ""))
    if fields:
        fields.append("updated_at = datetime('now')")
        await db.execute(f"UPDATE knowledge_cards SET {', '.join(fields)} WHERE card_id = ?", tuple(params + [card_id]))
    if evidence_changed or should_reanchor or "evidence_ids" in data:
        await _replace_card_evidence(card_id, prepared_evidence_ids)
    if fields:
        await record_asset_event(
            "card_updated",
            "card",
            card_id,
            paper_id=str(next_card.get("paper_id") or current.get("paper_id") or ""),
            source="knowledge_assets",
            detail={
                "status": str(next_card.get("status") or ""),
                "changed_fields": sorted(key for key in data if key != "allow_untraceable"),
            },
        )
    if data.get("status") == "verified" and str(next_card.get("asset_level") or "") == "action":
        await _after_action_card_verified(card_id)
    return await get_card(card_id)


async def delete_card(card_id: str) -> None:
    await db.execute("DELETE FROM research_evidence_cards WHERE card_id = ?", (card_id,))
    await db.execute(
        "UPDATE writing_snippets SET source_card_id = '', updated_at = datetime('now') WHERE source_card_id = ?",
        (card_id,),
    )
    await db.execute("DELETE FROM knowledge_cards WHERE card_id = ?", (card_id,))


async def merge_card(card_id: str, target_card_id: str) -> dict[str, Any]:
    if card_id == target_card_id:
        raise ValueError("Cannot merge a card into itself")
    await get_card(target_card_id)
    await update_card(card_id, {"status": "merged", "merged_into_id": target_card_id})
    await db.execute(
        "UPDATE writing_snippets SET source_card_id = ?, updated_at = datetime('now') WHERE source_card_id = ?",
        (target_card_id, card_id),
    )
    evidence = await db.fetch_all("SELECT evidence_id FROM research_evidence_cards WHERE card_id = ?", (card_id,))
    for row in evidence:
        try:
            await db.execute(
                "INSERT OR IGNORE INTO research_evidence_cards (evidence_id, card_id) VALUES (?, ?)",
                (str(row.get("evidence_id") or ""), target_card_id),
            )
        except Exception:
            pass
    await record_asset_event(
        "card_merged",
        "card",
        card_id,
        paper_id=str((await get_card(target_card_id)).get("paper_id") or ""),
        source="knowledge_assets",
        detail={"target_card_id": target_card_id},
    )
    return await get_card(card_id)


async def batch_update_card_status(
    card_ids: list[str],
    status: str,
    *,
    allow_untraceable: bool = False,
    reviewed_by: str = "",
) -> list[dict[str, Any]]:
    status = _require_choice("status", status, CARD_STATUSES)
    updated: list[dict[str, Any]] = []
    for card_id in dict.fromkeys(card_ids):
        if not card_id:
            continue
        updated.append(
            await update_card(
                card_id,
                {
                    "status": status,
                    "allow_untraceable": allow_untraceable,
                    "reviewed_by": reviewed_by,
                },
            )
        )
    return updated


async def batch_merge_cards(source_card_ids: list[str], target_card_id: str) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for card_id in dict.fromkeys(source_card_ids):
        if not card_id or card_id == target_card_id:
            continue
        merged.append(await merge_card(card_id, target_card_id))
    return merged


async def list_card_generations(paper_id: str = "", run_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if paper_id:
        clauses.append("paper_id = ?")
        params.append(paper_id)
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.fetch_all(
        f"""
        SELECT *
          FROM knowledge_card_generations
          {where_sql}
         ORDER BY created_at DESC
         LIMIT ?
        """,
        tuple(params + [max(1, min(limit, 200))]),
    )
    for row in rows:
        card_rows = await db.fetch_all(
            "SELECT card_id FROM knowledge_cards WHERE run_id = ? AND prompt_version = ? ORDER BY created_at ASC",
            (str(row.get("run_id") or ""), str(row.get("prompt_version") or "")),
        )
        row["card_ids"] = [str(item.get("card_id") or "") for item in card_rows]
    return rows


async def _replace_card_evidence(card_id: str, evidence_ids: list[str]) -> None:
    await db.execute("DELETE FROM research_evidence_cards WHERE card_id = ?", (card_id,))
    for evidence_id in dict.fromkeys(str(item) for item in evidence_ids if item):
        await db.execute(
            "INSERT OR IGNORE INTO research_evidence_cards (evidence_id, card_id) VALUES (?, ?)",
            (evidence_id, card_id),
        )


async def list_snippets(section_hint: str = "", paper_id: str = "") -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if section_hint:
        _require_choice("section_hint", section_hint, SECTION_HINTS)
        clauses.append("ws.section_hint = ?")
        params.append(section_hint)
    if paper_id:
        clauses.append("ws.paper_id = ?")
        params.append(paper_id)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.fetch_all(
        f"""
        SELECT ws.*, COALESCE(kc.title, '') AS source_card_title, COALESCE(p.title, '') AS paper_title
          FROM writing_snippets ws
          LEFT JOIN knowledge_cards kc ON kc.card_id = ws.source_card_id
          LEFT JOIN papers p ON p.paper_id = ws.paper_id
          {where_sql}
         ORDER BY ws.updated_at DESC
        """,
        tuple(params),
    )
    for row in rows:
        if not str(row.get("citation_key") or "") and row.get("paper_id"):
            paper = await ensure_paper(str(row["paper_id"]))
            row["citation_key"] = _citation_key(paper)
        row["source_card_ids"] = _json_list(row.get("source_card_ids")) or _json_list(row.get("source_card_id"))
        row["evidence_ids"] = _json_list(row.get("evidence_ids"))
        row["paragraph_plan_json"] = _json_dict(row.get("paragraph_plan_json"))
        row["trace_mode"] = str(row.get("trace_mode") or "traceable")
        row["usage_count"] = int(row.get("usage_count") or 0)
    return rows


async def _snippet_trace_from_cards(source_card_ids: list[str], evidence_ids: list[str]) -> tuple[list[dict[str, Any]], list[str], str, int, str, str]:
    cards: list[dict[str, Any]] = []
    all_evidence_ids = list(evidence_ids)
    paper_id = ""
    source_page = 0
    source_quote = ""
    citation_key = ""
    for card_id in dict.fromkeys(source_card_ids):
        if not card_id:
            continue
        card = await get_card(card_id)
        cards.append(card)
        all_evidence_ids.extend(str(eid) for eid in card.get("evidence_ids", []) if eid)
        if not paper_id:
            paper_id = str(card.get("paper_id") or "")
        if not source_page:
            source_page = int(card.get("source_page") or 0)
        if not source_quote:
            source_quote = str(card.get("source_quote") or "")
        if not citation_key:
            citation_key = str(card.get("citation_key") or "")
    return cards, list(dict.fromkeys(all_evidence_ids)), paper_id, source_page, source_quote, citation_key


def _paragraph_plan_from_cards(cards: list[dict[str, Any]], section_hint: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, str]]] = {}
    for card in cards:
        key = str(card.get("card_type") or "claim")
        groups.setdefault(key, []).append(
            {
                "card_id": str(card.get("card_id") or ""),
                "title": str(card.get("title") or ""),
                "paper_id": str(card.get("paper_id") or ""),
                "citation_key": str(card.get("citation_key") or ""),
            }
        )
    ordered = [key for key in ("claim", "problem", "method", "dataset", "metric", "result", "limitation") if key in groups]
    ordered.extend(key for key in sorted(groups) if key not in ordered)
    return {
        "section_hint": section_hint,
        "topic": "Traceable related-work paragraph",
        "order": ordered,
        "groups": {key: groups[key] for key in ordered},
    }


async def create_snippet(data: dict[str, Any]) -> dict[str, Any]:
    paper_id = str(data.get("paper_id") or "")
    source_card_id = str(data.get("source_card_id") or "")
    source_card_ids = _json_list(data.get("source_card_ids") or [])
    if source_card_id and source_card_id not in source_card_ids:
        source_card_ids.insert(0, source_card_id)
    evidence_ids = _json_list(data.get("evidence_ids") or [])
    source_page = max(0, int(data.get("source_page") or 0))
    source_quote = str(data.get("source_quote") or "").strip()
    cards, evidence_ids, card_paper_id, card_page, card_quote, card_citation = await _snippet_trace_from_cards(source_card_ids, evidence_ids)
    if not source_card_id and source_card_ids:
        source_card_id = source_card_ids[0]
    if not paper_id:
        paper_id = card_paper_id
    if not source_page:
        source_page = card_page
    if not source_quote:
        source_quote = card_quote.strip()
    if paper_id:
        await ensure_paper(paper_id)
    snippet_id = _new_id("snip")
    citation_key = str(data.get("citation_key") or "")
    if not citation_key:
        citation_key = card_citation
    if not citation_key and paper_id:
        citation_key = _citation_key(await ensure_paper(paper_id))
    section_hint = _require_choice("section_hint", str(data.get("section_hint") or "related_work"), SECTION_HINTS)
    paragraph_plan = _json_dict(data.get("paragraph_plan_json")) or _paragraph_plan_from_cards(cards, section_hint)
    trace_mode = str(data.get("trace_mode") or "traceable").strip() or "traceable"
    await db.execute(
        """
        INSERT INTO writing_snippets (
            snippet_id, content, source_card_id, paper_id, citation_key,
            source_page, source_quote, section_hint, source_card_ids,
            evidence_ids, paragraph_plan_json, trace_mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snippet_id,
            str(data.get("content") or "").strip(),
            source_card_id,
            paper_id,
            citation_key,
            source_page,
            source_quote,
            section_hint,
            _json_list_text(source_card_ids),
            _json_list_text(evidence_ids),
            json.dumps(paragraph_plan, ensure_ascii=False),
            trace_mode,
        ),
    )
    await record_asset_event(
        "snippet_created",
        "snippet",
        snippet_id,
        paper_id=paper_id,
        source="writing",
        detail={"source_card_ids": source_card_ids, "evidence_ids": evidence_ids, "section_hint": section_hint},
    )
    rows = await list_snippets()
    for row in rows:
        if row.get("snippet_id") == snippet_id:
            return row
    raise RuntimeError("Snippet creation failed")


async def update_snippet(snippet_id: str, data: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM writing_snippets WHERE snippet_id = ?", (snippet_id,))
    if not row:
        raise ValueError("Writing snippet not found")
    fields: list[str] = []
    params: list[Any] = []
    for key in (
        "content",
        "source_card_id",
        "paper_id",
        "citation_key",
        "source_page",
        "source_quote",
        "section_hint",
        "source_card_ids",
        "evidence_ids",
        "paragraph_plan_json",
        "trace_mode",
    ):
        if key in data and data[key] is not None:
            value = data[key]
            if key == "paper_id" and value:
                await ensure_paper(str(value))
            if key == "source_page":
                value = max(0, int(value))
            if key == "section_hint":
                value = _require_choice(key, value, SECTION_HINTS)
            if key in {"source_card_ids", "evidence_ids"}:
                value = _json_list_text(value)
            if key == "paragraph_plan_json":
                value = _json_dict_text(value)
            fields.append(f"{key} = ?")
            params.append(value)
    if fields:
        fields.append("updated_at = datetime('now')")
        await db.execute(
            f"UPDATE writing_snippets SET {', '.join(fields)} WHERE snippet_id = ?",
            tuple(params + [snippet_id]),
        )
        await record_asset_event(
            "snippet_updated",
            "snippet",
            snippet_id,
            paper_id=str(data.get("paper_id") or row.get("paper_id") or ""),
            source="writing",
            detail={"changed_fields": sorted(data.keys())},
        )
    rows = await list_snippets()
    for item in rows:
        if item.get("snippet_id") == snippet_id:
            return item
    raise ValueError("Writing snippet not found")


async def delete_snippet(snippet_id: str) -> None:
    await db.execute("DELETE FROM writing_snippets WHERE snippet_id = ?", (snippet_id,))


async def build_comparison_table(paper_ids: list[str]) -> dict[str, Any]:
    paper_ids = [paper_id for paper_id in dict.fromkeys(str(item).strip() for item in paper_ids) if paper_id]
    if not paper_ids:
        raise ValueError("paper_ids must be non-empty")
    placeholders = ",".join("?" for _ in paper_ids)
    papers = await db.fetch_all(
        f"SELECT paper_id, title, citation_key FROM papers WHERE paper_id IN ({placeholders})",
        tuple(paper_ids),
    )
    cards = await db.fetch_all(
        f"""
        SELECT kc.card_id, kc.card_type, kc.paper_id, kc.title, kc.content,
               kc.source_page, kc.source_quote, COALESCE(p.citation_key, '') AS citation_key
          FROM knowledge_cards kc
          LEFT JOIN papers p ON p.paper_id = kc.paper_id
         WHERE kc.paper_id IN ({placeholders})
           AND kc.status = 'verified'
           AND kc.card_type IN ('dataset', 'metric', 'result', 'method', 'limitation')
         ORDER BY kc.paper_id, kc.card_type, kc.confidence DESC, kc.updated_at DESC
        """,
        tuple(paper_ids),
    )
    relation_rows = await db.fetch_all(
        f"""
        SELECT relation_id, source_paper_id, target_paper_id, confidence, status, negative_checks
          FROM research_relation_edges
         WHERE relation_type = 'conflicting_claim'
           AND status != 'rejected'
           AND (source_paper_id IN ({placeholders}) OR target_paper_id IN ({placeholders}))
         ORDER BY confidence DESC, updated_at DESC
        """,
        tuple(paper_ids + paper_ids),
    )
    conflicts_by_paper: dict[str, list[str]] = {}
    for relation in relation_rows:
        source = str(relation.get("source_paper_id") or "")
        target = str(relation.get("target_paper_id") or "")
        label = f"conflict:{relation.get('status') or 'review'} {source}->{target} ({float(relation.get('confidence') or 0):.2f})"
        conflicts_by_paper.setdefault(source, []).append(label)
        conflicts_by_paper.setdefault(target, []).append(label)
    by_paper_type: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for card in cards:
        by_paper_type.setdefault((str(card.get("paper_id") or ""), str(card.get("card_type") or "")), []).append(card)
    rows: list[dict[str, Any]] = []
    for paper in papers:
        paper_id = str(paper.get("paper_id") or "")
        row = {
            "paper_id": paper_id,
            "title": str(paper.get("title") or paper_id),
            "citation_key": _citation_key(paper),
            "method": _table_cell(by_paper_type.get((paper_id, "method"), [])),
            "dataset": _table_cell(by_paper_type.get((paper_id, "dataset"), [])),
            "metric": _table_cell(by_paper_type.get((paper_id, "metric"), [])),
            "result": _table_cell(by_paper_type.get((paper_id, "result"), [])),
            "limitation": _table_cell(by_paper_type.get((paper_id, "limitation"), [])),
            "conflicts": "\n".join(conflicts_by_paper.get(paper_id, [])) or "缺失",
        }
        rows.append(row)
    await record_asset_event(
        "comparison_table_generated",
        "writing",
        "comparison_table",
        source="writing",
        detail={"paper_ids": paper_ids, "rows": len(rows), "conflict_relations": len(relation_rows)},
    )
    return {"columns": ["paper", "method", "dataset", "metric", "result", "limitation", "conflicts"], "rows": rows}


def _table_cell(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return "缺失"
    parts: list[str] = []
    for index, card in enumerate(cards[:3], start=1):
        page = int(card.get("source_page") or 0)
        citation = str(card.get("citation_key") or "").strip()
        suffix_parts = []
        if citation:
            suffix_parts.append(f"@{citation}")
        if page:
            suffix_parts.append(f"p.{page}")
        suffix = f" [{' '.join(suffix_parts)}]" if suffix_parts else ""
        parts.append(f"{index}. {str(card.get('content') or card.get('title') or '').strip()}{suffix}"[:500])
    if len(cards) > 3:
        parts.append(f"+{len(cards) - 3} more evidence-backed cards")
    return "\n".join(parts)


async def compose_related_work_snippet(card_ids: list[str], *, section_hint: str = "related_work") -> dict[str, Any]:
    card_ids = [card_id for card_id in dict.fromkeys(str(item).strip() for item in card_ids) if card_id]
    if not card_ids:
        raise ValueError("card_ids must be non-empty")
    cards = [await get_card(card_id) for card_id in card_ids]
    paragraph_plan = _paragraph_plan_from_cards(cards, section_hint)
    sentences: list[str] = []
    evidence_ids: list[str] = []
    for index, card in enumerate(cards, start=1):
        evidence_ids.extend(str(eid) for eid in card.get("evidence_ids", []) if eid)
        citation = str(card.get("citation_key") or _citation_key(card))
        page = int(card.get("source_page") or 0)
        marker = f" @{citation}" if citation else ""
        source = f" p.{page}" if page else ""
        sentences.append(f"[C{index}] {str(card.get('content') or card.get('title') or '').strip()}{marker}{source}.")
    content = " ".join(sentence for sentence in sentences if sentence.strip())
    first = cards[0]
    return await create_snippet(
        {
            "content": content,
            "source_card_id": str(first.get("card_id") or ""),
            "source_card_ids": card_ids,
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "paragraph_plan_json": paragraph_plan,
            "paper_id": str(first.get("paper_id") or ""),
            "citation_key": str(first.get("citation_key") or ""),
            "source_page": int(first.get("source_page") or 0),
            "source_quote": str(first.get("source_quote") or ""),
            "section_hint": section_hint,
            "trace_mode": "traceable",
        }
    )


async def export_obsidian_markdown() -> str:
    cards = await list_cards(status="verified", limit=500)
    lines = ["# AI4Sec Knowledge Export", ""]
    for card in cards:
        title = str(card.get("title") or card.get("card_id") or "Card")
        lines.extend(
            [
                f"## {title}",
                "",
                str(card.get("content") or ""),
                "",
                f"- paper_id: {card.get('paper_id') or ''}",
                f"- page: {card.get('source_page') or 0}",
                f"- quote: {card.get('source_quote') or ''}",
                f"- tags: {card.get('tags') or ''}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


async def import_references(content: str, fmt: str = "bibtex") -> dict[str, Any]:
    refs = _parse_ris(content) if fmt == "ris" else _parse_bibtex(content)
    imported = 0
    skipped = 0
    paper_ids: list[str] = []
    for ref in refs:
        title = str(ref.get("title") or "").strip()
        doi = str(ref.get("doi") or "").strip()
        arxiv_id = str(ref.get("arxiv_id") or "").strip()
        if not title and not doi and not arxiv_id:
            skipped += 1
            continue
        existing = await _find_existing_reference(doi=doi, arxiv_id=arxiv_id, title=title)
        if existing:
            skipped += 1
            paper_ids.append(str(existing.get("paper_id") or ""))
            continue
        paper_id = _paper_id_from_reference(ref)
        citation_key = str(ref.get("citation_key") or "").strip()
        await db.execute(
            """
            INSERT OR IGNORE INTO papers (
                paper_id, file_path, original_filename, title, doi, venue, year,
                citation_key, reading_status, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unread', 'medium')
            """,
            (
                paper_id,
                f"references/{paper_id}",
                str(ref.get("source_name") or ""),
                title,
                doi or (f"arXiv:{arxiv_id}" if arxiv_id else ""),
                str(ref.get("venue") or ""),
                int(ref.get("year") or 0),
                citation_key,
            ),
        )
        imported += 1
        paper_ids.append(paper_id)
    return {"imported": imported, "skipped": skipped, "paper_ids": paper_ids}


def _parse_bibtex(content: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for entry in _bibtex_entries(content):
        fields = _bibtex_fields(entry["body"])
        title = fields.get("title", "")
        doi = fields.get("doi", "")
        arxiv_id = _extract_arxiv(fields.get("eprint", ""), fields.get("archiveprefix", ""), doi, title)
        refs.append(
            {
                "citation_key": entry["key"],
                "title": title,
                "doi": doi,
                "arxiv_id": arxiv_id,
                "venue": fields.get("journal") or fields.get("booktitle") or fields.get("venue") or "",
                "year": _year(fields.get("year", "")),
                "source_name": "bibtex",
            }
        )
    return refs


def _bibtex_entries(content: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    pos = 0
    while True:
        match = _BIB_ENTRY_START_RE.search(content, pos)
        if not match:
            break
        start = match.end()
        depth = 1
        in_quote = False
        escaped = False
        idx = start
        while idx < len(content) and depth > 0:
            char = content[idx]
            if in_quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "\"":
                    in_quote = False
            else:
                if char == "\"":
                    in_quote = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
            idx += 1
        raw = content[start: idx - 1]
        comma = raw.find(",")
        if comma > 0:
            entries.append({"key": raw[:comma].strip(), "body": raw[comma + 1:]})
        pos = idx
    return entries


def _bibtex_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    pos = 0
    while pos < len(body):
        match = re.search(r"([A-Za-z_]+)\s*=", body[pos:])
        if not match:
            break
        name = match.group(1).lower()
        pos += match.end()
        while pos < len(body) and body[pos].isspace():
            pos += 1
        if pos >= len(body):
            break
        value, pos = _read_bibtex_value(body, pos)
        fields[name] = _clean_ref_value(value)
        while pos < len(body) and body[pos] not in ",":
            pos += 1
        if pos < len(body) and body[pos] == ",":
            pos += 1
    return fields


def _read_bibtex_value(body: str, pos: int) -> tuple[str, int]:
    opener = body[pos]
    if opener == "{":
        depth = 1
        idx = pos + 1
        while idx < len(body) and depth > 0:
            if body[idx] == "{":
                depth += 1
            elif body[idx] == "}":
                depth -= 1
            idx += 1
        return body[pos + 1: idx - 1], idx
    if opener == "\"":
        idx = pos + 1
        escaped = False
        while idx < len(body):
            char = body[idx]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "\"":
                return body[pos + 1:idx], idx + 1
            idx += 1
        return body[pos + 1:], len(body)
    idx = pos
    while idx < len(body) and body[idx] != ",":
        idx += 1
    return body[pos:idx], idx


def _parse_ris(content: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    current: dict[str, list[str]] = {}
    for raw_line in content.splitlines():
        if len(raw_line) < 6 or raw_line[2:6] != "  - ":
            continue
        tag = raw_line[:2]
        value = raw_line[6:].strip()
        if tag == "TY":
            current = {"TY": [value]}
        elif tag == "ER":
            refs.append(_ris_record(current))
            current = {}
        else:
            current.setdefault(tag, []).append(value)
    if current:
        refs.append(_ris_record(current))
    return refs


def _ris_record(record: dict[str, list[str]]) -> dict[str, Any]:
    title = (record.get("TI") or record.get("T1") or [""])[0]
    doi = (record.get("DO") or [""])[0]
    arxiv_id = _extract_arxiv(doi, title, " ".join(record.get("N1", [])))
    return {
        "citation_key": (record.get("ID") or [""])[0],
        "title": title,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "venue": (record.get("JO") or record.get("JF") or record.get("T2") or [""])[0],
        "year": _year((record.get("PY") or record.get("Y1") or [""])[0]),
        "source_name": "ris",
    }


def _year(value: str) -> int:
    match = re.search(r"\d{4}", value or "")
    return int(match.group(0)) if match else 0


async def _find_existing_reference(doi: str = "", arxiv_id: str = "", title: str = "") -> dict[str, Any] | None:
    if doi:
        row = await db.fetch_one("SELECT * FROM papers WHERE LOWER(doi) = LOWER(?)", (doi,))
        if row:
            return row
    if arxiv_id:
        row = await db.fetch_one("SELECT * FROM papers WHERE LOWER(doi) = LOWER(?) OR LOWER(doi) = LOWER(?)", (arxiv_id, f"arXiv:{arxiv_id}"))
        if row:
            return row
    if title:
        norm = _normalize_title(title)
        rows = await db.fetch_all("SELECT * FROM papers WHERE title != ''")
        for row in rows:
            row_title = str(row.get("title") or "")
            if _normalize_title(row_title) == norm or _title_similarity(row_title, title) >= 0.93:
                return row
    return None


async def local_search(mode: str, query: str, limit: int = 20) -> dict[str, Any]:
    query = query.strip()
    limit = max(1, min(limit, 100))
    if not query:
        return {"mode": mode, "query": query, "results": []}
    term = _like(query)
    if mode == "papers":
        rows = await db.fetch_all(
            """
            SELECT paper_id, title, doi, venue, year, citation_key
              FROM papers
             WHERE title LIKE ? ESCAPE '\' OR doi LIKE ? ESCAPE '\'
                OR venue LIKE ? ESCAPE '\' OR citation_key LIKE ? ESCAPE '\'
             ORDER BY created_at DESC
             LIMIT ?
            """,
            (term, term, term, term, limit),
        )
        results = [
            {
                "result_type": "paper",
                "id": row["paper_id"],
                "title": row.get("title") or row["paper_id"],
                "snippet": f"{row.get('venue') or ''} {row.get('year') or ''}".strip(),
                "paper_id": row["paper_id"],
                "paper_title": row.get("title") or "",
                "metadata": {"citation_key": _citation_key(row), "doi": row.get("doi") or ""},
            }
            for row in rows
        ]
    elif mode == "fragments":
        rows = await db.fetch_all(
            """
            SELECT b.block_id, b.paper_id, b.page_idx, b.text, b.section_path,
                   COALESCE(p.title, '') AS paper_title, COALESCE(p.citation_key, '') AS citation_key
              FROM blocks b
              LEFT JOIN papers p ON p.paper_id = b.paper_id
             WHERE b.text LIKE ? ESCAPE '\'
             ORDER BY b.paper_id, b.order_idx
             LIMIT ?
            """,
            (term, limit),
        )
        results = [
            {
                "result_type": "fragment",
                "id": str(row["block_id"]),
                "title": row.get("section_path") or row.get("paper_title") or row["paper_id"],
                "snippet": str(row.get("text") or "")[:500],
                "paper_id": row["paper_id"],
                "paper_title": row.get("paper_title") or "",
                "page": int(row.get("page_idx") or 0) + 1,
                "metadata": {
                    "block_id": int(row.get("block_id") or 0),
                    "section_path": row.get("section_path") or "",
                    "citation_key": _citation_key(row),
                },
            }
            for row in rows
        ]
    elif mode == "relations":
        rows = await db.fetch_all(
            """
            SELECT re.*, COALESCE(sp.title, '') AS source_title, COALESCE(tp.title, '') AS target_title
              FROM research_relation_edges re
              LEFT JOIN papers sp ON sp.paper_id = re.source_paper_id
              LEFT JOIN papers tp ON tp.paper_id = re.target_paper_id
             WHERE re.relation_type LIKE ? ESCAPE '\' OR sp.title LIKE ? ESCAPE '\'
                OR tp.title LIKE ? ESCAPE '\'
             ORDER BY
                CASE re.status WHEN 'confirmed' THEN 0 WHEN 'unverified' THEN 1 ELSE 2 END,
                re.confidence DESC,
                re.updated_at DESC
             LIMIT ?
            """,
            (term, term, term, limit),
        )
        results = [
            {
                "result_type": "relation",
                "id": row["relation_id"],
                "title": row.get("relation_type") or "relation",
                "snippet": f"{row.get('source_title') or row.get('source_paper_id')} -> {row.get('target_title') or row.get('target_paper_id')}",
                "paper_id": row.get("source_paper_id") or "",
                "paper_title": row.get("source_title") or "",
                "score": float(row.get("confidence") or 0.0),
                "metadata": {
                    "status": row.get("status") or "",
                    "target_paper_id": row.get("target_paper_id") or "",
                    "target_title": row.get("target_title") or "",
                },
            }
            for row in rows
        ]
    elif mode == "writing":
        rows = await db.fetch_all(
            """
            SELECT ws.*, COALESCE(p.title, '') AS paper_title
              FROM writing_snippets ws
              LEFT JOIN papers p ON p.paper_id = ws.paper_id
             WHERE ws.content LIKE ? ESCAPE '\' OR ws.section_hint LIKE ? ESCAPE '\'
             ORDER BY ws.updated_at DESC
             LIMIT ?
            """,
            (term, term, limit),
        )
        results = [
            {
                "result_type": "writing",
                "id": row["snippet_id"],
                "title": row.get("section_hint") or "writing",
                "snippet": row.get("content") or "",
                "paper_id": row.get("paper_id") or "",
                "paper_title": row.get("paper_title") or "",
                "page": int(row.get("source_page") or 0),
                "metadata": {
                    "citation_key": row.get("citation_key") or "",
                    "source_card_id": row.get("source_card_id") or "",
                    "source_page": int(row.get("source_page") or 0),
                },
            }
            for row in rows
        ]
    else:
        cards = await list_cards(query=query, limit=limit)
        results = [
            {
                "result_type": "card",
                "id": row["card_id"],
                "title": row.get("title") or row.get("card_type") or "card",
                "snippet": row.get("content") or row.get("source_quote") or "",
                "paper_id": row.get("paper_id") or "",
                "paper_title": row.get("paper_title") or "",
                "page": int(row.get("source_page") or 0),
                "score": float(row.get("confidence") or 0.0),
                "metadata": {
                    "card_type": row.get("card_type") or "",
                    "status": row.get("status") or "",
                    "citation_key": row.get("citation_key") or "",
                },
            }
            for row in cards
        ]
        mode = "cards"
    return {"mode": mode, "query": query, "results": results}


async def export_snippets_markdown(section_hint: str = "", *, mode: str = "traceable") -> str:
    mode = "clean" if mode == "clean" else "traceable"
    snippets = await list_snippets(section_hint=section_hint)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for snippet in snippets:
        grouped.setdefault(str(snippet.get("section_hint") or "related_work"), []).append(snippet)
    lines: list[str] = []
    for section, rows in grouped.items():
        lines.append(f"## {section.replace('_', ' ').title()}")
        lines.append("")
        for row in rows:
            citation = str(row.get("citation_key") or "").strip()
            if not citation:
                citation = str(row.get("paper_id") or "").strip()
            suffix = f" [@{citation}]" if citation else ""
            lines.append(f"- {str(row.get('content') or '').strip()}{suffix}")
            if mode == "clean":
                continue
            source_parts = []
            if row.get("paper_id"):
                source_parts.append(f"paper_id={row['paper_id']}")
            source_card_ids = _json_list(row.get("source_card_ids")) or _json_list(row.get("source_card_id"))
            if source_card_ids:
                source_parts.append(f"card_ids={','.join(source_card_ids)}")
            evidence_ids = _json_list(row.get("evidence_ids"))
            if evidence_ids:
                source_parts.append(f"evidence_ids={','.join(evidence_ids)}")
            if int(row.get("source_page") or 0) > 0:
                source_parts.append(f"page={int(row.get('source_page') or 0)}")
            if source_parts:
                lines.append(f"  - source: {', '.join(source_parts)}")
            quote = _short_quote(str(row.get("source_quote") or ""))
            if quote:
                lines.append(f"  - quote: {quote}")
            plan = _json_dict(row.get("paragraph_plan_json"))
            if plan.get("order"):
                lines.append(f"  - paragraph_plan: {', '.join(str(item) for item in plan.get('order', []))}")
        lines.append("")
    if lines:
        await record_asset_event(
            "writing_exported",
            "writing",
            section_hint or "all",
            source="markdown",
            detail={"mode": mode, "section_hint": section_hint, "snippet_count": len(snippets)},
        )
    return "\n".join(lines).strip() + ("\n" if lines else "")


async def export_bibtex(collection_id: str = "") -> str:
    papers = await _papers_for_export(collection_id)
    entries: list[str] = []
    for row in papers:
        key = _citation_key(row)
        title = str(row.get("title") or row.get("original_filename") or row.get("paper_id") or "").replace("{", "").replace("}", "")
        venue = str(row.get("venue") or "").replace("{", "").replace("}", "")
        doi = str(row.get("doi") or "").strip()
        year = int(row.get("year") or 0)
        fields = [f"  title = {{{title}}}"]
        if venue:
            fields.append(f"  journal = {{{venue}}}")
        if year:
            fields.append(f"  year = {{{year}}}")
        if doi:
            fields.append(f"  doi = {{{doi}}}")
        entries.append("@article{" + key + ",\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries) + ("\n" if entries else "")


async def export_ris(collection_id: str = "") -> str:
    papers = await _papers_for_export(collection_id)
    lines: list[str] = []
    for row in papers:
        lines.extend([
            "TY  - JOUR",
            f"ID  - {_citation_key(row)}",
        ])
        if row.get("title"):
            lines.append(f"TI  - {row['title']}")
        if row.get("venue"):
            lines.append(f"JO  - {row['venue']}")
        if row.get("year"):
            lines.append(f"PY  - {int(row['year'])}")
        doi = str(row.get("doi") or "").strip()
        if doi:
            lines.append(f"DO  - {doi}")
        lines.append("ER  - ")
        lines.append("")
    return "\n".join(lines)


async def export_zotero_csl_json(collection_id: str = "") -> str:
    papers = await _papers_for_export(collection_id)
    entries: list[dict[str, Any]] = []
    for row in papers:
        entry: dict[str, Any] = {
            "id": _citation_key(row),
            "type": "article-journal" if row.get("venue") else "article",
            "title": _csl_text(str(row.get("title") or row.get("original_filename") or row.get("paper_id") or "")),
        }
        if row.get("venue"):
            entry["container-title"] = _csl_text(str(row.get("venue") or ""))
        if row.get("year"):
            entry["issued"] = {"date-parts": [[int(row.get("year") or 0)]]}
        doi = str(row.get("doi") or "").strip()
        if doi:
            entry["DOI"] = doi.replace("doi:", "").strip()
        entries.append(entry)
    return json.dumps(entries, ensure_ascii=False, indent=2) + ("\n" if entries else "")


def _csl_text(value: str) -> str:
    return _clean_ref_value(value).replace("{", "").replace("}", "")


async def _papers_for_export(collection_id: str = "") -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if collection_id:
        clauses.append(
            "EXISTS (SELECT 1 FROM paper_collection_items pci "
            "WHERE pci.paper_id = p.paper_id AND pci.collection_id = ?)"
        )
        params.append(collection_id)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return await db.fetch_all(
        f"""
        SELECT p.*
          FROM papers p
          {where_sql}
         ORDER BY p.year DESC, p.title ASC
        """,
        tuple(params),
    )


async def duplicate_candidates() -> list[dict[str, Any]]:
    papers = await db.fetch_all("SELECT paper_id, title, doi, year FROM papers ORDER BY created_at ASC")
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in papers:
        doi = str(row.get("doi") or "").strip().lower()
        title = str(row.get("title") or "")
        arxiv_id = _extract_arxiv(doi, title)
        title_key = _normalize_title(title)
        if doi and not doi.startswith("arxiv:"):
            buckets.setdefault(("doi", doi), []).append(row)
        if arxiv_id:
            buckets.setdefault(("arxiv", arxiv_id), []).append(row)
        if title_key and len(title_key) >= 12:
            buckets.setdefault(("title", title_key), []).append(row)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for (reason, key), rows in buckets.items():
        ids = tuple(sorted(str(row.get("paper_id") or "") for row in rows))
        if len(ids) < 2 or ids in seen:
            continue
        seen.add(ids)
        candidates.append({
            "reason": reason,
            "key": key,
            "paper_ids": list(ids),
            "titles": [str(row.get("title") or "") for row in rows],
        })
    for index, left in enumerate(papers):
        left_title = str(left.get("title") or "")
        if len(_normalize_title(left_title)) < 12:
            continue
        for right in papers[index + 1:]:
            right_title = str(right.get("title") or "")
            if len(_normalize_title(right_title)) < 12:
                continue
            similarity = _title_similarity(left_title, right_title)
            if similarity < 0.93:
                continue
            ids = tuple(sorted([str(left.get("paper_id") or ""), str(right.get("paper_id") or "")]))
            if ids in seen:
                continue
            seen.add(ids)
            candidates.append({
                "reason": "title_similarity",
                "key": f"{similarity:.3f}",
                "paper_ids": list(ids),
                "titles": [left_title, right_title],
            })
    return candidates


async def health_report() -> dict[str, Any]:
    total_papers = int((await db.fetch_one("SELECT COUNT(*) AS c FROM papers") or {}).get("c") or 0)
    unparsed_rows = await db.fetch_all(
        """
        SELECT p.paper_id
          FROM papers p
          LEFT JOIN mineru_parses mp ON mp.paper_id = p.paper_id AND mp.status = 'done'
         WHERE mp.paper_id IS NULL
        """
    )
    sync_failed_rows = await db.fetch_all("SELECT DISTINCT paper_id FROM dify_syncs WHERE status = 'failed'")
    missing_metadata_rows = await db.fetch_all(
        "SELECT paper_id FROM papers WHERE COALESCE(doi, '') = '' OR COALESCE(year, 0) = 0 OR COALESCE(venue, '') = ''"
    )
    duplicate_groups = await duplicate_candidates()
    stale_index_rows = await db.fetch_all(
        """
        SELECT p.paper_id
          FROM papers p
          LEFT JOIN dify_syncs ds ON ds.paper_id = p.paper_id
         WHERE EXISTS (SELECT 1 FROM blocks b WHERE b.paper_id = p.paper_id)
           AND (ds.paper_id IS NULL OR ds.status IN ('failed', 'pending'))
        """
    )
    read_without_notes_rows = await db.fetch_all(
        """
        SELECT p.paper_id
          FROM papers p
          LEFT JOIN paper_notes pn ON pn.paper_id = p.paper_id
          LEFT JOIN knowledge_cards kc ON kc.paper_id = p.paper_id AND kc.status NOT IN ('rejected', 'merged')
         WHERE p.reading_status = 'read'
           AND COALESCE(p.decision, '') != 'discard'
           AND kc.card_id IS NULL
           AND (pn.paper_id IS NULL OR (pn.summary_user = '' AND pn.key_takeaways = '' AND pn.open_questions = ''))
        """
    )
    reading_without_cards_rows = await db.fetch_all(
        """
        SELECT p.paper_id
          FROM papers p
         LEFT JOIN knowledge_cards kc ON kc.paper_id = p.paper_id AND kc.status != 'rejected'
         WHERE p.reading_status IN ('reading', 'read')
           AND COALESCE(p.decision, '') != 'discard'
           AND p.reading_status != 'archived'
           AND kc.card_id IS NULL
        """
    )
    pending_ai_cards_rows = await db.fetch_all(
        "SELECT card_id FROM knowledge_cards WHERE created_by = 'ai' AND status = 'draft'"
    )
    verified_without_evidence_rows = await db.fetch_all(
        """
        SELECT kc.card_id
          FROM knowledge_cards kc
          LEFT JOIN research_evidence_cards rec ON rec.card_id = kc.card_id
         WHERE kc.status = 'verified'
           AND kc.card_type IN ('claim', 'method', 'dataset', 'metric', 'result', 'limitation')
         GROUP BY kc.card_id
        HAVING COUNT(rec.evidence_id) = 0
        """
    )
    draft_backlog_rows = await db.fetch_all(
        """
        SELECT card_id, julianday('now') - julianday(created_at) AS age_days
          FROM knowledge_cards
         WHERE status = 'draft'
        """
    )
    draft_backlog_avg_age = (
        sum(float(row.get("age_days") or 0.0) for row in draft_backlog_rows) / len(draft_backlog_rows)
        if draft_backlog_rows
        else 0.0
    )
    ai_card_counts = await db.fetch_one(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN quality_flags LIKE '%low%' OR quality_flags LIKE '%missing%' THEN 1 ELSE 0 END) AS low_quality
          FROM knowledge_cards
         WHERE created_by = 'ai'
        """
    ) or {}
    ai_total = int(ai_card_counts.get("total") or 0)
    low_quality_ratio = round(float(ai_card_counts.get("low_quality") or 0) / ai_total, 3) if ai_total else 0.0
    weak_synthesis_rows = await db.fetch_all(
        """
        SELECT card_id
          FROM knowledge_cards
         WHERE asset_level = 'synthesis'
           AND status = 'verified'
           AND (
                supporting_paper_ids = '[]'
             OR json_array_length(supporting_paper_ids) < 2
           )
        """
    )
    gaps_missing_rows = await db.fetch_all(
        """
        SELECT gap_id
          FROM research_gaps
         WHERE status != 'rejected'
           AND (support_evidence_ids = '[]' OR minimum_experiment = '')
        """
    )
    snippets_missing_trace_rows = await db.fetch_all(
        """
        SELECT snippet_id
          FROM writing_snippets
         WHERE source_card_id = ''
           AND (source_card_ids = '[]' OR source_card_ids = '')
           AND (evidence_ids = '[]' OR evidence_ids = '')
        """
    )
    qa_stats = await db.fetch_one(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN graph_sources > 0 THEN 1 ELSE 0 END) AS graph_hit
          FROM library_qa_events
        """
    ) or {}
    qa_total = int(qa_stats.get("total") or 0)
    local_qa_graph_hit_ratio = round(float(qa_stats.get("graph_hit") or 0) / qa_total, 3) if qa_total else 0.0
    export_stats = await db.fetch_one(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN citation_key = '' AND paper_id = '' THEN 1 ELSE 0 END) AS missing
          FROM writing_snippets
        """
    ) or {}
    export_total = int(export_stats.get("total") or 0)
    export_citation_missing_rate = round(float(export_stats.get("missing") or 0) / export_total, 3) if export_total else 0.0
    isolated_evidence_rows = await db.fetch_all(
        """
        SELECT rei.evidence_id
          FROM research_evidence_items rei
          LEFT JOIN research_evidence_cards rec ON rec.evidence_id = rei.evidence_id
         WHERE rec.evidence_id IS NULL
        """
    )

    issues = [
        _issue("unparsed", "high", "未解析论文", unparsed_rows),
        _issue("sync_failed", "high", "Dify 同步失败", sync_failed_rows),
        _issue("missing_metadata", "medium", "元数据或 citation key 缺失", missing_metadata_rows),
        _issue("duplicates", "medium", "重复论文候选", [{"paper_id": group["paper_ids"][0]} for group in duplicate_groups], groups=duplicate_groups),
        _issue("read_without_notes", "medium", "已读但无笔记", read_without_notes_rows),
        _issue("reading_without_cards", "medium", "精读但无知识卡片", reading_without_cards_rows),
        _issue("pending_ai_cards", "low", "待审核 AI 草稿卡片", pending_ai_cards_rows, key="card_id"),
        _issue("stale_index", "medium", "待同步或待重建索引", stale_index_rows),
        _issue("verified_without_evidence", "high", "Verified 卡片缺少证据", verified_without_evidence_rows, key="card_id"),
        _issue("weak_synthesis", "high", "Synthesis 支撑论文不足", weak_synthesis_rows, key="card_id"),
        _issue("gaps_missing_support_or_experiment", "high", "Gap 缺少证据或最小实验", gaps_missing_rows, key="gap_id"),
        _issue("writing_missing_trace", "high", "写作片段缺少来源 trace", snippets_missing_trace_rows, key="snippet_id"),
        _issue("isolated_evidence", "medium", "孤立 evidence", isolated_evidence_rows, key="evidence_id"),
    ]
    return {
        "total_papers": total_papers,
        "unresolved_issues": sum(item["count"] for item in issues),
        "unparsed_papers": len(unparsed_rows),
        "sync_failed_papers": len(sync_failed_rows),
        "missing_metadata_papers": len(missing_metadata_rows),
        "duplicate_candidates": len(duplicate_groups),
        "stale_index_documents": len(stale_index_rows),
        "read_without_notes": len(read_without_notes_rows),
        "reading_without_cards": len(reading_without_cards_rows),
        "pending_ai_cards": len(pending_ai_cards_rows),
        "verified_cards_without_evidence": len(verified_without_evidence_rows),
        "draft_backlog_count": len(draft_backlog_rows),
        "draft_backlog_avg_age_days": round(draft_backlog_avg_age, 2),
        "low_quality_ai_candidate_ratio": low_quality_ratio,
        "weak_synthesis_cards": len(weak_synthesis_rows),
        "gaps_missing_support_or_experiment": len(gaps_missing_rows),
        "writing_snippets_missing_trace": len(snippets_missing_trace_rows),
        "local_qa_graph_hit_ratio": local_qa_graph_hit_ratio,
        "export_citation_missing_rate": export_citation_missing_rate,
        "isolated_evidence_count": len(isolated_evidence_rows),
        "issues": issues,
    }


async def fix_health_issue(issue_type: str, paper_ids: list[str] | None = None) -> dict[str, Any]:
    paper_ids = [paper_id for paper_id in dict.fromkeys(paper_ids or []) if paper_id]
    fixed = 0
    if issue_type == "sync_failed":
        if paper_ids:
            placeholders = ",".join("?" for _ in paper_ids)
            await db.execute(
                f"UPDATE dify_syncs SET status = 'pending', error_msg = '', updated_at = datetime('now') WHERE paper_id IN ({placeholders})",
                tuple(paper_ids),
            )
            fixed = len(paper_ids)
        else:
            await db.execute("UPDATE dify_syncs SET status = 'pending', error_msg = '', updated_at = datetime('now') WHERE status = 'failed'")
            fixed = 1
        await record_asset_event("health_fix", "health", issue_type, source="health", detail={"paper_ids": paper_ids, "fixed": fixed})
        return {"issue_type": issue_type, "fixed": fixed, "message": "同步失败项已标记为待重试"}
    if issue_type == "missing_metadata":
        targets = paper_ids or [row["paper_id"] for row in await db.fetch_all("SELECT paper_id FROM papers WHERE citation_key = ''")]
        for paper_id in targets:
            row = await ensure_paper(paper_id)
            await db.execute("UPDATE papers SET citation_key = ? WHERE paper_id = ? AND citation_key = ''", (_citation_key(row), paper_id))
            fixed += 1
        await record_asset_event("health_fix", "health", issue_type, source="health", detail={"paper_ids": targets, "fixed": fixed})
        return {"issue_type": issue_type, "fixed": fixed, "message": "已补齐可自动生成的 citation key；DOI、年份、venue 仍需人工确认"}
    if issue_type == "duplicates":
        groups = await duplicate_candidates()
        fixed = len(groups)
        await record_asset_event("health_fix", "health", issue_type, source="health", detail={"fixed": fixed})
        return {"issue_type": issue_type, "fixed": fixed, "message": "重复候选已刷新；不会自动合并或删除论文"}
    if issue_type == "stale_index":
        targets = paper_ids or [
            row["paper_id"]
            for row in await db.fetch_all(
                """
                SELECT p.paper_id
                  FROM papers p
                  LEFT JOIN dify_syncs ds ON ds.paper_id = p.paper_id
                 WHERE EXISTS (SELECT 1 FROM blocks b WHERE b.paper_id = p.paper_id)
                   AND (ds.paper_id IS NULL OR ds.status IN ('failed', 'pending'))
                """
            )
        ]
        for paper_id in targets:
            await db.execute(
                """
                INSERT INTO dify_syncs (paper_id, dataset_id, status, updated_at)
                VALUES (?, '', 'pending', datetime('now'))
                ON CONFLICT(paper_id, dataset_id) DO UPDATE SET
                    status = 'pending',
                    error_msg = '',
                    updated_at = datetime('now')
                """,
                (paper_id,),
            )
            fixed += 1
        await record_asset_event("health_fix", "health", issue_type, source="health", detail={"paper_ids": targets, "fixed": fixed})
        return {"issue_type": issue_type, "fixed": fixed, "message": "已标记为待同步/待重建，实际完成状态请查看同步状态"}
    if issue_type == "pending_ai_cards":
        await db.execute("UPDATE knowledge_cards SET status = 'draft', updated_at = datetime('now') WHERE created_by = 'ai' AND status = 'draft'")
        return {"issue_type": issue_type, "fixed": 0, "message": "待确认 AI 卡片需要人工确认或废弃"}
    return {"issue_type": issue_type, "fixed": 0, "message": "该问题需要人工处理"}


def _issue(
    issue_type: str,
    severity: str,
    label: str,
    rows: list[dict[str, Any]],
    *,
    key: str = "paper_id",
    groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "count": len(rows),
        "label": label,
        "paper_ids": [str(row.get(key) or "") for row in rows[:20]],
        "groups": groups or [],
    }
