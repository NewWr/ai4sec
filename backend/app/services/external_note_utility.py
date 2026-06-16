from __future__ import annotations

import json
import re
from typing import Any

from app.db import database as db
from app.services.recommendation_behavior import build_behavior_terms, build_profile_terms, extract_behavior_terms


async def refresh_utility_score(note_id: str) -> dict[str, Any]:
    note = await db.fetch_one("SELECT * FROM external_paper_notes WHERE note_id = ?", (note_id,))
    if not note:
        raise KeyError("External note not found")
    try:
        behavior_terms = await build_behavior_terms(limit=80)
    except Exception:
        behavior_terms = []
    try:
        profile_terms = await build_profile_terms(limit=60)
    except Exception:
        profile_terms = []
    text = " ".join(
        str(note.get(key) or "")
        for key in ("title", "title_zh", "domain", "summary", "method", "experiments", "limitations", "keywords_json")
    )
    note_terms = set(extract_behavior_terms(text, limit=140))
    behavior_hit = _term_hits(note_terms, behavior_terms)
    profile_hit = _term_hits(note_terms, profile_terms)
    gap_rows = await db.fetch_all(
        "SELECT target_id, confidence, reason FROM external_note_matches WHERE note_id = ? AND target_kind = 'gap'",
        (note_id,),
    )
    local_rows = await db.fetch_all(
        "SELECT target_id, confidence, reason FROM external_note_matches WHERE note_id = ? AND target_kind IN ('paper', 'daily_item')",
        (note_id,),
    )
    behavior_score = min(1.0, len(behavior_hit) / 6.0)
    profile_score = min(1.0, len(profile_hit) / 5.0)
    gap_score = min(1.0, sum(float(row.get("confidence") or 0.0) for row in gap_rows))
    local_score = min(1.0, sum(float(row.get("confidence") or 0.0) for row in local_rows))
    venue_score = _venue_recency_score(note)
    feedback_score = _feedback_score(str(note.get("status") or ""))
    score = (
        behavior_score * 0.25
        + profile_score * 0.20
        + gap_score * 0.25
        + local_score * 0.15
        + venue_score * 0.10
        + feedback_score * 0.05
    )
    reasons: list[str] = []
    if gap_rows:
        reasons.append(f"命中研究缺口 {len(gap_rows)} 个")
    if local_rows:
        reasons.append("与本地论文或每日推荐存在匹配")
    if behavior_hit:
        reasons.append(f"命中近期阅读偏好：{' / '.join(behavior_hit[:4])}")
    if profile_hit:
        reasons.append(f"命中研究画像：{' / '.join(profile_hit[:4])}")
    conference = str(note.get("conference") or "")
    year = int(note.get("year") or 0)
    domain = str(note.get("domain") or "")
    if conference or year or domain:
        reasons.append("来自 " + " / ".join(str(x) for x in (conference, year or "", domain) if x))
    if str(note.get("arxiv_id") or ""):
        reasons.append("含 arXiv 链接")
    if str(note.get("code_url") or ""):
        reasons.append("含代码链接")
    utility_reason = "；".join(reasons)[:1000]
    await db.execute(
        """
        UPDATE external_paper_notes
           SET utility_score = ?,
               utility_reason = ?,
               updated_at = datetime('now')
         WHERE note_id = ?
        """,
        (round(score, 4), utility_reason, note_id),
    )
    updated = await db.fetch_one("SELECT * FROM external_paper_notes WHERE note_id = ?", (note_id,))
    return updated or {}


def _term_hits(note_terms: set[str], profile_terms: list[str]) -> list[str]:
    hits: list[str] = []
    for term in profile_terms:
        normalized = re.sub(r"\s+", " ", str(term or "").strip().lower())
        if not normalized:
            continue
        if normalized in note_terms or any(normalized in candidate or candidate in normalized for candidate in note_terms):
            hits.append(term)
    return hits[:12]


def _venue_recency_score(note: dict[str, Any]) -> float:
    year = int(note.get("year") or 0)
    conference = str(note.get("conference") or "").upper()
    score = 0.0
    if conference in {"CVPR", "ICCV", "ECCV", "NEURIPS", "ICLR", "ICML", "ACL", "EMNLP", "USENIX", "CCS", "NDSS", "S&P", "SP"}:
        score += 0.45
    if year >= 2026:
        score += 0.55
    elif year == 2025:
        score += 0.45
    elif year == 2024:
        score += 0.3
    elif year >= 2022:
        score += 0.15
    return min(1.0, score)


def _feedback_score(status: str) -> float:
    if status in {"useful", "promoted", "linked"}:
        return 1.0
    if status == "later":
        return 0.5
    if status in {"ignored", "irrelevant"}:
        return -1.0
    return 0.0


def score_detail_from_row(row: dict[str, Any]) -> dict[str, Any]:
    try:
        keywords = json.loads(str(row.get("keywords_json") or "[]"))
    except Exception:
        keywords = []
    return {
        "keywords": keywords if isinstance(keywords, list) else [],
        "utility_score": float(row.get("utility_score") or 0.0),
        "utility_reason": str(row.get("utility_reason") or ""),
    }
