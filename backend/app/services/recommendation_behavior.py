from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from app.db import database as db

_LATIN_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)*\b", re.IGNORECASE)
_CJK_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,8}")
_STOP_TERMS = {
    "about",
    "after",
    "against",
    "and",
    "analysis",
    "an",
    "approach",
    "are",
    "by",
    "based",
    "between",
    "dataset",
    "datasets",
    "deep",
    "evaluation",
    "for",
    "framework",
    "from",
    "in",
    "image",
    "images",
    "is",
    "learning",
    "method",
    "model",
    "models",
    "of",
    "on",
    "paper",
    "papers",
    "result",
    "results",
    "study",
    "that",
    "the",
    "this",
    "to",
    "using",
    "vision",
    "we",
    "with",
    "方法",
    "模型",
    "论文",
    "结果",
    "数据",
    "任务",
    "研究",
}


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return [item.strip() for item in text.split(",") if item.strip()]
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def _json_any_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", str(term or "").replace("_", " ").strip().lower())


def _term_allowed(term: str) -> bool:
    if not term or term in _STOP_TERMS:
        return False
    if term.isdigit():
        return False
    if re.fullmatch(r"[a-z]", term):
        return False
    return len(term) >= 2 if re.search(r"[\u4e00-\u9fff]", term) else len(term) >= 3


def _phrase_allowed(tokens: list[str]) -> bool:
    if not tokens:
        return False
    if tokens[0] in _STOP_TERMS:
        return False
    if all(token in _STOP_TERMS for token in tokens):
        return False
    phrase = " ".join(tokens)
    return 5 <= len(phrase) <= 60


