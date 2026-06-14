from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.db import database as db
from app.services import entity_registry, knowledge_assets, knowledge_synthesis, research_discovery, semantic_index
from app.services.llm_runtime_config import get_llm_runtime_config
from app.services.llm_service import get_llm_service
from app.services.paper_search.config import Settings as PaperSearchSettings
from app.services.paper_search.search import search_papers

logger = logging.getLogger("scholar.research_construction")

_jobs: dict[str, asyncio.Task[dict[str, Any]]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _job_id() -> str:
    return "construct_" + uuid.uuid4().hex


def _feedback_id(item_id: str, verdict: str) -> str:
    return "ifeed_" + hashlib.sha1(f"{item_id}:{verdict}:{_now()}".encode("utf-8")).hexdigest()[:24]


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _loads_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _hash(parts: list[str]) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _clean_text(value: str, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _counts() -> dict[str, int]:
    rows = await db.fetch_all(
        """
        SELECT 'papers' AS key, COUNT(*) AS count FROM papers
        UNION ALL SELECT 'evidence', COUNT(*) FROM research_evidence_items
        UNION ALL SELECT 'cards', COUNT(*) FROM knowledge_cards
        UNION ALL SELECT 'relations', COUNT(*) FROM research_relation_edges
        UNION ALL SELECT 'gaps', COUNT(*) FROM research_gaps
        """
    )
    return {str(row.get("key") or ""): int(row.get("count") or 0) for row in rows}


async def get_state() -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM construction_state WHERE state_key = 'global'")
    counts = await _counts()
    if not row:
        return {
            "state_key": "global",
            "last_construction_at": "",
            "last_paper_count": 0,
            "last_evidence_count": 0,
            "last_card_count": 0,
            "state": {},
            "current_counts": counts,
        }
    return {
        "state_key": "global",
        "last_construction_at": str(row.get("last_construction_at") or ""),
        "last_paper_count": int(row.get("last_paper_count") or 0),
        "last_evidence_count": int(row.get("last_evidence_count") or 0),
        "last_card_count": int(row.get("last_card_count") or 0),
        "state": _loads_dict(str(row.get("state_json") or "{}")),
        "current_counts": counts,
    }


async def should_run_threshold() -> bool:
    settings = get_settings()
    state = await get_state()
    counts = state["current_counts"]
    new_papers = int(counts.get("papers", 0)) - int(state.get("last_paper_count", 0))
    new_evidence = int(counts.get("evidence", 0)) - int(state.get("last_evidence_count", 0))
    threshold = max(1, int(settings.research_construction_new_paper_threshold or 10))
    return new_papers >= threshold or new_evidence >= threshold


async def estimate_plan() -> dict[str, Any]:
    settings = get_settings()
    counts = await _counts()
    unembedded_cards = await db.fetch_one(
        """
        SELECT COUNT(*) AS count
          FROM knowledge_cards kc
          LEFT JOIN card_embeddings ce ON ce.card_id = kc.card_id
         WHERE kc.status NOT IN ('rejected', 'merged')
           AND ce.card_id IS NULL
        """
    )
    unembedded_nodes = await db.fetch_one(
        """
        SELECT COUNT(*) AS count
          FROM paper_nodes pn
          LEFT JOIN node_embeddings ne ON ne.node_id = pn.node_id
         WHERE pn.node_type = 'chunk'
           AND ne.node_id IS NULL
        """
    )
    candidate_gaps = await db.fetch_one(
        "SELECT COUNT(*) AS count FROM research_gaps WHERE status NOT IN ('rejected', 'covered')"
    )
    relation_clusters = await db.fetch_one(
        "SELECT COUNT(*) AS count FROM research_relation_edges WHERE status != 'rejected'"
    )
    new_entities = await db.fetch_one(
        """
        SELECT COUNT(*) AS count
          FROM knowledge_cards kc
          LEFT JOIN entity_mentions em ON em.card_id = kc.card_id
         WHERE kc.card_type IN ('method', 'dataset', 'metric', 'result', 'limitation')
           AND kc.status NOT IN ('rejected', 'merged')
           AND em.card_id IS NULL
        """
    )
    batch = max(1, int(settings.embedding_backfill_batch or 128))
    idea_limit = max(0, int(settings.research_construction_max_ideas_per_run or 12))
    promote_estimate = min(idea_limit, int((candidate_gaps or {}).get("count") or 0))
    chat_calls = (
        min(int((candidate_gaps or {}).get("count") or 0), idea_limit)
        + min(promote_estimate, int(settings.research_construction_novelty_check_limit or 6))
        + min(promote_estimate, int(settings.idea_critique_limit or 6))
        + min(int((relation_clusters or {}).get("count") or 0), int(settings.research_construction_synthesis_limit or 8))
        + min(int((new_entities or {}).get("count") or 0), int(settings.max_entities_per_run or 20))
        + 1
    )
    unembedded_total = int((unembedded_cards or {}).get("count") or 0) + int((unembedded_nodes or {}).get("count") or 0)
    return {
        "counts": counts,
        "embedding_enabled": semantic_index.embedding_enabled(),
        "llm_configured": bool(
            get_llm_runtime_config().base_url
            and get_llm_runtime_config().api_key
            and get_llm_runtime_config().default_thinking_model
        ),
        "limits": {
            "max_ideas": idea_limit,
            "novelty_check": int(settings.research_construction_novelty_check_limit or 6),
            "idea_critique": int(settings.idea_critique_limit or 6),
            "synthesis": int(settings.research_construction_synthesis_limit or 8),
            "entities": int(settings.max_entities_per_run or 20),
            "embedding_batch": batch,
        },
        "estimated_chat_calls": max(0, chat_calls),
        "estimated_embedding_batches": (unembedded_total + batch - 1) // batch,
        "unembedded_cards": int((unembedded_cards or {}).get("count") or 0),
        "unembedded_nodes": int((unembedded_nodes or {}).get("count") or 0),
        "candidate_gaps": int((candidate_gaps or {}).get("count") or 0),
        "relation_clusters": int((relation_clusters or {}).get("count") or 0),
        "new_entity_mentions": int((new_entities or {}).get("count") or 0),
    }


def _job_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(row.get("job_id") or ""),
        "trigger_source": str(row.get("trigger_source") or "manual"),
        "dry_run": bool(row.get("dry_run") or 0),
        "status": str(row.get("status") or "pending"),
        "progress": _loads_dict(str(row.get("progress_json") or "{}")),
        "estimate": _loads_dict(str(row.get("estimate_json") or "{}")),
        "result": _loads_dict(str(row.get("result_json") or "{}")),
        "error_msg": str(row.get("error_msg") or ""),
        "started_at": str(row.get("started_at") or ""),
        "finished_at": str(row.get("finished_at") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


async def _insert_job(job_id: str, *, trigger_source: str, dry_run: bool, estimate: dict[str, Any]) -> None:
    await db.execute(
        """
        INSERT INTO construction_jobs (
            job_id, trigger_source, dry_run, status, progress_json, estimate_json,
            result_json, started_at, updated_at
        ) VALUES (?, ?, ?, 'pending', '{}', ?, '{}', '', datetime('now'))
        """,
        (job_id, trigger_source, 1 if dry_run else 0, _json(estimate)),
    )


async def _update_job(job_id: str, **fields: Any) -> None:
    allowed = {
        "status",
        "progress_json",
        "estimate_json",
        "result_json",
        "error_msg",
        "started_at",
        "finished_at",
    }
    updates: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        updates.append(f"{key} = ?")
        params.append(value)
    if not updates:
        return
    updates.append("updated_at = datetime('now')")
    await db.execute(
        f"UPDATE construction_jobs SET {', '.join(updates)} WHERE job_id = ?",
        tuple(params + [job_id]),
    )


async def get_job(job_id: str) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM construction_jobs WHERE job_id = ?", (job_id,))
    if not row:
        raise ValueError("Construction job not found")
    return _job_response(row)


async def start_construction_job(*, dry_run: bool = False, force: bool = False, trigger_source: str = "manual") -> dict[str, Any]:
    if not dry_run and not force and trigger_source != "manual" and not await should_run_threshold():
        estimate = await estimate_plan()
        job_id = _job_id()
        await _insert_job(job_id, trigger_source=trigger_source, dry_run=True, estimate=estimate)
        await _update_job(
            job_id,
            status="skipped",
            finished_at=_now(),
            result_json=_json({"skipped": True, "reason": "threshold_not_met"}),
        )
        return await get_job(job_id)
    estimate = await estimate_plan()
    job_id = _job_id()
    await _insert_job(job_id, trigger_source=trigger_source, dry_run=dry_run, estimate=estimate)
    if dry_run:
        await _update_job(job_id, status="done", finished_at=_now(), result_json=_json({"dry_run": True, "estimate": estimate}))
        return await get_job(job_id)
    task = asyncio.create_task(run_construction_job(job_id), name=f"research-construction-{job_id}")
    _jobs[job_id] = task
    return await get_job(job_id)


async def _stage(job_id: str, name: str, result: dict[str, Any] | None = None) -> None:
    current = await get_job(job_id)
    progress = current.get("progress") or {}
    stages = progress.setdefault("stages", {})
    stages[name] = {"status": "done" if result is not None else "running", "result": result or {}, "updated_at": _now()}
    await _update_job(job_id, progress_json=_json(progress))


async def run_construction_job(job_id: str) -> dict[str, Any]:
    await _update_job(job_id, status="running", started_at=_now())
    result: dict[str, Any] = {}
    try:
        await _stage(job_id, "discovery_refresh")
        discovery = await research_discovery.build_research_discovery(limit=500)
        stage_result = {
            "papers": discovery.stats.total_papers,
            "evidence": discovery.stats.evidence_items,
            "relations": discovery.stats.relation_edges,
            "gaps": discovery.stats.gap_candidates,
        }
        result["discovery_refresh"] = stage_result
        await _stage(job_id, "discovery_refresh", stage_result)

        await _stage(job_id, "entity_registry")
        entity_result = await entity_registry.normalize_entities(limit=600)
        result["entity_registry"] = entity_result
        await _stage(job_id, "entity_registry", entity_result)

        await _stage(job_id, "semantic_index")
        card_index = await semantic_index.backfill_embeddings("card", limit=800)
        node_index = await semantic_index.backfill_embeddings("node", limit=1200)
        semantic_result = {"cards": card_index, "nodes": node_index}
        result["semantic_index"] = semantic_result
        await _stage(job_id, "semantic_index", semantic_result)

        await _stage(job_id, "synthesis")
        synthesis_result = await rebuild_llm_synthesis(limit=get_settings().research_construction_synthesis_limit)
        result["synthesis"] = synthesis_result
        await _stage(job_id, "synthesis", synthesis_result)

        await _stage(job_id, "ideas")
        ideas_result = await build_ideas(job_id, limit=get_settings().research_construction_max_ideas_per_run)
        result["ideas"] = ideas_result
        await _stage(job_id, "ideas", ideas_result)

        await _stage(job_id, "research_profile")
        profile_result = await rebuild_research_profile(job_id)
        result["research_profile"] = profile_result
        await _stage(job_id, "research_profile", profile_result)

        counts = await _counts()
        await db.execute(
            """
            INSERT INTO construction_state (
                state_key, state_json, last_construction_at, last_paper_count,
                last_evidence_count, last_card_count, updated_at
            ) VALUES ('global', ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(state_key) DO UPDATE SET
                state_json = excluded.state_json,
                last_construction_at = excluded.last_construction_at,
                last_paper_count = excluded.last_paper_count,
                last_evidence_count = excluded.last_evidence_count,
                last_card_count = excluded.last_card_count,
                updated_at = datetime('now')
            """,
            (_json({"last_job_id": job_id, "result": result}), _now(), counts.get("papers", 0), counts.get("evidence", 0), counts.get("cards", 0)),
        )
        await _update_job(job_id, status="done", finished_at=_now(), result_json=_json(result))
        return await get_job(job_id)
    except Exception as exc:
        logger.exception("research construction job failed job_id=%s", job_id)
        await _update_job(job_id, status="failed", finished_at=_now(), error_msg=str(exc)[:1000], result_json=_json(result))
        return await get_job(job_id)
    finally:
        _jobs.pop(job_id, None)


async def rebuild_llm_synthesis(*, limit: int = 8) -> dict[str, int | str]:
    base = await knowledge_synthesis.rebuild_synthesis_cards(limit=600)
    rows = await db.fetch_all(
        """
        SELECT re.*, COALESCE(sp.title, '') AS source_title, COALESCE(tp.title, '') AS target_title
          FROM research_relation_edges re
          LEFT JOIN papers sp ON sp.paper_id = re.source_paper_id
          LEFT JOIN papers tp ON tp.paper_id = re.target_paper_id
         WHERE re.status IN ('verified', 'confirmed', 'needs_more_evidence')
         ORDER BY
            CASE re.relation_type WHEN 'conflicting_claim' THEN 0 WHEN 'transferable_method' THEN 1 ELSE 2 END,
            re.confidence DESC,
            re.updated_at DESC
         LIMIT ?
        """,
        (max(1, int(limit)),),
    )
    created = 0
    for row in rows:
        relation_id = str(row.get("relation_id") or "")
        if not relation_id:
            continue
        existing = await knowledge_assets.list_cards(asset_level="synthesis", status="verified", query=relation_id, limit=5)
        normalized_key = f"construction:synthesis:{relation_id}"
        if any(str(card.get("normalized_key") or "") == normalized_key for card in existing):
            continue
        content = await _relation_synthesis_content(row)
        evidence_ids = _loads_list(str(row.get("source_evidence_ids") or "[]")) + _loads_list(str(row.get("target_evidence_ids") or "[]"))
        paper_ids = [str(row.get("source_paper_id") or ""), str(row.get("target_paper_id") or "")]
        await knowledge_assets.create_card(
            {
                "card_type": "claim",
                "title": f"Cross-paper synthesis: {row.get('relation_type') or 'relation'}",
                "content": content,
                "paper_id": paper_ids[0],
                "confidence": min(0.95, max(0.55, float(row.get("confidence") or 0.0))),
                "status": "verified",
                "created_by": "ai",
                "normalized_key": normalized_key,
                "tags": f"research-construction,{relation_id},{row.get('relation_type') or ''}",
                "asset_level": "synthesis",
                "synthesis_type": str(row.get("relation_type") or ""),
                "action_type": "idea",
                "why_useful": "Summarizes a relation cluster for research construction and idea generation.",
                "use_case": "idea",
                "next_action": "Review comparability and decide whether this relation should motivate a research idea.",
                "expected_output": "A traceable cross-paper synthesis card.",
                "risk_or_caveat": "Generated from local evidence and should be reviewed before final writing.",
                "supporting_paper_ids": [pid for pid in paper_ids if pid],
                "evidence_ids": [str(eid) for eid in evidence_ids if eid],
                "evidence_strength": "multi-paper",
                "allow_untraceable": True,
            }
        )
        created += 1
    return {"rule_synthesis_cards": int(base.get("synthesis_cards", 0)), "llm_synthesis_cards": created}


async def _relation_synthesis_content(row: dict[str, Any]) -> str:
    relation = str(row.get("relation_type") or "")
    source = str(row.get("source_title") or row.get("source_paper_id") or "")
    target = str(row.get("target_title") or row.get("target_paper_id") or "")
    positives = _loads_list(str(row.get("positive_checks") or "[]"))
    negatives = _loads_list(str(row.get("negative_checks") or "[]"))
    comparability = _loads_dict(str(row.get("comparability_json") or "{}"))
    runtime = get_llm_runtime_config()
    if runtime.base_url and runtime.api_key and runtime.default_thinking_model:
        payload = {
            "relation_type": relation,
            "source_paper": source,
            "target_paper": target,
            "positive_checks": positives,
            "negative_checks": negatives,
            "comparability": comparability,
        }
        try:
            return await get_llm_service().chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Write one concise cross-paper synthesis in Chinese. "
                            "Use only the provided relation checks. Mention agreement/conflict and comparability caveat."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.0,
            )
        except Exception as exc:
            logger.debug("LLM synthesis skipped: %s", exc)
    return (
        f"{source} 与 {target} 存在 {relation} 关系。"
        f"支持信号：{'; '.join(str(item) for item in positives[:4]) or '暂无'}。"
        f"限制或待核验点：{'; '.join(str(item) for item in negatives[:4]) or '暂无'}。"
    )


async def _profile_topic_weights() -> dict[str, float]:
    """Load the global research-profile topic weights (module C consumer).

    Lets idea construction rank candidate seeds toward the user's accumulated
    interests and accepted/rejected ideas. Empty when no profile exists yet, so
    ranking falls back to the evidence/novelty order.
    """
    row = await db.fetch_one("SELECT topic_weights_json FROM research_profile WHERE profile_id = 'global'")
    if not row:
        return {}
    weights = _loads_dict(str(row.get("topic_weights_json") or "{}"))
    out: dict[str, float] = {}
    for term, weight in weights.items():
        key = re.sub(r"\s+", " ", str(term or "").strip().lower())
        if not key:
            continue
        try:
            out[key] = float(weight)
        except (TypeError, ValueError):
            out[key] = 1.0
    return out


def _profile_boost(text: str, weights: dict[str, float]) -> float:
    if not weights:
        return 0.0
    haystack = str(text or "").lower()
    if not haystack:
        return 0.0
    max_weight = max(weights.values()) or 1.0
    total = 0.0
    for term, weight in weights.items():
        if term and term in haystack:
            total += float(weight) / max_weight
    return round(total, 4)


_IDEA_TYPE_TITLE_PREFIXES = (
    ("resolve limitation", "limitation"),
    ("evaluate method transfer", "transfer"),
    ("corpus evidence audit", "audit"),
)


def _gap_idea_type(row: dict[str, Any]) -> str:
    """Derive an idea/template type from a gap row (no schema column needed).

    Mirrors the generators in research_discovery._build_gap_rows: title prefixes
    and history events identify whether a seed came from a limitation, a method
    transfer relation, or a corpus audit. Lets feedback be aggregated per type.
    """
    title = str(row.get("title") or "").strip().lower()
    for prefix, idea_type in _IDEA_TYPE_TITLE_PREFIXES:
        if title.startswith(prefix):
            return idea_type
    for entry in _loads_list(str(row.get("history_json") or "[]")):
        event = str(entry.get("event") or "") if isinstance(entry, dict) else ""
        if "from_limitation" in event:
            return "limitation"
        if "from_relation" in event:
            return "transfer"
        if "from_corpus_audit" in event:
            return "audit"
    return "other"


async def idea_type_weights() -> dict[str, float]:
    """Per-idea-type feedback multipliers (module C+ consumer).

    Aggregates idea feedback by template type so chronically rejected templates
    (e.g. corpus audit) get down-weighted in the next idea-construction round and
    accepted ones get a small boost. All weights are 1.0 (or absent) when there
    is no feedback, so ranking is unaffected until the user actually reacts.
    """
    rows = await db.fetch_all(
        """
        SELECT g.title, g.history_json, f.verdict
          FROM idea_feedback f
          JOIN research_gaps g ON g.gap_id = f.item_id
         WHERE f.item_type = 'gap'
        """
    )
    totals: dict[str, int] = {}
    accepts: dict[str, int] = {}
    rejects: dict[str, int] = {}
    for row in rows:
        idea_type = _gap_idea_type(row)
        verdict = str(row.get("verdict") or "")
        totals[idea_type] = totals.get(idea_type, 0) + 1
        if verdict in {"accepted", "up"}:
            accepts[idea_type] = accepts.get(idea_type, 0) + 1
        elif verdict in {"rejected", "down"}:
            rejects[idea_type] = rejects.get(idea_type, 0) + 1
    weights: dict[str, float] = {}
    for idea_type, total in totals.items():
        if total <= 0:
            continue
        accept_rate = accepts.get(idea_type, 0) / total
        reject_rate = rejects.get(idea_type, 0) / total
        weight = 1.0 + 0.15 * accept_rate - 0.25 * reject_rate
        weights[idea_type] = round(max(0.5, min(1.3, weight)), 4)
    return weights


async def build_ideas(job_id: str, *, limit: int) -> dict[str, int]:
    pool_size = max(int(limit), int(limit) * 3, 12)
    rows = await db.fetch_all(
        """
        SELECT *
          FROM research_gaps
         WHERE status NOT IN ('rejected', 'covered')
         ORDER BY
            CASE status WHEN 'candidate' THEN 0 WHEN 'needs_more_evidence' THEN 1 ELSE 2 END,
            evidence_strength DESC,
            novelty_score DESC,
            updated_at DESC
         LIMIT ?
        """,
        (pool_size,),
    )
    # Profile-weighted seed ranking: among the strongest evidence/novelty
    # candidates, prefer those matching the user's research profile and idea
    # types they have accepted. The base 1.0 keeps per-type weighting effective
    # even without a profile; stable sort preserves evidence order on ties, so
    # an empty profile and no feedback together are a no-op.
    profile_weights = await _profile_topic_weights()
    type_weights = await idea_type_weights()
    if (profile_weights or type_weights) and len(rows) > int(limit):
        rows = sorted(
            rows,
            key=lambda row: (
                1.0
                + _profile_boost(
                    " ".join(
                        str(row.get(key) or "")
                        for key in ("title", "hypothesis", "research_question", "target_task", "contribution")
                    ),
                    profile_weights,
                )
            )
            * type_weights.get(_gap_idea_type(row), 1.0),
            reverse=True,
        )
    rows = rows[: max(1, int(limit))]
    scored = 0
    promoted = 0
    snippets = 0
    for row in rows:
        support_ids = [str(item) for item in _loads_list(str(row.get("support_evidence_ids") or "[]")) if item]
        fingerprint = _hash(["idea", str(row.get("gap_id") or ""), ",".join(sorted(support_ids))])
        if str(row.get("source_fingerprint") or "") == fingerprint and str(row.get("scored_by") or "") == "llm":
            continue
        idea = await _score_gap_with_llm(row)
        await _update_gap_idea(row, idea, job_id=job_id, fingerprint=fingerprint)
        scored += 1
        if idea.get("decision") == "promote":
            promoted += 1
            await _novelty_check(row, idea)
            await _critique_idea(row, idea)
            await _create_idea_brief(row, idea)
            snippets += 1
    await _dedupe_idea_lineage()
    return {"scored": scored, "promoted": promoted, "idea_briefs": snippets}


async def _score_gap_with_llm(row: dict[str, Any]) -> dict[str, Any]:
    runtime = get_llm_runtime_config()
    fallback = {
        "title": str(row.get("title") or ""),
        "research_question": str(row.get("research_question") or row.get("hypothesis") or ""),
        "hypothesis": str(row.get("hypothesis") or ""),
        "contribution": str(row.get("contribution") or ""),
        "rationale": "Heuristic construction: LLM is not configured or failed.",
        "novelty_score": float(row.get("novelty_score") or 0.0),
        "feasibility_score": float(row.get("feasibility_score") or 0.0),
        "risk_score": float(row.get("risk_score") or 0.0),
        "novelty_basis": str(row.get("novelty_basis") or "local evidence only"),
        "decision": "promote" if float(row.get("novelty_score") or 0.0) >= 0.65 and float(row.get("risk_score") or 0.0) <= 0.65 else "needs_more_evidence",
        "model": "",
    }
    if not runtime.base_url or not runtime.api_key or not runtime.default_thinking_model:
        return fallback
    evidence_rows = await _evidence_for_gap(row)
    payload = {
        "gap": {
            "title": row.get("title"),
            "hypothesis": row.get("hypothesis"),
            "description": row.get("description"),
            "research_question": row.get("research_question"),
            "target_task": row.get("target_task"),
            "baseline_plan": row.get("baseline_plan"),
            "contribution": row.get("contribution"),
        },
        "evidence": evidence_rows,
    }
    try:
        raw = await get_llm_service().chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Evaluate a research idea seed from local paper evidence. Return strict JSON with keys: "
                        "title, research_question, hypothesis, contribution, rationale, novelty_score, "
                        "feasibility_score, risk_score, novelty_basis, decision. "
                        "decision must be promote, needs_more_evidence, or reject. Do not require experiments."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.0,
        )
        data = json.loads(raw)
        if not isinstance(data, dict):
            return fallback
        data["model"] = runtime.default_thinking_model
        decision = str(data.get("decision") or "").strip()
        if decision not in {"promote", "needs_more_evidence", "reject"}:
            data["decision"] = fallback["decision"]
        return {**fallback, **data}
    except Exception as exc:
        logger.debug("gap LLM scoring skipped gap=%s: %s", row.get("gap_id"), exc)
        return fallback


async def _evidence_for_gap(row: dict[str, Any]) -> list[dict[str, Any]]:
    ids = [str(item) for item in _loads_list(str(row.get("support_evidence_ids") or "[]")) if item]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = await db.fetch_all(
        f"""
        SELECT rei.evidence_id, rei.evidence_type, rei.paper_id, COALESCE(p.title, '') AS paper_title,
               rei.normalized_label, rei.quote, rei.page
          FROM research_evidence_items rei
          LEFT JOIN papers p ON p.paper_id = rei.paper_id
         WHERE rei.evidence_id IN ({placeholders})
        """,
        tuple(ids),
    )
    return rows


async def _update_gap_idea(row: dict[str, Any], idea: dict[str, Any], *, job_id: str, fingerprint: str) -> None:
    status = "promoted_to_idea" if idea.get("decision") == "promote" else "needs_more_evidence"
    if idea.get("decision") == "reject":
        status = "rejected"
    history = _loads_list(str(row.get("history_json") or "[]"))
    history.append({"event": "research_construction_scored", "job_id": job_id, "decision": idea.get("decision"), "at": _now()})
    await db.execute(
        """
        UPDATE research_gaps
           SET title = CASE WHEN ? != '' THEN ? ELSE title END,
               research_question = CASE WHEN ? != '' THEN ? ELSE research_question END,
               hypothesis = CASE WHEN ? != '' THEN ? ELSE hypothesis END,
               contribution = CASE WHEN ? != '' THEN ? ELSE contribution END,
               novelty_score = ?,
               feasibility_score = ?,
               risk_score = ?,
               status = ?,
               llm_model = ?,
               llm_rationale = ?,
               novelty_basis = ?,
               construction_batch_id = ?,
               source_fingerprint = ?,
               scored_by = ?,
               history_json = ?,
               updated_at = datetime('now')
         WHERE gap_id = ?
        """,
        (
            str(idea.get("title") or ""),
            str(idea.get("title") or "")[:240],
            str(idea.get("research_question") or ""),
            str(idea.get("research_question") or "")[:1000],
            str(idea.get("hypothesis") or ""),
            str(idea.get("hypothesis") or "")[:2000],
            str(idea.get("contribution") or ""),
            str(idea.get("contribution") or "")[:1000],
            max(0.0, min(1.0, float(idea.get("novelty_score") or 0.0))),
            max(0.0, min(1.0, float(idea.get("feasibility_score") or 0.0))),
            max(0.0, min(1.0, float(idea.get("risk_score") or 0.0))),
            status,
            str(idea.get("model") or ""),
            str(idea.get("rationale") or "")[:2000],
            str(idea.get("novelty_basis") or "")[:1000],
            job_id,
            fingerprint,
            "llm" if idea.get("model") else "heuristic",
            _json(history[-80:]),
            str(row.get("gap_id") or ""),
        ),
    )


async def _novelty_check(row: dict[str, Any], idea: dict[str, Any]) -> None:
    settings = get_settings()
    runtime = get_llm_runtime_config()
    if int(settings.research_construction_novelty_check_limit or 0) <= 0:
        return
    if not (runtime.base_url and runtime.api_key and runtime.default_thinking_model):
        await db.execute(
            """
            UPDATE research_gaps
               SET novelty_evidence_json = ?,
                   updated_at = datetime('now')
             WHERE gap_id = ?
            """,
            (
                _json({"skipped": True, "reason": "llm_not_configured"}),
                str(row.get("gap_id") or ""),
            ),
        )
        return
    query = str(idea.get("title") or row.get("title") or "")[:240]
    if not query:
        return
    evidence: dict[str, Any] = {"query": query, "papers": [], "assessment": ""}
    try:
        ps_settings = PaperSearchSettings.from_env()
        ps_settings = PaperSearchSettings(
            **{
                **ps_settings.__dict__,
                "llm_base_url": runtime.base_url,
                "llm_api_key": runtime.api_key,
                "rank_model": "",
                "embed_model": get_settings().embed_model,
                "final_limit": min(5, int(settings.research_construction_novelty_check_limit or 6)),
                "doi_enrich_enabled": False,
            }
        )
        raw = await search_papers(
            query,
            ["arxiv", "semanticscholar", "openalex"],
            final_limit=min(5, int(settings.research_construction_novelty_check_limit or 6)),
            settings=ps_settings,
        )
        papers = json.loads(raw)
        evidence["papers"] = papers if isinstance(papers, list) else []
    except Exception as exc:
        evidence["error"] = str(exc)[:500]
    if runtime.base_url and runtime.api_key and runtime.default_thinking_model and evidence.get("papers"):
        try:
            evidence["assessment"] = await get_llm_service().chat(
                [
                    {"role": "system", "content": "Assess whether the idea appears already covered by the external abstracts. Return concise Chinese text."},
                    {"role": "user", "content": json.dumps({"idea": idea, "external_papers": evidence["papers"]}, ensure_ascii=False)},
                ],
                temperature=0.0,
            )
        except Exception as exc:
            evidence["assessment_error"] = str(exc)[:500]
    await db.execute(
        """
        UPDATE research_gaps
           SET novelty_evidence_json = ?,
               updated_at = datetime('now')
         WHERE gap_id = ?
        """,
        (_json(evidence), str(row.get("gap_id") or "")),
    )


async def _critique_idea(row: dict[str, Any], idea: dict[str, Any]) -> None:
    settings = get_settings()
    if int(settings.idea_critique_limit or 0) <= 0:
        return
    runtime = get_llm_runtime_config()
    critique: dict[str, Any] = {
        "skeptic_score": round(max(0.0, 1.0 - float(idea.get("risk_score") or 0.0)), 3),
        "notes": "Heuristic critique based on risk score.",
    }
    if runtime.base_url and runtime.api_key and runtime.default_thinking_model:
        try:
            raw = await get_llm_service().chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Act as a skeptical reviewer. Return strict JSON: "
                            "{\"already_done_risk\":\"...\",\"assumption_risk\":\"...\",\"feasibility_risk\":\"...\","
                            "\"skeptic_score\":0.0,\"decision\":\"keep|needs_more_evidence|reject\"}."
                        ),
                    },
                    {"role": "user", "content": json.dumps({"idea": idea}, ensure_ascii=False)},
                ],
                temperature=0.0,
            )
            data = json.loads(raw)
            if isinstance(data, dict):
                critique = data
        except Exception as exc:
            critique["error"] = str(exc)[:500]
    await db.execute(
        """
        UPDATE research_gaps
           SET critique_json = ?,
               updated_at = datetime('now')
         WHERE gap_id = ?
        """,
        (_json(critique), str(row.get("gap_id") or "")),
    )


