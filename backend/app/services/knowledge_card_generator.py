from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.db import database as db
from app.services import knowledge_assets as assets
from app.services.llm_service import get_llm_service

logger = logging.getLogger("scholar.knowledge_cards")

EXTRACTOR_VERSION = "auto_card_v1"
FACT_CARD_TYPES = {"claim", "method", "dataset", "metric", "result", "limitation"}
CARD_TYPES = {"claim", "method", "dataset", "metric", "result", "limitation", "question", "idea"}
_FENCE_RE = re.compile(r"^```\w*\n?|\n?```$", re.MULTILINE)


_SYSTEM_PROMPT = """You extract long-term research knowledge cards from an academic-paper analysis.
Return ONLY a JSON array. Do not include markdown fences or commentary.

Each item must follow this schema:
{
  "card_type": "claim|method|dataset|metric|result|limitation|question|idea",
  "title": "short reusable title",
  "content": "one reusable research-knowledge statement",
  "source_page": 3,
  "source_quote": "exact quote copied from the provided context",
  "confidence": 0.82,
  "tags": ["short-tag"],
  "source_ref": "evidence:E01",
  "why_useful": "why this matters for future research work",
  "use_case": "writing|experiment|idea|review|implementation|reading",
  "next_action": "one concrete next action a researcher can take",
  "risk_or_caveat": "boundary condition or caveat for using this knowledge"
}

Rules:
- Return at most MAX_CARDS_PLACEHOLDER cards.
- Prefer high-value cards useful for later literature review, method design, experiments, or writing.
- Factual card types (claim, method, dataset, metric, result, limitation) MUST include a source_quote copied from the context.
- Every card MUST explain its research utility through why_useful, use_case, next_action, and risk_or_caveat.
- next_action must be executable, e.g. "use as related-work contrast", "turn into an ablation", "check as baseline", or "add as limitation evidence".
- Skip generic summary sentences and low-value wording.
- Do not invent page numbers, metrics, datasets, methods, or quotes.
"""


