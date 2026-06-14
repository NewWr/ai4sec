from __future__ import annotations

import datetime as dt
import asyncio
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.config import get_settings
from app.db import database as db
from app.services.arxiv_client import ArxivPaper, search_arxiv, within_lookback
from app.services.daily_recommendation_scoring import DEFAULT_TOPICS, score_paper
from app.services.http_clients import get_default_http_client
from app.services.knowledge_spaces import DAILY_SOURCE_SPACE_ID, add_item_to_space
from app.services.llm_runtime_config import get_llm_runtime_config
from app.services.llm_service import get_llm_service
from app.services.paper_collections import assign_paper_to_collection, ensure_default_collection
from app.services.recommendation_behavior import build_behavior_terms, build_profile_terms, match_research_gaps_for_paper
from app.services.translation_cache import translate_text

logger = logging.getLogger("scholar.daily")

VALID_STATUSES = {"candidate", "interested", "irrelevant", "dismissed", "ingesting", "ingested", "ingest_failed"}
VALID_FEEDBACK = {"interested", "irrelevant", "dismissed"}
LEGACY_DEFAULT_TOPIC_IDS = {
    "ai_security",
    "vision_language_models",
    "prompt_learning_vlm",
    "medical_clip_prompt_learning",
    "medical_sam_segmentation",
    "medical_dino_self_supervised",
}


def today_str() -> str:
    return dt.date.today().isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str, default: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except Exception:
        return default
    return parsed if parsed is not None else default


def _topic_id(raw: dict[str, Any]) -> str:
    return str(raw.get("topic_id") or raw.get("id") or "").strip()


async def ensure_default_topics() -> None:
    current_ids: set[str] = set()
    for idx, topic in enumerate(DEFAULT_TOPICS):
        topic_id = _topic_id(topic)
        if not topic_id:
            continue
        current_ids.add(topic_id)
        await db.execute(
            """
            INSERT INTO daily_recommendation_topics (
                topic_id, name, name_zh, config_json, enabled, sort_order, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, datetime('now'))
            ON CONFLICT(topic_id) DO UPDATE SET
                name = excluded.name,
                name_zh = excluded.name_zh,
                config_json = excluded.config_json,
                sort_order = excluded.sort_order,
                updated_at = datetime('now')
            """,
            (
                topic_id,
                str(topic.get("name") or topic_id),
                str(topic.get("name_zh") or ""),
                _json_dumps(topic),
                int(topic.get("sort_order") or (idx + 1) * 10),
            ),
        )
    stale_legacy_ids = sorted(LEGACY_DEFAULT_TOPIC_IDS - current_ids)
    if stale_legacy_ids:
        placeholders = ", ".join("?" for _ in stale_legacy_ids)
        await db.execute(
            f"""
            UPDATE daily_recommendation_topics
               SET enabled = 0, updated_at = datetime('now')
             WHERE topic_id IN ({placeholders})
            """,
            tuple(stale_legacy_ids),
        )


async def list_topics() -> list[dict[str, Any]]:
    await ensure_default_topics()
    rows = await db.fetch_all(
        """
        SELECT * FROM daily_recommendation_topics
         WHERE enabled = 1
         ORDER BY sort_order ASC, name ASC
        """
    )
    topics: list[dict[str, Any]] = []
    for row in rows:
        config = _json_loads(str(row.get("config_json") or "{}"), {})
        topics.append(
            {
                "topic_id": str(row.get("topic_id") or ""),
                "name": str(row.get("name") or ""),
                "name_zh": str(row.get("name_zh") or ""),
                "enabled": bool(row.get("enabled") or 0),
                "sort_order": int(row.get("sort_order") or 0),
                "config": config if isinstance(config, dict) else {},
            }
        )
    return topics


def _item_id(arxiv_id: str, topic_id: str, fetched_date: str) -> str:
    raw = f"{arxiv_id}:{topic_id}:{fetched_date}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