async def _create_idea_brief(row: dict[str, Any], idea: dict[str, Any]) -> None:
    gap_id = str(row.get("gap_id") or "")
    existing = await db.fetch_one(
        "SELECT snippet_id FROM writing_snippets WHERE section_hint = 'idea_brief' AND paragraph_plan_json LIKE ? LIMIT 1",
        (f"%{gap_id}%",),
    )
    if existing:
        return
    evidence_ids = [str(item) for item in _loads_list(str(row.get("support_evidence_ids") or "[]")) if item]
    evidence_rows = await _evidence_for_gap(row)
    paper_id = str(evidence_rows[0].get("paper_id") or "") if evidence_rows else ""
    quote = str(evidence_rows[0].get("quote") or "") if evidence_rows else ""
    page = int(evidence_rows[0].get("page") or 0) if evidence_rows else 0
    content = "\n\n".join(
        [
            f"# {idea.get('title') or row.get('title') or 'Research idea'}",
            f"问题：{idea.get('research_question') or row.get('research_question') or ''}",
            f"假设：{idea.get('hypothesis') or row.get('hypothesis') or ''}",
            f"预期贡献：{idea.get('contribution') or row.get('contribution') or ''}",
            f"依据：{idea.get('rationale') or row.get('description') or ''}",
            "关键证据：\n" + "\n".join(f"- {item.get('paper_title') or item.get('paper_id')}: {_clean_text(str(item.get('quote') or ''), 280)}" for item in evidence_rows[:5]),
        ]
    ).strip()
    normalized_key = f"construction:idea:{gap_id}"
    card_row = await db.fetch_one(
        "SELECT card_id FROM knowledge_cards WHERE normalized_key = ? AND status != 'rejected' LIMIT 1",
        (normalized_key,),
    )
    source_card_id = str((card_row or {}).get("card_id") or "")
    if not source_card_id:
        card = await knowledge_assets.create_card(
            {
                "card_type": "idea",
                "title": str(idea.get("title") or row.get("title") or "Research idea")[:240],
                "content": str(idea.get("hypothesis") or row.get("hypothesis") or content)[:4000],
                "paper_id": paper_id,
                "source_page": page,
                "source_quote": quote,
                "confidence": max(0.5, min(0.95, float(idea.get("novelty_score") or row.get("novelty_score") or 0.5))),
                "status": "verified",
                "created_by": "ai",
                "normalized_key": normalized_key,
                "tags": f"research-construction,{gap_id},idea",
                "asset_level": "action",
                "action_type": "idea",
                "why_useful": str(idea.get("rationale") or "Research construction promoted this gap into an idea.")[:1000],
                "use_case": "idea",
                "next_action": "Review this idea brief and decide whether it should enter the active research queue.",
                "expected_output": "A traceable idea brief.",
                "risk_or_caveat": str(idea.get("novelty_basis") or "Novelty is estimated from local and optional external evidence.")[:1000],
                "priority": "high",
                "supporting_paper_ids": [paper_id] if paper_id else [],
                "evidence_ids": evidence_ids,
                "evidence_strength": "multi-evidence" if len(evidence_ids) > 1 else "single-evidence",
                "allow_untraceable": True,
            }
        )
        source_card_id = str(card.get("card_id") or "")
    await knowledge_assets.create_snippet(
        {
            "content": content,
            "source_card_id": source_card_id,
            "source_card_ids": [source_card_id] if source_card_id else [],
            "paper_id": paper_id,
            "source_page": page,
            "source_quote": quote,
            "section_hint": "idea_brief",
            "evidence_ids": evidence_ids,
            "paragraph_plan_json": {"gap_id": gap_id, "construction_batch_id": str(row.get("construction_batch_id") or "")},
            "trace_mode": "traceable",
        }
    )