@dataclass
class SourceMatch:
    ok: bool
    page: int = 0
    flags: list[str] | None = None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    return text


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("-\n", "").replace("\n", " ")).strip().lower()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _as_tags(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


async def generate_cards_for_run(
    run_id: str,
    *,
    paper_id: str = "",
    model: str = "",
    force: bool = False,
    max_cards: int = 12,
    trigger_source: str = "manual",
) -> dict[str, Any]:
    settings = get_settings()
    prompt_version = settings.auto_knowledge_card_prompt_version or "kg_card_v1"
    max_cards = max(1, min(max_cards or settings.auto_knowledge_card_max_per_run, 30))

    run = None
    output = None
    if run_id:
        run = await db.fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if not run:
            raise ValueError("Run not found")
        paper_id = paper_id or str(run.get("paper_id") or "")
        output = await db.fetch_one("SELECT * FROM run_outputs WHERE run_id = ?", (run_id,))
    if not paper_id:
        raise ValueError("paper_id is required when run_id is empty")
    await assets.ensure_paper(paper_id)

    context = await _build_context(paper_id, output)
    source_hash = hashlib.sha256(context.encode("utf-8")).hexdigest()
    llm_model = model or settings.auto_knowledge_card_model or str((run or {}).get("llm_model") or "")

    existing = await _existing_generation(run_id, paper_id, source_hash, prompt_version)
    if existing and not force:
        existing["card_ids"] = await _card_ids_for_generation(run_id, prompt_version)
        return existing

    generation_id = _new_id("kg")
    await _insert_generation(
        generation_id,
        paper_id=paper_id,
        run_id=run_id,
        status="running",
        trigger_source=trigger_source,
        llm_model=llm_model,
        prompt_version=prompt_version,
        source_hash=source_hash,
    )

    if not context.strip():
        await _finish_generation(generation_id, status="failed", error_msg="No source context for card generation")
        return await _get_generation(generation_id)

    try:
        raw = await get_llm_service().chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT.replace("MAX_CARDS_PLACEHOLDER", str(max_cards))},
                {"role": "user", "content": context},
            ],
            model=llm_model,
            temperature=0.0,
        )
        candidates = _parse_candidates(raw)
        source_rows = await _source_rows(paper_id, output)
        card_ids: list[str] = []
        skipped = 0
        duplicates = 0

        for candidate in candidates[:max_cards]:
            card = _coerce_candidate(candidate, paper_id, run_id, prompt_version)
            if not card:
                skipped += 1
                continue
            match = validate_card_source(card, source_rows)
            flags = list(card.get("quality_flags") or [])
            if match.flags:
                flags.extend(match.flags)
            if card["card_type"] in FACT_CARD_TYPES and not match.ok:
                skipped += 1
                continue
            if match.page:
                card["source_page"] = match.page
            card["quality_flags"] = sorted(set(flags))
            if not card["normalized_key"]:
                card["normalized_key"] = assets.normalize_card_key(
                    card["card_type"],
                    paper_id,
                    card["title"],
                    card["content"],
                    card["source_quote"],
                )
            duplicate = await _is_duplicate(card)
            if duplicate:
                duplicates += 1
                skipped += 1
                continue
            created = await assets.create_card(card)
            card_ids.append(str(created.get("card_id") or ""))

        await _finish_generation(
            generation_id,
            status="done",
            raw_output_json=json.dumps(candidates, ensure_ascii=False),
            cards_created=len(card_ids),
            cards_skipped=skipped,
            duplicate_count=duplicates,
        )
        result = await _get_generation(generation_id)
        result["card_ids"] = card_ids
        logger.info("[%s] generated %d AI knowledge cards for run=%s", paper_id, len(card_ids), run_id or "-")
        return result
    except Exception as exc:
        logger.warning("[%s] knowledge-card generation failed run=%s: %s", paper_id, run_id or "-", exc)
        await _finish_generation(generation_id, status="failed", error_msg=str(exc)[:1000])
        return await _get_generation(generation_id)


async def generate_cards_from_state(state: dict[str, Any], *, trigger_source: str = "run_completed") -> dict[str, Any]:
    settings = get_settings()
    if not settings.auto_knowledge_cards_enabled:
        return {"status": "skipped", "error_msg": "AUTO_KNOWLEDGE_CARDS_ENABLED=false"}
    mode = str(state.get("mode") or "")
    if mode not in {"snap", "lens"}:
        return {"status": "skipped", "error_msg": f"mode {mode or '-'} is not enabled for automatic cards"}
    run_id = str(state.get("run_id") or "")
    paper_id = str(state.get("paper_id") or "")
    output = await db.fetch_one("SELECT * FROM run_outputs WHERE run_id = ?", (run_id,)) if run_id else None
    if not output and run_id:
        await db.execute(
            "INSERT OR REPLACE INTO run_outputs (run_id, markdown, json_data) VALUES (?, ?, ?)",
            (run_id, str(state.get("final_markdown") or ""), str(state.get("final_json") or "{}")),
        )
    return await generate_cards_for_run(
        run_id,
        paper_id=paper_id,
        model=str(state.get("llm_model") or ""),
        force=False,
        max_cards=settings.auto_knowledge_card_max_per_run,
        trigger_source=trigger_source,
    )