async def _feedback_penalty(arxiv_id: str, topic_id: str, title: str) -> float:
    del title
    row = await db.fetch_one(
        """
        SELECT action, COUNT(*) AS n
          FROM daily_recommendation_feedback
         WHERE topic_id = ? AND arxiv_id = ?
         GROUP BY action
        """,
        (topic_id, arxiv_id),
    )
    if not row:
        return 0.0
    action = str(row.get("action") or "")
    n = int(row.get("n") or 0)
    if action == "irrelevant":
        return -0.4 * max(1, n)
    if action == "dismissed":
        return -0.15 * max(1, n)
    if action == "interested":
        return 0.1
    return 0.0


async def _translate_candidate(paper: ArxivPaper) -> tuple[str, str, str, str]:
    settings = get_settings()
    if not settings.daily_recommendation_translate_enabled:
        return paper.title, paper.abstract, "skipped", "skipped"
    target = settings.daily_recommendation_translate_target or "zh"
    title_res, abstract_res = await asyncio.gather(
        translate_text(
            paper.title,
            source_lang="en",
            target_lang=target,
            provider="deeplx",
        ),
        translate_text(
            paper.abstract,
            source_lang="en",
            target_lang=target,
            provider="deeplx",
        ),
    )
    return title_res.translated_text, abstract_res.translated_text, title_res.status, abstract_res.status


async def _llm_profile_rerank(fetched_date: str, *, limit: int) -> int:
    """Optional LLM re-rank of the day's top candidates against the research profile.

    Lights up the dormant ``DAILY_RECOMMENDATION_LLM_REVIEW_*`` flags: when
    enabled and a global research profile exists, the top-N kept candidates are
    re-scored by one batched LLM call for fit to the profile, nudging their score
    and recording the verdict in ``llm_review_json``. Disabled by default, so it
    costs no tokens unless the operator turns it on; any failure leaves the rule
    scores untouched.
    """
    runtime = get_llm_runtime_config()
    if not (runtime.base_url and runtime.api_key and runtime.default_thinking_model):
        return 0
    profile_row = await db.fetch_one(
        "SELECT profile_text FROM research_profile WHERE profile_id = 'global'"
    )
    profile_text = str((profile_row or {}).get("profile_text") or "").strip()
    if not profile_text:
        return 0
    rows = await db.fetch_all(
        """
        SELECT item_id, title_en, abstract_en, score
          FROM daily_recommendation_items
         WHERE fetched_date = ? AND status = 'candidate'
         ORDER BY score DESC
         LIMIT ?
        """,
        (fetched_date, max(1, int(limit))),
    )
    if not rows:
        return 0
    old_scores = {str(row.get("item_id") or ""): float(row.get("score") or 0.0) for row in rows}
    payload = {
        "profile": profile_text[:2000],
        "candidates": [
            {
                "item_id": str(row.get("item_id") or ""),
                "title": str(row.get("title_en") or ""),
                "abstract": str(row.get("abstract_en") or "")[:600],
            }
            for row in rows
        ],
    }
    try:
        raw = await get_llm_service().chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Re-rank daily paper candidates by fit to the researcher's profile. "
                        "Return strict JSON: {\"items\":[{\"item_id\":\"...\",\"fit\":0.0,\"reason\":\"...\"}]} "
                        "with fit in [0,1]. Judge only from the profile and the provided title/abstract."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.0,
        )
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("Daily LLM profile rerank failed: %s", exc)
        return 0
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return 0
    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id") or "")
        if not item_id or item_id not in old_scores:
            continue
        try:
            fit = max(0.0, min(1.0, float(item.get("fit") or 0.0)))
        except (TypeError, ValueError):
            continue
        new_score = round(min(1.0, old_scores[item_id] * 0.8 + fit * 0.2), 4)
        await db.execute(
            """
            UPDATE daily_recommendation_items
               SET llm_review_status = 'done',
                   llm_review_json = ?,
                   score = ?
             WHERE item_id = ?
            """,
            (
                json.dumps({"fit": fit, "reason": str(item.get("reason") or "")[:500]}, ensure_ascii=False),
                new_score,
                item_id,
            ),
        )
        updated += 1
    return updated


