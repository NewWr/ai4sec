"""Unified evidence layer — the single foundation of the knowledge spine (ADR-1).

Every piece of supporting evidence (rule-extracted research findings, knowledge
card source quotes, run evidence pools, manual highlights) is persisted to
``research_evidence_items`` through this module. Evidence is a verbatim quote
anchored to ``(paper_id, page, block_id)``; it is atomic, verifiable and never
rewritten by an LLM — only re-anchored or version-bumped.

Cards bind to evidence through the ``research_evidence_cards`` bridge table
(written by ``knowledge_assets.create_card`` via ``evidence_ids``), so a fact
card is always traceable back to the source text (ADR-2).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.db import database as db

logger = logging.getLogger("scholar.evidence_store")

DEFAULT_EXTRACTOR = "auto_card_v1"
# Evidence types that originate from fact-style knowledge cards.
FACT_EVIDENCE_TYPES = {"claim", "method", "dataset", "metric", "result", "limitation"}


@dataclass(frozen=True)
class AnchorResult:
    ok: bool
    page: int = 0
    block_id: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("-\n", "").replace("\n", " ")).strip().lower()


def _hash(parts: list[str]) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def evidence_id(paper_id: str, evidence_type: str, quote: str) -> str:
    """Deterministic id so the same (paper, type, quote) dedups on re-upsert."""
    return _hash(["evidence", paper_id, evidence_type, _norm_text(quote)[:180]])[:24]


def _append_history(raw: Any, entry: dict[str, Any], *, limit: int = 50) -> str:
    try:
        history = json.loads(raw) if isinstance(raw, str) else (raw or [])
        if not isinstance(history, list):
            history = []
    except Exception:
        history = []
    history.append({"at": _now(), **entry})
    return json.dumps(history[-limit:], ensure_ascii=False)


async def anchor_quote(paper_id: str, quote: str) -> AnchorResult:
    """Anchor a verbatim quote back to its source block, returning page + block_id.

    Mirrors ``knowledge_card_generator.validate_card_source`` matching (exact
    normalized substring, then whitespace/punctuation-insensitive fallback) but
    also returns the owning ``block_id``.
    """
    quote_norm = _norm_text(quote)
    if not paper_id or not quote_norm:
        return AnchorResult(False)
    rows = await db.fetch_all(
        "SELECT block_id, page_idx, text FROM blocks WHERE paper_id = ? AND text != '' ORDER BY order_idx",
        (paper_id,),
    )
    for row in rows:
        text_norm = _norm_text(str(row.get("text") or ""))
        if quote_norm in text_norm:
            return AnchorResult(True, page=int(row.get("page_idx") or 0) + 1, block_id=int(row.get("block_id") or 0))
    compact_quote = re.sub(r"\W+", "", quote_norm)
    if compact_quote:
        for row in rows:
            compact_text = re.sub(r"\W+", "", _norm_text(str(row.get("text") or "")))
            if compact_quote in compact_text:
                return AnchorResult(True, page=int(row.get("page_idx") or 0) + 1, block_id=int(row.get("block_id") or 0))
    return AnchorResult(False)


async def upsert_evidence(
    paper_id: str,
    quote: str,
    *,
    evidence_type: str,
    page: int = 0,
    block_id: int = 0,
    source_run_id: str = "",
    normalized_label: str = "",
    taxonomy_path: str = "",
    confidence: float = 0.0,
    extractor: str = DEFAULT_EXTRACTOR,
    model_version: str = "",
    prompt_version: str = "",
    anchor: bool = True,
) -> str:
    """Upsert one evidence item and return its evidence_id.

    Same ``(paper_id, evidence_type, quote)`` dedups onto one row; re-upsert bumps
    ``evidence_version`` and appends a ``revision_history`` entry. Rejected
    evidence is never resurrected.
    """
    paper_id = str(paper_id or "").strip()
    quote = str(quote or "").strip()
    evidence_type = str(evidence_type or "").strip()
    if not paper_id or not quote or not evidence_type:
        raise ValueError("upsert_evidence requires paper_id, quote and evidence_type")

    if anchor and (not page or not block_id):
        anchored = await anchor_quote(paper_id, quote)
        if anchored.ok:
            page = page or anchored.page
            block_id = block_id or anchored.block_id

    eid = evidence_id(paper_id, evidence_type, quote)
    existing = await db.fetch_one(
        "SELECT evidence_version, revision_history, status FROM research_evidence_items WHERE evidence_id = ?",
        (eid,),
    )
    confidence = max(0.0, min(1.0, float(confidence or 0.0)))

    if existing:
        if str(existing.get("status") or "") == "rejected":
            return eid
        version = int(existing.get("evidence_version") or 1) + 1
        history = _append_history(
            existing.get("revision_history"),
            {"action": "revised", "extractor": extractor, "version": version, "source_run_id": source_run_id},
        )
        await db.execute(
            """
            UPDATE research_evidence_items
               SET quote = ?, page = ?, block_id = ?, normalized_label = ?, taxonomy_path = ?,
                   confidence = ?, source_run_id = ?, evidence_version = ?, revision_history = ?,
                   updated_at = datetime('now')
             WHERE evidence_id = ?
            """,
            (
                quote, page, block_id, normalized_label, taxonomy_path,
                confidence, source_run_id, version, history, eid,
            ),
        )
        return eid

    history = _append_history([], {"action": "created", "extractor": extractor, "source_run_id": source_run_id})
    await db.execute(
        """
        INSERT INTO research_evidence_items (
            evidence_id, evidence_type, paper_id, block_id, page, quote,
            normalized_label, taxonomy_path, confidence, extractor, model_version,
            prompt_version, status, revision_history, source_hash, source_run_id, evidence_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unverified', ?, ?, ?, 1)
        ON CONFLICT(evidence_id) DO NOTHING
        """,
        (
            eid, evidence_type, paper_id, block_id, page, quote,
            normalized_label, taxonomy_path, confidence, extractor, model_version,
            prompt_version, history, _hash([paper_id, evidence_type, _norm_text(quote)[:180]]), source_run_id,
        ),
    )
    return eid


async def upsert_evidence_many(rows: Iterable[dict[str, Any]]) -> None:
    """Batch upsert for high-volume rule extraction (research_discovery).

    Each row dict must carry: evidence_id, evidence_type, paper_id, block_id,
    page, quote, normalized_label, taxonomy_path, confidence, extractor,
    model_version, prompt_version, source_run_id, source_hash. Re-upsert bumps
    ``evidence_version`` arithmetically; rejected rows are left untouched.
    """
    params: list[tuple[Any, ...]] = []
    seen: set[str] = set()
    created_history = _append_history([], {"action": "created", "extractor": "rule_v1"})
    for row in rows:
        eid = str(row.get("evidence_id") or "")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        params.append(
            (
                eid,
                str(row.get("evidence_type") or ""),
                str(row.get("paper_id") or ""),
                int(row.get("block_id") or 0),
                int(row.get("page") or 0),
                str(row.get("quote") or ""),
                str(row.get("normalized_label") or ""),
                str(row.get("taxonomy_path") or ""),
                max(0.0, min(1.0, float(row.get("confidence") or 0.0))),
                str(row.get("extractor") or "rule_v1"),
                str(row.get("model_version") or ""),
                str(row.get("prompt_version") or ""),
                created_history,
                str(row.get("source_hash") or ""),
                str(row.get("source_run_id") or ""),
            )
        )
    if not params:
        return
    await db.execute_many(
        """
        INSERT INTO research_evidence_items (
            evidence_id, evidence_type, paper_id, block_id, page, quote,
            normalized_label, taxonomy_path, confidence, extractor, model_version,
            prompt_version, status, revision_history, source_hash, source_run_id, evidence_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unverified', ?, ?, ?, 1)
        ON CONFLICT(evidence_id) DO UPDATE SET
            quote = excluded.quote,
            normalized_label = excluded.normalized_label,
            taxonomy_path = excluded.taxonomy_path,
            confidence = excluded.confidence,
            source_hash = excluded.source_hash,
            source_run_id = excluded.source_run_id,
            evidence_version = research_evidence_items.evidence_version + 1,
            updated_at = datetime('now')
        WHERE research_evidence_items.status != 'rejected'
        """,
        params,
    )


async def backfill_card_evidence() -> dict[str, int]:
    """One-time idempotent migration: give legacy fact cards their bridge rows.

    For each fact card that has a ``source_quote`` but no ``research_evidence_cards``
    row, anchor the quote, upsert an evidence item and link it. Fact cards that
    cannot be anchored and are currently ``verified`` are demoted to ``draft`` so
    the post-migration invariant holds: every fact card is either evidence-backed
    or in the review queue. Only processes cards lacking a bridge row, so it is
    safe to run on every startup.
    """
    rows = await db.fetch_all(
        """
        SELECT kc.card_id, kc.paper_id, kc.card_type, kc.source_quote, kc.source_page,
               kc.status, kc.run_id
          FROM knowledge_cards kc
         WHERE kc.card_type IN ('claim', 'method', 'dataset', 'metric', 'result', 'limitation')
           AND kc.status NOT IN ('rejected', 'merged')
           AND kc.paper_id != ''
           AND kc.source_quote != ''
           AND NOT EXISTS (
                SELECT 1 FROM research_evidence_cards rec WHERE rec.card_id = kc.card_id
           )
        """
    )
    linked = 0
    demoted = 0
    for row in rows:
        card_id = str(row.get("card_id") or "")
        paper_id = str(row.get("paper_id") or "")
        quote = str(row.get("source_quote") or "").strip()
        anchored = await anchor_quote(paper_id, quote)
        if not anchored.ok:
            if str(row.get("status") or "") == "verified":
                await db.execute(
                    "UPDATE knowledge_cards SET status = 'draft', updated_at = datetime('now') WHERE card_id = ?",
                    (card_id,),
                )
                demoted += 1
            continue
        eid = await upsert_evidence(
            paper_id,
            quote,
            evidence_type=str(row.get("card_type") or "claim"),
            page=int(row.get("source_page") or 0) or anchored.page,
            block_id=anchored.block_id,
            source_run_id=str(row.get("run_id") or ""),
            extractor="backfill_v1",
            anchor=False,
        )
        await db.execute(
            "INSERT OR IGNORE INTO research_evidence_cards (evidence_id, card_id) VALUES (?, ?)",
            (eid, card_id),
        )
        linked += 1
    if linked or demoted:
        logger.info("backfill_card_evidence: linked=%d demoted=%d", linked, demoted)
    return {"linked": linked, "demoted": demoted}