def validate_card_source(card: dict[str, Any], source_rows: list[dict[str, Any]]) -> SourceMatch:
    quote = str(card.get("source_quote") or "").strip()
    if not quote:
        if str(card.get("card_type") or "") in FACT_CARD_TYPES:
            return SourceMatch(False, flags=["missing_quote"])
        return SourceMatch(True)
    quote_norm = _norm_text(quote)
    for row in source_rows:
        text_norm = _norm_text(str(row.get("text") or ""))
        if quote_norm and quote_norm in text_norm:
            page = _safe_int(row.get("page"), _safe_int(card.get("source_page")))
            flags: list[str] = []
            if page and page != _safe_int(card.get("source_page")):
                flags.append("page_corrected")
            return SourceMatch(True, page=page, flags=flags)
    compact_quote = re.sub(r"\W+", "", quote_norm)
    for row in source_rows:
        compact_text = re.sub(r"\W+", "", _norm_text(str(row.get("text") or "")))
        if compact_quote and compact_quote in compact_text:
            return SourceMatch(True, page=_safe_int(row.get("page")), flags=["quote_fuzzy_matched"])
    return SourceMatch(False, flags=["quote_not_found"])


async def _build_context(paper_id: str, output: dict[str, Any] | None) -> str:
    parts: list[str] = []
    paper = await db.fetch_one("SELECT title FROM papers WHERE paper_id = ?", (paper_id,))
    if paper and paper.get("title"):
        parts.append(f"Paper title: {paper['title']}")
    final_json = {}
    markdown = ""
    if output:
        markdown = str(output.get("markdown") or "")
        try:
            final_json = json.loads(str(output.get("json_data") or "{}"))
        except Exception:
            final_json = {}
    evidence_pool = final_json.get("evidence_pool") if isinstance(final_json, dict) else []
    if isinstance(evidence_pool, list) and evidence_pool:
        parts.append("Evidence pool:")
        for item in evidence_pool[:24]:
            if not isinstance(item, dict):
                continue
            page = _safe_int(item.get("page"))
            quote = str(item.get("quote") or "").strip()
            slot = str(item.get("slot") or "").strip()
            eid = str(item.get("id") or "").strip()
            paraphrase = str(item.get("paraphrase") or "").strip()
            if quote:
                parts.append(f"- [{eid or slot or 'evidence'}] [p.{page}] {quote} | {paraphrase}")
    if markdown.strip():
        parts.append("Analysis markdown:")
        parts.append(markdown[:8000])
    block_rows = await db.fetch_all(
        """
        SELECT block_id, page_idx, text, section_path
          FROM blocks
         WHERE paper_id = ? AND text != ''
         ORDER BY page_idx, order_idx
         LIMIT 80
        """,
        (paper_id,),
    )
    if block_rows:
        parts.append("Paper text excerpts:")
        for row in block_rows:
            text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
            if not text:
                continue
            parts.append(f"[block:{row.get('block_id')}] [p.{int(row.get('page_idx') or 0) + 1}] {text[:900]}")
    return "\n\n".join(parts)