def extract_behavior_terms(*texts: str, limit: int = 80) -> list[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        raw = str(text or "")
        tokens = [_normalize_term(match) for match in _LATIN_TOKEN_RE.findall(raw)]
        tokens = [token for token in tokens if token]
        for token in tokens:
            if _term_allowed(token) and token not in _STOP_TERMS:
                counter[token] += 1
        for size in (2, 3):
            for idx in range(0, max(0, len(tokens) - size + 1)):
                ngram = tokens[idx : idx + size]
                if _phrase_allowed(ngram):
                    counter[" ".join(ngram)] += 2 if size == 2 else 1
        for match in _CJK_TERM_RE.findall(raw):
            term = _normalize_term(match)
            if _term_allowed(term):
                counter[term] += 1
    return [term for term, _count in counter.most_common(limit)]


async def build_profile_terms(*, limit: int = 60) -> list[str]:
    """Weighted terms from the global research profile (module C consumer).

    Reads the semantic research profile built by the research-construction batch
    (``research_profile.topic_weights_json`` + ``profile_text``) so daily
    recommendation scoring can re-rank toward the user's accumulated interests
    and accepted/rejected ideas. Returns an empty list when no profile has been
    built yet, leaving scoring unchanged.
    """
    row = await db.fetch_one(
        "SELECT profile_text, topic_weights_json FROM research_profile WHERE profile_id = 'global'"
    )
    if not row:
        return []
    counter: Counter[str] = Counter()
    try:
        weights = json.loads(str(row.get("topic_weights_json") or "{}"))
    except Exception:
        weights = {}
    if isinstance(weights, dict):
        for term, weight in weights.items():
            normalized = _normalize_term(str(term))
            if not _term_allowed(normalized):
                continue
            counter[normalized] += max(1, int(weight)) if isinstance(weight, (int, float)) else 1
    for term in extract_behavior_terms(str(row.get("profile_text") or ""), limit=40):
        counter[term] += 1
    return [term for term, _count in counter.most_common(limit)]


async def build_behavior_terms(*, limit: int = 80) -> list[str]:
    rows = await db.fetch_all(
        """
        SELECT text, weight
          FROM (
                SELECT
                    COALESCE(title, '') || ' ' || COALESCE(citation_key, '') AS text,
                    CASE
                        WHEN decision IN ('must_read', 'useful') THEN 4
                        WHEN reading_status = 'read' THEN 3
                        ELSE 2
                    END AS weight,
                    COALESCE(NULLIF(last_read_at, ''), created_at) AS ts
                  FROM papers
                 WHERE reading_status IN ('reading', 'read')
                   AND COALESCE(decision, '') != 'discard'
                UNION ALL
                SELECT
                    COALESCE(title, '') || ' ' || COALESCE(content, '') || ' ' || COALESCE(tags, '') AS text,
                    3 AS weight,
                    updated_at AS ts
                  FROM knowledge_cards
                 WHERE status = 'verified'
                   AND asset_level IN ('action', 'synthesis', 'evidence')
                UNION ALL
                SELECT
                    COALESCE(title_en, '') || ' ' || COALESCE(abstract_en, '') AS text,
                    3 AS weight,
                    created_at AS ts
                  FROM daily_recommendation_items
                 WHERE status IN ('interested', 'ingested')
                UNION ALL
                SELECT
                    COALESCE(user_question, '') AS text,
                    2 AS weight,
                    started_at AS ts
                  FROM runs
                 WHERE COALESCE(user_question, '') != ''
               )
         WHERE COALESCE(text, '') != ''
         ORDER BY ts DESC
         LIMIT 200
        """
    )
    counter: Counter[str] = Counter()
    for row in rows:
        weight = max(1, min(5, int(row.get("weight") or 1)))
        for term in extract_behavior_terms(str(row.get("text") or ""), limit=30):
            counter[term] += weight
    return [term for term, _count in counter.most_common(limit)]


async def match_research_gaps_for_paper(
    *,
    paper_key: str,
    title: str,
    abstract: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    haystack_terms = set(extract_behavior_terms(title, abstract, limit=120))
    if not haystack_terms:
        return []
    rows = await db.fetch_all(
        """
        SELECT gap_id, title, hypothesis, description, minimum_experiment, hit_by_paper_ids, history_json
          FROM research_gaps
         WHERE status NOT IN ('rejected', 'promoted_to_idea')
         ORDER BY evidence_strength DESC, novelty_score DESC, updated_at DESC
         LIMIT 200
        """
    )
    matches: list[dict[str, Any]] = []
    for row in rows:
        gap_text = " ".join(
            str(row.get(key) or "")
            for key in ("title", "hypothesis", "description", "minimum_experiment")
        )
        gap_terms = set(extract_behavior_terms(gap_text, limit=80))
        shared = sorted(
            haystack_terms & gap_terms,
            key=lambda term: ((" " in term), len(term)),
            reverse=True,
        )
        if len(shared) < 2:
            continue
        matches.append(
            {
                "gap_id": str(row.get("gap_id") or ""),
                "title": str(row.get("title") or ""),
                "matched_terms": shared[:8],
                "score": round(min(1.0, len(shared) / max(4, len(gap_terms) or 1)), 3),
            }
        )
    matches.sort(key=lambda item: (float(item["score"]), len(item["matched_terms"])), reverse=True)
    selected = matches[:limit]
    if paper_key and selected:
        for match in selected:
            row = next((item for item in rows if str(item.get("gap_id") or "") == match["gap_id"]), None)
            existing = _json_list(row.get("hit_by_paper_ids") if row else "[]")
            if paper_key in existing:
                continue
            history = _json_any_list(row.get("history_json") if row else "[]")
            history.append({"event": "hit_by_new_paper", "paper_key": paper_key, "matched_terms": match["matched_terms"]})
            await db.execute(
                """
                UPDATE research_gaps
                   SET hit_by_paper_ids = ?,
                       history_json = ?,
                       coverage_status = CASE
                           WHEN coverage_status IN ('unknown', 'uncovered') THEN 'partially_covered'
                           ELSE coverage_status
                       END,
                       updated_at = datetime('now')
                 WHERE gap_id = ?
                """,
                (
                    json.dumps([*existing, paper_key], ensure_ascii=False),
                    json.dumps(history[-80:], ensure_ascii=False),
                    match["gap_id"],
                ),
            )
    return selected