async def refresh_daily_recommendations(
    *,
    fetched_date: str = "",
    topic_id: str = "",
    force: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.daily_recommendation_enabled:
        return {"date": fetched_date or today_str(), "fetched": 0, "inserted_or_updated": 0, "kept": 0, "skipped": 0, "message": "Daily recommendation is disabled"}

    fetched_date = fetched_date or today_str()
    topics = await list_topics()
    if topic_id:
        topics = [topic for topic in topics if topic["topic_id"] == topic_id]
    fetched = 0
    upserted = 0
    kept = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    translate_semaphore = asyncio.Semaphore(4)
    try:
        behavior_terms = await build_behavior_terms()
    except Exception as exc:
        logger.warning("Daily refresh behavior profile unavailable: %s", exc)
        behavior_terms = []
    try:
        profile_terms = await build_profile_terms()
    except Exception as exc:
        logger.warning("Daily refresh research profile unavailable: %s", exc)
        profile_terms = []

    async def translate_candidate_limited(paper: ArxivPaper) -> tuple[str, str, str, str]:
        async with translate_semaphore:
            return await _translate_candidate(paper)

    for topic_row in topics:
        config = dict(topic_row.get("config") or {})
        config.setdefault("id", topic_row["topic_id"])
        config.setdefault("name", topic_row["name"])
        config.setdefault("name_zh", topic_row["name_zh"])
        try:
            papers = await search_arxiv(
                config,
                max_results=int(settings.daily_recommendation_max_results_per_topic),
            )
        except Exception as exc:
            logger.warning("Daily refresh failed topic=%s: %s", topic_row["topic_id"], exc)
            errors.append(
                {
                    "topic_id": str(topic_row["topic_id"]),
                    "topic": str(topic_row.get("name_zh") or topic_row.get("name") or topic_row["topic_id"]),
                    "error": str(exc)[:500] or exc.__class__.__name__,
                }
            )
            continue
        fetched += len(papers)
        for paper in papers:
            if not paper.arxiv_id:
                skipped += 1
                continue
            if not within_lookback(
                paper,
                fetched_date=fetched_date,
                lookback_days=int(settings.daily_recommendation_lookback_days),
            ):
                skipped += 1
                continue
            existing = await db.fetch_one(
                """
                SELECT item_id, status FROM daily_recommendation_items
                 WHERE arxiv_id = ? AND topic_id = ? AND fetched_date = ?
                """,
                (paper.arxiv_id, topic_row["topic_id"], fetched_date),
            )
            if existing and not force:
                kept += 1
                continue
            penalty = await _feedback_penalty(paper.arxiv_id, topic_row["topic_id"], paper.title)
            score = score_paper(
                title=paper.title,
                abstract=paper.abstract,
                categories=paper.categories,
                primary_category=paper.primary_category,
                topic=config,
                feedback_penalty=penalty,
                behavior_terms=behavior_terms,
                profile_terms=profile_terms,
                default_min_score=float(settings.daily_recommendation_min_score),
            )
            if not score.keep:
                skipped += 1
                continue
            matched_gaps = await match_research_gaps_for_paper(
                paper_key=paper.arxiv_id,
                title=paper.title,
                abstract=paper.abstract,
            )
            score_detail = dict(score.detail)
            reason = score.reason
            if matched_gaps:
                score_detail["matched_gaps"] = matched_gaps
                score_detail["gap_hit_count"] = len(matched_gaps)
                reason = f"{reason}；命中想法 " + ", ".join(
                    str(item.get("title") or item.get("gap_id") or "")[:40]
                    for item in matched_gaps[:2]
                )
            title_zh, abstract_zh, title_status, abstract_status = await translate_candidate_limited(paper)
            item_id = _item_id(paper.arxiv_id, topic_row["topic_id"], fetched_date)
            current_status = str((existing or {}).get("status") or "candidate")
            if current_status not in VALID_STATUSES:
                current_status = "candidate"
            await db.execute(
                """
                INSERT INTO daily_recommendation_items (
                    item_id, arxiv_id, topic_id, title_en, title_zh, abstract_en, abstract_zh,
                    authors_json, primary_category, categories_json, published_at, updated_at,
                    arxiv_url, pdf_url, score, score_detail_json, reason,
                    title_translation_status, abstract_translation_status,
                    llm_review_status, llm_review_json, status, fetched_date, error_msg
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_needed', '{}', ?, ?, '')
                ON CONFLICT(arxiv_id, topic_id, fetched_date) DO UPDATE SET
                    title_en = excluded.title_en,
                    title_zh = excluded.title_zh,
                    abstract_en = excluded.abstract_en,
                    abstract_zh = excluded.abstract_zh,
                    authors_json = excluded.authors_json,
                    primary_category = excluded.primary_category,
                    categories_json = excluded.categories_json,
                    published_at = excluded.published_at,
                    updated_at = excluded.updated_at,
                    arxiv_url = excluded.arxiv_url,
                    pdf_url = excluded.pdf_url,
                    score = excluded.score,
                    score_detail_json = excluded.score_detail_json,
                    reason = excluded.reason,
                    title_translation_status = excluded.title_translation_status,
                    abstract_translation_status = excluded.abstract_translation_status,
                    error_msg = ''
                """,
                (
                    item_id,
                    paper.arxiv_id,
                    topic_row["topic_id"],
                    paper.title,
                    title_zh,
                    paper.abstract,
                    abstract_zh,
                    _json_dumps(paper.authors),
                    paper.primary_category,
                    _json_dumps(paper.categories),
                    paper.published_at,
                    paper.updated_at,
                    paper.arxiv_url,
                    paper.pdf_url,
                    score.score,
                    _json_dumps(score_detail),
                    reason,
                    title_status,
                    abstract_status,
                    current_status,
                    fetched_date,
                ),
            )
            upserted += 1
            kept += 1

    if settings.daily_recommendation_llm_review_enabled:
        try:
            await _llm_profile_rerank(
                fetched_date,
                limit=int(settings.daily_recommendation_llm_review_limit or 20),
            )
        except Exception as exc:
            logger.warning("Daily LLM profile rerank skipped: %s", exc)

    if errors and fetched == 0 and upserted == 0:
        message = "refresh_failed"
    elif errors:
        message = "partial"
    else:
        message = "ok"
    return {
        "date": fetched_date,
        "fetched": fetched,
        "inserted_or_updated": upserted,
        "kept": kept,
        "skipped": skipped,
        "message": message,
        "errors": errors,
    }


def _row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": str(row.get("item_id") or ""),
        "arxiv_id": str(row.get("arxiv_id") or ""),
        "topic_id": str(row.get("topic_id") or ""),
        "title_en": str(row.get("title_en") or ""),
        "title_zh": str(row.get("title_zh") or ""),
        "abstract_en": str(row.get("abstract_en") or ""),
        "abstract_zh": str(row.get("abstract_zh") or ""),
        "authors": _json_loads(str(row.get("authors_json") or "[]"), []),
        "primary_category": str(row.get("primary_category") or ""),
        "categories": _json_loads(str(row.get("categories_json") or "[]"), []),
        "published_at": str(row.get("published_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "arxiv_url": str(row.get("arxiv_url") or ""),
        "pdf_url": str(row.get("pdf_url") or ""),
        "score": float(row.get("score") or 0.0),
        "score_detail": _json_loads(str(row.get("score_detail_json") or "{}"), {}),
        "reason": str(row.get("reason") or ""),
        "title_translation_status": str(row.get("title_translation_status") or "pending"),
        "abstract_translation_status": str(row.get("abstract_translation_status") or "pending"),
        "llm_review_status": str(row.get("llm_review_status") or "not_needed"),
        "status": str(row.get("status") or "candidate"),
        "linked_paper_id": str(row.get("linked_paper_id") or ""),
        "linked_run_id": str(row.get("linked_run_id") or ""),
        "error_msg": str(row.get("error_msg") or ""),
        "fetched_date": str(row.get("fetched_date") or ""),
        "created_at": str(row.get("created_at") or ""),
    }


async def list_items(
    *,
    fetched_date: str = "",
    topic_id: str = "",
    status: str = "",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    topics = await list_topics()
    clauses: list[str] = []
    params: list[Any] = []
    if fetched_date:
        clauses.append("fetched_date = ?")
        params.append(fetched_date)
    if topic_id:
        clauses.append("topic_id = ?")
        params.append(topic_id)
    elif topics:
        topic_ids = [str(topic["topic_id"]) for topic in topics if str(topic.get("topic_id") or "")]
        placeholders = ", ".join("?" for _ in topic_ids)
        clauses.append(f"topic_id IN ({placeholders})")
        params.extend(topic_ids)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(int(limit or 20), 500))
    safe_offset = max(0, int(offset or 0))
    total_row = await db.fetch_one(
        f"""
        SELECT COUNT(*) AS total
          FROM daily_recommendation_items
         {where_sql}
        """,
        tuple(params),
    )
    total = int((total_row or {}).get("total") or 0)
    rows = await db.fetch_all(
        f"""
        SELECT *
          FROM daily_recommendation_items
         {where_sql}
         ORDER BY fetched_date DESC, score DESC, updated_at DESC, published_at DESC, created_at DESC
         LIMIT ? OFFSET ?
        """,
        tuple(params + [safe_limit, safe_offset]),
    )
    return {
        "date": fetched_date,
        "topics": topics,
        "items": [_row_to_item(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "has_more": safe_offset + len(rows) < total,
    }


async def update_feedback(item_id: str, *, action: str, note: str = "") -> dict[str, Any]:
    action = (action or "").strip()
    if action not in VALID_FEEDBACK:
        raise ValueError("Invalid feedback action")
    row = await db.fetch_one("SELECT * FROM daily_recommendation_items WHERE item_id = ?", (item_id,))
    if not row:
        raise KeyError("Daily recommendation item not found")
    feedback_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO daily_recommendation_feedback (
            feedback_id, item_id, arxiv_id, topic_id, action, note
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            feedback_id,
            item_id,
            str(row.get("arxiv_id") or ""),
            str(row.get("topic_id") or ""),
            action,
            (note or "").strip()[:1000],
        ),
    )
    await db.execute(
        "UPDATE daily_recommendation_items SET status = ?, error_msg = '' WHERE item_id = ?",
        (action, item_id),
    )
    updated = await db.fetch_one("SELECT * FROM daily_recommendation_items WHERE item_id = ?", (item_id,))
    if not updated:
        raise KeyError("Daily recommendation item not found")
    return _row_to_item(updated)


async def _download_pdf(url: str, dest_path: Path) -> None:
    if not url:
        raise ValueError("PDF URL is empty")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.hostname not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        raise ValueError("Only arXiv PDF URLs are allowed")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(".pdf.part")
    client = get_default_http_client()
    async with client.stream("GET", url, follow_redirects=True, timeout=90.0) as resp:
        resp.raise_for_status()
        first = b""
        with open(tmp_path, "wb") as out:
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                if not first:
                    first = chunk[:2048]
                out.write(chunk)
    if not first.lstrip().startswith(b"%PDF"):
        tmp_path.unlink(missing_ok=True)
        raise ValueError("Downloaded file is not a PDF")
    os.replace(tmp_path, dest_path)


async def ingest_item(
    item_id: str,
    *,
    collection_id: str = "",
    source_space_id: str = DAILY_SOURCE_SPACE_ID,
) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM daily_recommendation_items WHERE item_id = ?", (item_id,))
    if not row:
        raise KeyError("Daily recommendation item not found")
    linked = str(row.get("linked_paper_id") or "")
    if linked:
        return {"item_id": item_id, "paper_id": linked, "run_id": str(row.get("linked_run_id") or ""), "status": "ingested", "message": "Already ingested"}

    await db.execute(
        "UPDATE daily_recommendation_items SET status = 'ingesting', error_msg = '' WHERE item_id = ?",
        (item_id,),
    )
    settings = get_settings()
    title = str(row.get("title_en") or "")
    arxiv_id = str(row.get("arxiv_id") or "")
    pdf_url = str(row.get("pdf_url") or "")
    try:
        tmp_dir = settings.data_dir / "daily-downloads"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"{item_id}.pdf"
        await _download_pdf(pdf_url, tmp_path)
        data = tmp_path.read_bytes()
        digest = hashlib.sha1(data).hexdigest()
        paper_dir = settings.data_dir / "papers" / digest
        paper_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = paper_dir / "original.pdf"
        if not pdf_path.exists():
            os.replace(tmp_path, pdf_path)
        else:
            tmp_path.unlink(missing_ok=True)
        rel_path = f"papers/{digest}/original.pdf"
        existing = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (digest,))
        if not existing:
            await db.execute(
                """
                INSERT INTO papers (
                    paper_id, file_path, original_filename, title, reading_status,
                    priority, decision
                ) VALUES (?, ?, ?, ?, 'unread', 'medium', '')
                """,
                (digest, rel_path, f"arxiv-{arxiv_id}.pdf", title),
            )
            await db.execute(
                """
                INSERT INTO paper_display_cache (
                    paper_id, title_zh, summary_source, summary_en, summary_zh,
                    source_hash, translation_status, updated_at
                ) VALUES (?, ?, 'daily_arxiv', ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(paper_id) DO UPDATE SET
                    title_zh = excluded.title_zh,
                    summary_en = excluded.summary_en,
                    summary_zh = excluded.summary_zh,
                    translation_status = excluded.translation_status,
                    updated_at = datetime('now')
                """,
                (
                    digest,
                    str(row.get("title_zh") or ""),
                    str(row.get("abstract_en") or ""),
                    str(row.get("abstract_zh") or ""),
                    hashlib.sha1(str(row.get("abstract_en") or "").encode("utf-8")).hexdigest(),
                    str(row.get("abstract_translation_status") or "pending"),
                ),
            )
        await ensure_default_collection()
        await assign_paper_to_collection(
            paper_id=digest,
            collection_id=collection_id or "unclassified",
            is_primary=True,
            note=f"Imported from daily arXiv recommendation {arxiv_id}".strip(),
        )
        await add_item_to_space(
            space_id=source_space_id or DAILY_SOURCE_SPACE_ID,
            item_kind="paper",
            item_id=digest,
            paper_id=digest,
            source_type="daily",
            sync_status="pending",
            note=f"Imported from daily arXiv recommendation {arxiv_id}".strip(),
        )
        await db.execute(
            """
            UPDATE daily_recommendation_items
               SET status = 'ingested',
                   linked_paper_id = ?,
                   error_msg = ''
             WHERE item_id = ?
            """,
            (digest, item_id),
        )
        return {"item_id": item_id, "paper_id": digest, "run_id": "", "status": "ingested", "message": "Ingested"}
    except Exception as exc:
        logger.warning("Daily ingest failed item=%s: %s", item_id, exc)
        await db.execute(
            "UPDATE daily_recommendation_items SET status = 'ingest_failed', error_msg = ? WHERE item_id = ?",
            (str(exc)[:1000], item_id),
        )
        raise
