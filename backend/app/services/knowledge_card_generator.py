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
from app.services import evidence_store
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
- If SECTION_CONTEXT blocks are present, extract factual cards from the matching section role first: method cards from method sections, dataset/metric/result cards from evaluation sections, and limitation/question/idea from assessment sections.
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


@dataclass
class CritiqueResult:
    score: float
    flags: list[str]
    passed: bool


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
        research_profiles = await _research_profiles_for_paper(paper_id)
        promote_threshold = float(settings.knowledge_card_promote_confidence)
        card_ids: list[str] = []
        skipped = 0
        duplicates = 0
        critique_low = 0

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
            critique = critique_card_candidate(card, match=match, research_profiles=research_profiles)
            card["quality_flags"] = sorted(set([*card["quality_flags"], *critique.flags]))
            card["critique_score"] = critique.score
            if not critique.passed:
                critique_low += 1
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
            if card["card_type"] in {"question", "idea"}:
                await _upsert_gap_seed(card, paper_id=paper_id, run_id=run_id, prompt_version=prompt_version)
                continue
            # Bind fact cards to the unified evidence layer (ADR-2): anchor the
            # source quote into research_evidence_items and pass evidence_ids so
            # create_card writes the research_evidence_cards bridge.
            evidence_ids: list[str] = []
            if card["card_type"] in FACT_CARD_TYPES and card["source_quote"]:
                try:
                    eid = await evidence_store.upsert_evidence(
                        paper_id,
                        card["source_quote"],
                        evidence_type=card["card_type"],
                        page=card.get("source_page") or 0,
                        source_run_id=run_id,
                        confidence=card.get("confidence") or 0.0,
                        extractor=EXTRACTOR_VERSION,
                        prompt_version=prompt_version,
                    )
                    evidence_ids = [eid]
                except Exception as exc:
                    logger.warning("[%s] evidence upsert failed for card: %s", paper_id, exc)
            card["evidence_ids"] = evidence_ids
            # Promotion state machine (ADR-10): high-confidence, evidence-anchored
            # cards auto-promote to verified; everything else stays draft in the
            # review queue.
            if critique.passed and _should_promote(card, evidence_ids, promote_threshold):
                card["status"] = "verified"
            created = await assets.create_card(card)
            card_ids.append(str(created.get("card_id") or ""))

        await _finish_generation(
            generation_id,
            status="done",
            raw_output_json=json.dumps(candidates, ensure_ascii=False),
            cards_created=len(card_ids),
            cards_skipped=skipped,
            duplicate_count=duplicates,
            critique_low_count=critique_low,
            total_candidates=len(candidates[:max_cards]),
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


def _should_promote(card: dict[str, Any], evidence_ids: list[str], threshold: float) -> bool:
    """Promotion gate (ADR-10): auto-promote draft -> verified only when the card
    is high-confidence, evidence-anchored (fact cards) and articulates its value.
    """
    if _safe_float(card.get("confidence")) < threshold:
        return False
    if not str(card.get("why_useful") or "").strip() or not str(card.get("next_action") or "").strip():
        return False
    if str(card.get("card_type") or "") in FACT_CARD_TYPES and not evidence_ids:
        return False
    return True


def critique_card_candidate(
    card: dict[str, Any],
    *,
    match: SourceMatch,
    research_profiles: list[str] | None = None,
) -> CritiqueResult:
    score = _safe_float(card.get("confidence"))
    flags: list[str] = []
    for field in ("why_useful", "use_case", "next_action", "risk_or_caveat"):
        if not str(card.get(field) or "").strip():
            score -= 0.18
            flags.append(f"critique_missing_{field}")
    if str(card.get("card_type") or "") in FACT_CARD_TYPES and not match.ok:
        score -= 0.35
        flags.append("critique_unanchored_fact")
    text = _norm_text(
        " ".join(
            str(card.get(field) or "")
            for field in ("title", "content", "why_useful", "next_action", "risk_or_caveat")
        )
    )
    generic_markers = [
        "future research",
        "important for researchers",
        "provides insights",
        "further investigate",
        "后续研究",
        "具有重要意义",
    ]
    if any(marker in text for marker in generic_markers):
        score -= 0.10
        flags.append("critique_generic_value")
    profile_terms = _profile_terms(research_profiles or [])
    if profile_terms:
        profile_hits = [term for term in profile_terms if term in text]
        if not profile_hits:
            score -= 0.16
            flags.append("critique_profile_unreferenced")
        else:
            flags.append("critique_profile_referenced")
    score = round(max(0.0, min(1.0, score)), 3)
    blocking_flags = {
        "critique_profile_unreferenced",
        "critique_unanchored_fact",
    }
    flag_set = set(flags)
    passed = (
        score >= 0.62
        and not any(flag.startswith("critique_missing_") for flag in flag_set)
        and not (flag_set & blocking_flags)
    )
    return CritiqueResult(score=score, flags=sorted(flag_set), passed=passed)


def _profile_terms(profiles: list[str]) -> list[str]:
    terms: list[str] = []
    for profile in profiles:
        tokens = re.findall(r"[\u4e00-\u9fff]{2,8}|[a-zA-Z][a-zA-Z0-9-]{2,}", profile.lower())
        for token in tokens:
            token = token.strip().lower()
            if token and token not in terms:
                terms.append(token)
            if len(terms) >= 24:
                return terms
    return terms


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
    profiles = await _research_profiles_for_paper(paper_id)
    if profiles:
        parts.append("Research profile:")
        parts.extend(f"- {profile}" for profile in profiles)
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
    section_contexts = final_json.get("lens_section_contexts") if isinstance(final_json, dict) else []
    if isinstance(section_contexts, list) and section_contexts:
        parts.append("SECTION_CONTEXT blocks:")
        for item in section_contexts[:8]:
            if not isinstance(item, dict):
                continue
            key = str(item.get("section_key") or "").strip()
            target = ", ".join(str(value) for value in item.get("target_card_types") or [] if str(value).strip())
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            parts.append(f"## SECTION_CONTEXT {key} target_card_types={target}\n{_cap_context_text(text, 3500)}")
    if markdown.strip():
        parts.append("Analysis markdown:")
        parts.append(_cap_context_text(markdown, 5000 if section_contexts else 8000))
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


def _cap_context_text(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit]


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
    use_case = str(candidate.get("use_case") or "").strip()
    why_useful = str(candidate.get("why_useful") or "").strip()
    next_action = str(candidate.get("next_action") or "").strip()
    risk_or_caveat = str(candidate.get("risk_or_caveat") or "").strip()
    quality_flags = ["low_confidence"] if _safe_float(candidate.get("confidence")) < 0.5 else []
    missing_value_fields = [
        field
        for field, value in (
            ("why_useful", why_useful),
            ("use_case", use_case),
            ("next_action", next_action),
            ("risk_or_caveat", risk_or_caveat),
        )
        if not value
    ]
    if missing_value_fields:
        quality_flags.append("missing_value_fields")
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
        "quality_flags": quality_flags,
        "prompt_version": prompt_version,
        "extractor_version": EXTRACTOR_VERSION,
        "asset_level": "action",
        "action_type": use_case,
        "why_useful": why_useful[:1000],
        "use_case": use_case[:120],
        "next_action": next_action[:1000],
        "expected_output": str(candidate.get("expected_output") or "").strip()[:500],
        "risk_or_caveat": risk_or_caveat[:1000],
        "priority": _default_priority(card_type, _safe_float(candidate.get("confidence"))),
        "supporting_card_ids": [],
        "supporting_paper_ids": [paper_id] if paper_id else [],
        "evidence_strength": "single-paper",
    }


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