async def _source_rows(paper_id: str, output: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if output:
        try:
            final_json = json.loads(str(output.get("json_data") or "{}"))
        except Exception:
            final_json = {}
        evidence_pool = final_json.get("evidence_pool") if isinstance(final_json, dict) else []
        if isinstance(evidence_pool, list):
            for item in evidence_pool:
                if isinstance(item, dict) and item.get("quote"):
                    rows.append({
                        "page": _safe_int(item.get("page")),
                        "text": str(item.get("quote") or ""),
                        "source_ref": f"evidence:{item.get('id') or ''}",
                    })
    block_rows = await db.fetch_all(
        "SELECT block_id, page_idx, text FROM blocks WHERE paper_id = ? AND text != ''",
        (paper_id,),
    )
    for row in block_rows:
        rows.append({
            "page": int(row.get("page_idx") or 0) + 1,
            "text": str(row.get("text") or ""),
            "source_ref": f"block:{row.get('block_id')}",
        })
    return rows


def _parse_candidates(raw: str) -> list[dict[str, Any]]:
    data = json.loads(_strip_fences(raw))
    if not isinstance(data, list):
        raise ValueError("Knowledge-card generator returned non-array JSON")
    return [item for item in data if isinstance(item, dict)]


def _coerce_candidate(candidate: dict[str, Any], paper_id: str, run_id: str, prompt_version: str) -> dict[str, Any] | None:
    card_type = str(candidate.get("card_type") or "claim").strip()
    if card_type not in CARD_TYPES:
        return None
    title = str(candidate.get("title") or "").strip()[:240]
    content = str(candidate.get("content") or "").strip()
    source_quote = str(candidate.get("source_quote") or "").strip()
    if not title or not content:
        return None
    use_case = str(candidate.get("use_case") or "").strip() or _default_use_case(card_type)
    why_useful = str(candidate.get("why_useful") or "").strip() or _default_why_useful(card_type)
    next_action = str(candidate.get("next_action") or "").strip() or _default_next_action(card_type)
    risk_or_caveat = str(candidate.get("risk_or_caveat") or "").strip() or "Verify applicability before reusing this paper-specific evidence."
    return {
        "card_type": card_type,
        "title": title,
        "content": content,
        "paper_id": paper_id,
        "source_page": _safe_int(candidate.get("source_page")),
        "source_quote": source_quote[:1000],
        "confidence": _safe_float(candidate.get("confidence")),
        "status": "draft",
        "tags": _as_tags(candidate.get("tags")),
        "created_by": "ai",
        "run_id": run_id,
        "source_kind": "evidence_pool" if str(candidate.get("source_ref") or "").startswith("evidence:") else "ai_report",
        "source_ref": str(candidate.get("source_ref") or "").strip()[:160],
        "normalized_key": "",
        "quality_flags": ["low_confidence"] if _safe_float(candidate.get("confidence")) < 0.5 else [],
        "prompt_version": prompt_version,
        "extractor_version": EXTRACTOR_VERSION,
        "asset_level": "action",
        "action_type": use_case,
        "why_useful": why_useful[:1000],
        "use_case": use_case[:120],
        "next_action": next_action[:1000],
        "expected_output": _default_expected_output(use_case)[:500],
        "risk_or_caveat": risk_or_caveat[:1000],
        "priority": _default_priority(card_type, _safe_float(candidate.get("confidence"))),
        "supporting_card_ids": [],
        "supporting_paper_ids": [paper_id] if paper_id else [],
        "evidence_strength": "single-paper",
    }


def _default_use_case(card_type: str) -> str:
    return {
        "method": "implementation",
        "dataset": "experiment",
        "metric": "experiment",
        "result": "writing",
        "limitation": "idea",
        "question": "idea",
        "idea": "idea",
    }.get(card_type, "writing")


def _default_why_useful(card_type: str) -> str:
    return {
        "method": "Captures a reusable method mechanism that can inform implementation, comparison, or method design.",
        "dataset": "Identifies an evaluation setting that can be reused when designing experiments or baselines.",
        "metric": "Identifies an evaluation criterion that can standardize later experiment comparison.",
        "result": "Provides cited result evidence that can support related work, motivation, or comparison writing.",
        "limitation": "Records an applicability boundary that can motivate follow-up work or risk analysis.",
        "question": "Marks an unresolved issue that can seed future reading or idea generation.",
        "idea": "Preserves a possible research direction for later refinement.",
    }.get(card_type, "Provides traceable evidence that may support later research writing or decisions.")


def _default_next_action(card_type: str) -> str:
    return {
        "method": "Compare this mechanism with your target method and decide whether it should be a baseline, module, or ablation.",
        "dataset": "Check whether this dataset or setting should be included in the next experiment matrix.",
        "metric": "Use this metric when drafting the evaluation protocol or comparing baselines.",
        "result": "Use this as cited evidence in related work or as a comparison point in the experiment section.",
        "limitation": "Turn this limitation into a motivation, stress test, or follow-up hypothesis.",
        "question": "Queue this question for targeted literature search or experiment design.",
        "idea": "Convert this idea into a concrete hypothesis and minimum experiment.",
    }.get(card_type, "Review the source and decide whether to promote this evidence into writing, experiment, or idea planning.")


def _default_expected_output(use_case: str) -> str:
    return {
        "writing": "A cited sentence or paragraph for related work, motivation, result comparison, or limitation discussion.",
        "experiment": "A dataset, metric, baseline, or ablation item in the experiment plan.",
        "idea": "A refined research hypothesis, gap statement, or follow-up experiment.",
        "review": "A review note with traceable evidence and applicability judgment.",
        "implementation": "An implementation checklist item, baseline module, or ablation variant.",
        "reading": "A prioritized reading note or follow-up question.",
    }.get(use_case, "A concrete research note that can be reused in later work.")


def _default_priority(card_type: str, confidence: float) -> str:
    if card_type in {"method", "result", "limitation"} and confidence >= 0.85:
        return "high"
    if confidence < 0.6:
        return "low"
    return "medium"


async def _is_duplicate(card: dict[str, Any]) -> bool:
    row = await db.fetch_one(
        """
        SELECT card_id
          FROM knowledge_cards
         WHERE normalized_key = ?
           AND status NOT IN ('rejected', 'merged')
         LIMIT 1
        """,
        (str(card.get("normalized_key") or ""),),
    )
    if row:
        return True
    quote = str(card.get("source_quote") or "").strip()
    if quote:
        row = await db.fetch_one(
            """
            SELECT card_id
              FROM knowledge_cards
             WHERE paper_id = ? AND source_quote = ?
               AND status NOT IN ('rejected', 'merged')
             LIMIT 1
            """,
            (str(card.get("paper_id") or ""), quote),
        )
        return bool(row)
    return False


async def _existing_generation(run_id: str, paper_id: str, source_hash: str, prompt_version: str) -> dict[str, Any] | None:
    row = await db.fetch_one(
        """
        SELECT *
          FROM knowledge_card_generations
         WHERE run_id = ? AND paper_id = ? AND source_hash = ? AND prompt_version = ?
           AND status = 'done'
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (run_id, paper_id, source_hash, prompt_version),
    )
    return row


async def _insert_generation(
    generation_id: str,
    *,
    paper_id: str,
    run_id: str,
    status: str,
    trigger_source: str,
    llm_model: str,
    prompt_version: str,
    source_hash: str,
) -> None:
    await db.execute(
        """
        INSERT INTO knowledge_card_generations (
            generation_id, paper_id, run_id, status, trigger_source, llm_model,
            prompt_version, extractor_version, source_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (generation_id, paper_id, run_id, status, trigger_source, llm_model, prompt_version, EXTRACTOR_VERSION, source_hash),
    )


async def _finish_generation(
    generation_id: str,
    *,
    status: str,
    raw_output_json: str = "[]",
    cards_created: int = 0,
    cards_skipped: int = 0,
    duplicate_count: int = 0,
    error_msg: str = "",
) -> None:
    await db.execute(
        """
        UPDATE knowledge_card_generations
           SET status = ?,
               raw_output_json = ?,
               cards_created = ?,
               cards_skipped = ?,
               duplicate_count = ?,
               error_msg = ?,
               updated_at = datetime('now')
         WHERE generation_id = ?
        """,
        (status, raw_output_json, cards_created, cards_skipped, duplicate_count, error_msg, generation_id),
    )


async def _get_generation(generation_id: str) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM knowledge_card_generations WHERE generation_id = ?", (generation_id,))
    if not row:
        raise RuntimeError("Knowledge-card generation record not found")
    row["card_ids"] = await _card_ids_for_generation(str(row.get("run_id") or ""), str(row.get("prompt_version") or ""))
    return row


async def _card_ids_for_generation(run_id: str, prompt_version: str) -> list[str]:
    if not run_id:
        return []
    rows = await db.fetch_all(
        "SELECT card_id FROM knowledge_cards WHERE run_id = ? AND prompt_version = ? ORDER BY created_at ASC",
        (run_id, prompt_version),
    )
    return [str(row.get("card_id") or "") for row in rows]
