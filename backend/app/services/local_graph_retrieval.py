"""Local research-graph retrieval for corpus-wide Q&A.

This module is the local structured-knowledge retrieval port used by
``corpus_qa``. It intentionally depends only on SQLite-backed assets, so Dify
can fail or be disabled without taking graph Q&A down.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.db import database as db

logger = logging.getLogger("scholar.local_graph_retrieval")

_STOPWORDS = frozenset({
    "what", "which", "how", "why", "the", "and", "for", "with", "from",
    "that", "this", "these", "those", "paper", "papers", "about", "into",
    "does", "did", "can", "could", "should", "would",
})
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,4}")


def _terms(question: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for token in _TOKEN_RE.findall(question.lower()):
        if token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= 10:
            break
    return terms


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _or_like_clause(columns: list[str], terms: list[str]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for term in terms:
        clauses.append("(" + " OR ".join(f"{col} LIKE ? ESCAPE '\\'" for col in columns) + ")")
        params.extend([_like(term)] * len(columns))
    return " OR ".join(clauses), params


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def _score(text: str, terms: list[str], base: float = 0.0) -> float:
    text_l = text.lower()
    score = base
    for term in terms:
        if term and term.lower() in text_l:
            score += 1.0
    return round(score, 4)


def _paper_name(row: dict[str, Any], fallback: str = "local graph") -> str:
    return str(row.get("paper_title") or row.get("title") or row.get("paper_id") or fallback)


def _source_record(
    *,
    document_id: str,
    document_name: str,
    segment_id: str,
    content: str,
    score: float,
    source_type: str,
    source_rank: int,
    paper_id: str = "",
    page: int = 0,
    card_id: str = "",
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "document_name": document_name,
        "segment_id": segment_id,
        "content": content,
        "score": score,
        "source_type": source_type,
        "card_id": card_id,
        "paper_id": paper_id,
        "page": page,
        "_source_rank": source_rank,
    }


async def _card_records(terms: list[str], limit: int) -> list[dict[str, Any]]:
    where, params = _or_like_clause(
        [
            "kc.title",
            "kc.content",
            "kc.tags",
            "kc.source_quote",
            "kc.normalized_key",
            "rei.quote",
            "rei.normalized_label",
            "COALESCE(p.title, '')",
        ],
        terms,
    )
    rows = await db.fetch_all(
        f"""
        SELECT
               kc.card_id, kc.card_type, kc.title, kc.content, kc.paper_id,
               kc.source_page, kc.source_quote, kc.asset_level, kc.action_type,
               kc.evidence_strength, kc.supporting_card_ids, kc.supporting_paper_ids,
               kc.confidence, kc.updated_at, COALESCE(p.title, '') AS paper_title,
               rei.evidence_id, rei.quote AS evidence_quote, rei.page AS evidence_page
          FROM knowledge_cards kc
          LEFT JOIN papers p ON p.paper_id = kc.paper_id
          LEFT JOIN research_evidence_cards rec ON rec.card_id = kc.card_id
          LEFT JOIN research_evidence_items rei ON rei.evidence_id = rec.evidence_id
         WHERE kc.status = 'verified'
           AND ({where})
         ORDER BY
           CASE kc.asset_level WHEN 'synthesis' THEN 0 WHEN 'action' THEN 1 ELSE 2 END,
           kc.confidence DESC,
           kc.updated_at DESC
         LIMIT ?
        """,
        tuple(params + [max(limit * 3, 10)]),
    )
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        card_id = str(row.get("card_id") or "")
        if not card_id or card_id in seen:
            continue
        seen.add(card_id)
        paper_title = _paper_name(row, "local card")
        quote = str(row.get("evidence_quote") or row.get("source_quote") or "")
        page = int(row.get("evidence_page") or row.get("source_page") or 0)
        asset_level = str(row.get("asset_level") or "evidence")
        source_rank = 0 if asset_level == "synthesis" else 1 if asset_level == "action" else 2
        support_cards = _json_list(row.get("supporting_card_ids"))
        support_papers = _json_list(row.get("supporting_paper_ids"))
        content = (
            f"Knowledge card ({asset_level}/{row.get('card_type') or 'claim'}): {row.get('title') or ''}\n"
            f"Claim: {row.get('content') or ''}\n"
            f"Paper: {paper_title}\n"
            f"Page: {page}\n"
            f"Evidence strength: {row.get('evidence_strength') or ''}\n"
            f"Supporting cards: {', '.join(support_cards)}\n"
            f"Supporting papers: {', '.join(support_papers)}\n"
            f"Evidence quote: {quote}"
        )
        records.append(
            _source_record(
                document_id=card_id,
                document_name=f"{paper_title} :: {row.get('title') or row.get('card_type') or 'card'}",
                segment_id=str(row.get("evidence_id") or card_id),
                content=content,
                score=_score(content, terms, float(row.get("confidence") or 0.0)),
                source_type="knowledge_graph",
                source_rank=source_rank,
                paper_id=str(row.get("paper_id") or ""),
                page=page,
                card_id=card_id,
            )
        )
    return records


async def _evidence_records(terms: list[str], limit: int) -> list[dict[str, Any]]:
    where, params = _or_like_clause(
        ["rei.quote", "rei.normalized_label", "rei.taxonomy_path", "rei.evidence_type", "COALESCE(p.title, '')"],
        terms,
    )
    rows = await db.fetch_all(
        f"""
        SELECT rei.*, COALESCE(p.title, '') AS paper_title
          FROM research_evidence_items rei
          LEFT JOIN papers p ON p.paper_id = rei.paper_id
         WHERE rei.status != 'rejected'
           AND ({where})
         ORDER BY
           CASE rei.status WHEN 'verified' THEN 0 WHEN 'revised' THEN 1 ELSE 2 END,
           rei.confidence DESC,
           rei.updated_at DESC
         LIMIT ?
        """,
        tuple(params + [max(limit * 2, 10)]),
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        evidence_id = str(row.get("evidence_id") or "")
        if not evidence_id:
            continue
        paper_title = _paper_name(row, "local evidence")
        page = int(row.get("page") or 0)
        content = (
            f"Evidence ({row.get('evidence_type') or 'evidence'}): {row.get('normalized_label') or ''}\n"
            f"Paper: {paper_title}\n"
            f"Page: {page}\n"
            f"Status: {row.get('status') or ''}\n"
            f"Quote: {row.get('quote') or ''}"
        )
        records.append(
            _source_record(
                document_id=evidence_id,
                document_name=f"{paper_title} :: evidence {row.get('evidence_type') or ''}".strip(),
                segment_id=evidence_id,
                content=content,
                score=_score(content, terms, float(row.get("confidence") or 0.0)),
                source_type="knowledge_graph",
                source_rank=2,
                paper_id=str(row.get("paper_id") or ""),
                page=page,
            )
        )
    return records


async def _relation_records(terms: list[str], limit: int) -> list[dict[str, Any]]:
    where, params = _or_like_clause(
        [
            "re.relation_type",
            "re.positive_checks",
            "re.negative_checks",
            "COALESCE(sp.title, '')",
            "COALESCE(tp.title, '')",
        ],
        terms,
    )
    rows = await db.fetch_all(
        f"""
        SELECT re.*, COALESCE(sp.title, '') AS source_title, COALESCE(tp.title, '') AS target_title
          FROM research_relation_edges re
          LEFT JOIN papers sp ON sp.paper_id = re.source_paper_id
          LEFT JOIN papers tp ON tp.paper_id = re.target_paper_id
         WHERE re.status != 'rejected'
           AND ({where})
         ORDER BY
           CASE re.status WHEN 'verified' THEN 0 WHEN 'confirmed' THEN 1 WHEN 'needs_more_evidence' THEN 2 ELSE 3 END,
           re.confidence DESC,
           re.updated_at DESC
         LIMIT ?
        """,
        tuple(params + [max(limit * 2, 10)]),
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        relation_id = str(row.get("relation_id") or "")
        if not relation_id:
            continue
        source_title = str(row.get("source_title") or row.get("source_paper_id") or "")
        target_title = str(row.get("target_title") or row.get("target_paper_id") or "")
        positives = _json_list(row.get("positive_checks"))
        negatives = _json_list(row.get("negative_checks"))
        content = (
            f"Research relation: {row.get('relation_type') or ''}\n"
            f"Source paper: {source_title}\n"
            f"Target paper: {target_title}\n"
            f"Status: {row.get('status') or ''}\n"
            f"Verifier: {row.get('verifier_version') or ''}\n"
            f"Positive checks: {', '.join(positives)}\n"
            f"Negative checks: {', '.join(negatives)}\n"
            f"Source evidence ids: {', '.join(_json_list(row.get('source_evidence_ids')))}\n"
            f"Target evidence ids: {', '.join(_json_list(row.get('target_evidence_ids')))}\n"
            f"Counter evidence ids: {', '.join(_json_list(row.get('counter_evidence_ids')))}"
        )
        records.append(
            _source_record(
                document_id=relation_id,
                document_name=f"{row.get('relation_type') or 'relation'} :: {source_title} -> {target_title}",
                segment_id=relation_id,
                content=content,
                score=_score(content, terms, float(row.get("confidence") or 0.0)),
                source_type="relation",
                source_rank=3,
                paper_id=str(row.get("source_paper_id") or ""),
            )
        )
    return records


async def _gap_records(terms: list[str], limit: int) -> list[dict[str, Any]]:
    where, params = _or_like_clause(
        ["title", "hypothesis", "description", "minimum_experiment", "coverage_status", "status"],
        terms,
    )
    rows = await db.fetch_all(
        f"""
        SELECT *
          FROM research_gaps
         WHERE status != 'rejected'
           AND ({where})
         ORDER BY
           CASE status WHEN 'pursue' THEN 0 WHEN 'promoted_to_idea' THEN 1 WHEN 'candidate' THEN 2 ELSE 3 END,
           domain_value DESC,
           feasibility_score DESC,
           updated_at DESC
         LIMIT ?
        """,
        tuple(params + [max(limit, 10)]),
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        gap_id = str(row.get("gap_id") or "")
        if not gap_id:
            continue
        content = (
            f"Research gap: {row.get('title') or ''}\n"
            f"Hypothesis: {row.get('hypothesis') or ''}\n"
            f"Description: {row.get('description') or ''}\n"
            f"Coverage: {row.get('coverage_status') or ''}\n"
            f"Status: {row.get('status') or ''}\n"
            f"Minimum experiment: {row.get('minimum_experiment') or ''}\n"
            f"Support evidence ids: {', '.join(_json_list(row.get('support_evidence_ids')))}\n"
            f"Counter evidence ids: {', '.join(_json_list(row.get('counter_evidence_ids')))}"
        )
        base = float(row.get("domain_value") or 0.0) + float(row.get("feasibility_score") or 0.0)
        records.append(
            _source_record(
                document_id=gap_id,
                document_name=f"Research gap :: {row.get('title') or gap_id}",
                segment_id=gap_id,
                content=content,
                score=_score(content, terms, base),
                source_type="knowledge_graph",
                source_rank=3,
            )
        )
    return records


async def _snippet_records(terms: list[str], limit: int) -> list[dict[str, Any]]:
    where, params = _or_like_clause(
        ["ws.content", "ws.source_quote", "ws.section_hint", "COALESCE(p.title, '')", "COALESCE(kc.title, '')"],
        terms,
    )
    rows = await db.fetch_all(
        f"""
        SELECT ws.*, COALESCE(p.title, '') AS paper_title, COALESCE(kc.title, '') AS card_title
          FROM writing_snippets ws
          LEFT JOIN papers p ON p.paper_id = ws.paper_id
          LEFT JOIN knowledge_cards kc ON kc.card_id = ws.source_card_id
         WHERE {where}
         ORDER BY ws.updated_at DESC
         LIMIT ?
        """,
        tuple(params + [max(limit, 10)]),
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        snippet_id = str(row.get("snippet_id") or "")
        if not snippet_id:
            continue
        paper_title = _paper_name(row, "writing snippet")
        page = int(row.get("source_page") or 0)
        content = (
            f"Writing snippet ({row.get('section_hint') or 'related_work'}): {row.get('content') or ''}\n"
            f"Paper: {paper_title}\n"
            f"Source card: {row.get('card_title') or row.get('source_card_id') or ''}\n"
            f"Page: {page}\n"
            f"Evidence quote: {row.get('source_quote') or ''}"
        )
        records.append(
            _source_record(
                document_id=snippet_id,
                document_name=f"{paper_title} :: writing {row.get('section_hint') or ''}".strip(),
                segment_id=snippet_id,
                content=content,
                score=_score(content, terms),
                source_type="snippet",
                source_rank=4,
                paper_id=str(row.get("paper_id") or ""),
                page=page,
                card_id=str(row.get("source_card_id") or ""),
            )
        )
    return records


async def search_local_graph_records(question: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Retrieve local structured research assets as corpus-QA context records."""
    query_terms = _terms(question)
    if not query_terms:
        return []
    bounded_limit = max(1, min(limit, 50))
    try:
        batches = [
            await _card_records(query_terms, bounded_limit),
            await _evidence_records(query_terms, bounded_limit),
            await _relation_records(query_terms, bounded_limit),
            await _gap_records(query_terms, bounded_limit),
            await _snippet_records(query_terms, bounded_limit),
        ]
    except Exception as exc:
        logger.debug("local graph retrieval skipped: %s", exc)
        return []

    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for batch in batches:
        for record in batch:
            key = (str(record.get("source_type") or ""), str(record.get("document_id") or ""))
            if not key[1] or key in seen:
                continue
            seen.add(key)
            records.append(record)
    records.sort(key=lambda item: (int(item.get("_source_rank") or 99), -float(item.get("score") or 0.0), str(item.get("document_name") or "")))
    for record in records:
        record.pop("_source_rank", None)
    return records[:bounded_limit]