async def _research_profiles_for_paper(paper_id: str) -> list[str]:
    rows = await db.fetch_all(
        """
        SELECT DISTINCT ks.research_profile
          FROM knowledge_spaces ks
          JOIN knowledge_space_items ksi ON ksi.space_id = ks.space_id
         WHERE ksi.paper_id = ?
           AND ks.research_profile != ''
         ORDER BY ks.sort_order ASC, ks.name ASC
         LIMIT 5
        """,
        (paper_id,),
    )
    return [str(row.get("research_profile") or "").strip()[:1200] for row in rows if str(row.get("research_profile") or "").strip()]


def _gap_seed_id(paper_id: str, title: str, content: str) -> str:
    seed = _norm_text(f"{paper_id}|{title}|{content}")[:240]
    return "gap_seed_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


async def _upsert_gap_seed(
    card: dict[str, Any],
    *,
    paper_id: str,
    run_id: str,
    prompt_version: str,
) -> None:
    support_evidence_ids: list[str] = []
    source_quote = str(card.get("source_quote") or "").strip()
    if source_quote:
        match = await evidence_store.anchor_quote(paper_id, source_quote)
        if match.ok:
            support_evidence_ids = [
                await evidence_store.upsert_evidence(
                    paper_id,
                    source_quote,
                    evidence_type=str(card.get("card_type") or "idea"),
                    page=int(card.get("source_page") or 0) or match.page,
                    block_id=match.block_id,
                    source_run_id=run_id,
                    confidence=float(card.get("confidence") or 0.0),
                    extractor=EXTRACTOR_VERSION,
                    prompt_version=prompt_version,
                    anchor=False,
                )
            ]
    gap_id = _gap_seed_id(paper_id, str(card.get("title") or ""), str(card.get("content") or ""))
    await db.execute(
        """
        INSERT INTO research_gaps (
            gap_id, title, hypothesis, description, support_evidence_ids,
            counter_evidence_ids, coverage_status, novelty_score, feasibility_score,
            evidence_strength, risk_score, experiment_cost, domain_value, status,
            rejection_reason, minimum_experiment, gap_version
        ) VALUES (?, ?, ?, ?, ?, '[]', 'unknown', ?, ?, ?, ?, ?, ?, 'candidate', '', ?, 1)
        ON CONFLICT(gap_id) DO UPDATE SET
            hypothesis = excluded.hypothesis,
            description = excluded.description,
            support_evidence_ids = excluded.support_evidence_ids,
            novelty_score = excluded.novelty_score,
            feasibility_score = excluded.feasibility_score,
            evidence_strength = excluded.evidence_strength,
            risk_score = excluded.risk_score,
            experiment_cost = excluded.experiment_cost,
            domain_value = excluded.domain_value,
            minimum_experiment = excluded.minimum_experiment,
            updated_at = datetime('now')
        WHERE research_gaps.status NOT IN ('rejected', 'promoted_to_idea')
        """,
        (
            gap_id,
            str(card.get("title") or "")[:240],
            str(card.get("content") or "")[:2000],
            str(card.get("why_useful") or card.get("content") or "")[:4000],
            json.dumps(support_evidence_ids, ensure_ascii=False),
            max(0.35, float(card.get("confidence") or 0.0) * 0.7),
            0.45,
            min(1.0, 0.35 + len(support_evidence_ids) * 0.25),
            0.45,
            0.4,
            0.5,
            str(card.get("next_action") or "")[:1000],
        ),
    )


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
    critique_low_count: int = 0,
    total_candidates: int = 0,
    error_msg: str = "",
) -> None:
    summary = {
        "total_candidates": total_candidates,
        "created": cards_created,
        "skipped": cards_skipped,
        "duplicates": duplicate_count,
        "critique_low_count": critique_low_count,
        "critique_rejection_rate": round(critique_low_count / total_candidates, 3) if total_candidates else 0.0,
    }
    await db.execute(
        """
        UPDATE knowledge_card_generations
           SET status = ?,
               raw_output_json = ?,
               cards_created = ?,
               cards_skipped = ?,
               duplicate_count = ?,
               critique_summary_json = ?,
               error_msg = ?,
               updated_at = datetime('now')
         WHERE generation_id = ?
        """,
        (
            status,
            raw_output_json,
            cards_created,
            cards_skipped,
            duplicate_count,
            json.dumps(summary, ensure_ascii=False),
            error_msg,
            generation_id,
        ),
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