async def _dedupe_idea_lineage() -> None:
    gaps = await db.fetch_all(
        """
        SELECT gap_id, title, hypothesis
          FROM research_gaps
         WHERE status = 'promoted_to_idea'
         ORDER BY updated_at DESC
         LIMIT 100
        """
    )
    if len(gaps) < 2 or not semantic_index.embedding_enabled():
        return
    texts = [f"{row.get('title') or ''}\n{row.get('hypothesis') or ''}" for row in gaps]
    vecs = await semantic_index.embed_texts(texts)
    if len(vecs) != len(gaps):
        return
    for idx, row in enumerate(gaps):
        parent_id = ""
        best = 0.0
        for jdx in range(0, idx):
            score = semantic_index.cosine_similarity(vecs[idx], vecs[jdx])
            if score > best:
                best = score
                parent_id = str(gaps[jdx].get("gap_id") or "")
        if parent_id and best >= 0.9:
            await db.execute(
                "UPDATE research_gaps SET lineage_parent_id = ? WHERE gap_id = ? AND lineage_parent_id = ''",
                (parent_id, str(row.get("gap_id") or "")),
            )


async def rebuild_research_profile(job_id: str) -> dict[str, Any]:
    cards = await db.fetch_all(
        """
        SELECT title, content, card_type, tags
          FROM knowledge_cards
         WHERE status = 'verified'
         ORDER BY updated_at DESC
         LIMIT 120
        """
    )
    gaps = await db.fetch_all(
        """
        SELECT title, hypothesis, status, llm_rationale
          FROM research_gaps
         WHERE status != 'rejected'
         ORDER BY updated_at DESC
         LIMIT 80
        """
    )
    feedback = await db.fetch_all(
        """
        SELECT verdict, reason
          FROM idea_feedback
         ORDER BY created_at DESC
         LIMIT 80
        """
    )
    topic_counter: dict[str, int] = {}
    for row in cards + gaps:
        text = " ".join(str(row.get(key) or "") for key in row)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}|[\u4e00-\u9fff]{2,8}", text.lower()):
            if token in {"the", "and", "with", "paper", "method", "模型", "方法"}:
                continue
            topic_counter[token] = topic_counter.get(token, 0) + 1
    weights = dict(sorted(topic_counter.items(), key=lambda item: item[1], reverse=True)[:30])
    profile_text = "研究兴趣集中在：" + "、".join(list(weights)[:12])
    runtime = get_llm_runtime_config()
    if runtime.base_url and runtime.api_key and runtime.default_thinking_model:
        try:
            profile_text = await get_llm_service().chat(
                [
                    {
                        "role": "system",
                        "content": "Summarize the user's research profile in concise Chinese from cards, ideas, and feedback. Include topic focus and preference signals.",
                    },
                    {
                        "role": "user",
                        "content": json.dumps({"cards": cards[:60], "ideas": gaps[:40], "feedback": feedback}, ensure_ascii=False),
                    },
                ],
                temperature=0.0,
            )
        except Exception as exc:
            logger.debug("LLM research profile skipped: %s", exc)
    source_counts = {
        "cards": len(cards),
        "gaps": len(gaps),
        "idea_feedback": len(feedback),
        "idea_type_weights": await idea_type_weights(),
        "job_id": job_id,
    }
    await db.execute(
        """
        INSERT INTO research_profile (
            profile_id, profile_scope, profile_text, topic_weights_json,
            source_counts_json, built_at, model_version, updated_at
        ) VALUES ('global', 'global', ?, ?, ?, datetime('now'), ?, datetime('now'))
        ON CONFLICT(profile_id) DO UPDATE SET
            profile_text = excluded.profile_text,
            topic_weights_json = excluded.topic_weights_json,
            source_counts_json = excluded.source_counts_json,
            built_at = datetime('now'),
            model_version = excluded.model_version,
            updated_at = datetime('now')
        """,
        (_clean_text(profile_text, 4000), _json(weights), _json(source_counts), runtime.default_thinking_model),
    )
    return {"profile_chars": len(profile_text), "topics": len(weights), "source_counts": source_counts}


