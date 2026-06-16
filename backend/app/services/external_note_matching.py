from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from app.db import database as db
from app.services.recommendation_behavior import match_research_gaps_for_paper


def title_fingerprint(title: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (title or "").lower())
    tokens = [token for token in text.split() if token and token not in {"a", "an", "the", "of", "for", "and", "to"}]
    return " ".join(tokens[:24])


async def refresh_matches(note_id: str) -> list[dict[str, Any]]:
    note = await db.fetch_one("SELECT * FROM external_paper_notes WHERE note_id = ?", (note_id,))
    if not note:
        raise KeyError("External note not found")
    matches: list[dict[str, Any]] = []
    arxiv_id = str(note.get("arxiv_id") or "")
    title = str(note.get("title") or "")
    if arxiv_id:
        paper_rows = await db.fetch_all(
            """
            SELECT paper_id, title
              FROM papers
             WHERE lower(title) LIKE ?
                OR lower(original_filename) LIKE ?
                OR lower(citation_key) LIKE ?
            """,
            tuple([f"%{arxiv_id.lower()}%"] * 3),
        )
        for row in paper_rows:
            matches.append(await _upsert_match(note_id, "paper", str(row["paper_id"]), "arxiv_id", 0.98, f"arXiv ID {arxiv_id} matches local paper metadata"))
        daily_rows = await db.fetch_all(
            "SELECT item_id, title_en FROM daily_recommendation_items WHERE arxiv_id = ?",
            (arxiv_id,),
        )
        for row in daily_rows:
            matches.append(await _upsert_match(note_id, "daily_item", str(row["item_id"]), "arxiv_id", 0.99, f"arXiv ID {arxiv_id} appears in daily recommendations"))
            await db.execute(
                "UPDATE external_paper_notes SET linked_daily_item_id = ? WHERE note_id = ? AND linked_daily_item_id = ''",
                (str(row["item_id"]), note_id),
            )
    fp = title_fingerprint(title)
    if fp:
        local_rows = await db.fetch_all("SELECT paper_id, title FROM papers WHERE COALESCE(title, '') != '' LIMIT 1000")
        for row in local_rows:
            local_fp = title_fingerprint(str(row.get("title") or ""))
            if local_fp and (fp == local_fp or fp in local_fp or local_fp in fp):
                matches.append(await _upsert_match(note_id, "paper", str(row["paper_id"]), "title_fingerprint", 0.86, "Title fingerprint matches local paper"))
                await db.execute(
                    "UPDATE external_paper_notes SET linked_paper_id = ? WHERE note_id = ? AND linked_paper_id = ''",
                    (str(row["paper_id"]), note_id),
                )
    gap_matches = await match_research_gaps_for_paper(
        paper_key=f"external_note:{note_id}",
        title=title,
        abstract=" ".join(str(note.get(key) or "") for key in ("summary", "method", "experiments", "limitations")),
        limit=5,
    )
    for gap in gap_matches:
        reason = f"Matched research gap terms: {', '.join(gap.get('matched_terms') or [])}"
        matches.append(
            await _upsert_match(
                note_id,
                "gap",
                str(gap.get("gap_id") or ""),
                "keyword",
                float(gap.get("score") or 0.0),
                reason[:500],
            )
        )
    return matches


async def _upsert_match(
    note_id: str,
    target_kind: str,
    target_id: str,
    match_type: str,
    confidence: float,
    reason: str,
) -> dict[str, Any]:
    if not target_id:
        return {}
    match_id = hashlib.sha1(f"{note_id}:{target_kind}:{target_id}:{match_type}".encode("utf-8")).hexdigest()[:24]
    await db.execute(
        """
        INSERT INTO external_note_matches (
            match_id, note_id, target_kind, target_id, match_type, confidence, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(note_id, target_kind, target_id, match_type) DO UPDATE SET
            confidence = excluded.confidence,
            reason = excluded.reason
        """,
        (
            match_id or uuid.uuid4().hex[:24],
            note_id,
            target_kind,
            target_id,
            match_type,
            max(0.0, min(1.0, float(confidence))),
            reason[:1000],
        ),
    )
    return await db.fetch_one(
        """
        SELECT * FROM external_note_matches
         WHERE note_id = ? AND target_kind = ? AND target_id = ? AND match_type = ?
        """,
        (note_id, target_kind, target_id, match_type),
    ) or {}