async def record_idea_feedback(item_id: str, verdict: str, reason: str = "") -> dict[str, Any]:
    verdict = str(verdict or "").strip()
    if verdict not in {"up", "down", "accepted", "rejected"}:
        raise ValueError("Invalid idea feedback verdict")
    row = await db.fetch_one("SELECT gap_id FROM research_gaps WHERE gap_id = ?", (item_id,))
    if not row:
        raise ValueError("Idea not found")
    feedback_id = _feedback_id(item_id, verdict)
    await db.execute(
        """
        INSERT INTO idea_feedback (feedback_id, item_id, item_type, verdict, reason)
        VALUES (?, ?, 'gap', ?, ?)
        """,
        (feedback_id, item_id, verdict, str(reason or "")[:1000]),
    )
    if verdict in {"accepted", "up"}:
        await db.execute(
            "UPDATE research_gaps SET status = CASE WHEN status = 'rejected' THEN status ELSE 'promoted_to_idea' END, updated_at = datetime('now') WHERE gap_id = ?",
            (item_id,),
        )
    elif verdict == "rejected":
        await db.execute(
            "UPDATE research_gaps SET status = 'rejected', rejection_reason = ?, updated_at = datetime('now') WHERE gap_id = ?",
            (str(reason or "idea feedback rejected")[:1000], item_id),
        )
    return {"feedback_id": feedback_id, "item_id": item_id, "verdict": verdict, "reason": reason}
