from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.services import entity_registry
from app.services import knowledge_assets as assets

SYNTHESIS_CARD_TYPES = {"method", "dataset", "metric", "result", "limitation"}


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


def _cluster_key(card: dict[str, Any]) -> str:
    card_type = str(card.get("card_type") or "")
    normalized_key = str(card.get("normalized_key") or "")
    if normalized_key:
        parts = normalized_key.split(":")
        if len(parts) >= 3:
            return f"{card_type}:{parts[-1][:80]}"
    tags = [part.strip().lower() for part in str(card.get("tags") or "").split(",") if part.strip()]
    if tags:
        return f"{card_type}:{','.join(sorted(tags)[:3])}"
    return f"{card_type}:{_norm(str(card.get('title') or card.get('content') or ''))[:80]}"


def _group_key(card: dict[str, Any], entity_by_card: dict[str, str]) -> str:
    """Prefer the canonical entity as the cluster key (module D consumer).

    When a card is registered to a canonical method/dataset/metric, all of its
    near-duplicate mentions across papers share one entity_id, so the synthesis
    aligns on the entity instead of literal normalized keys / tags. Falls back
    to the lexical cluster key when the registry has no mention for the card.
    """
    entity_id = entity_by_card.get(str(card.get("card_id") or ""))
    if entity_id:
        return f"{str(card.get('card_type') or '')}:entity:{entity_id}"
    return _cluster_key(card)


def _summary_title(card_type: str, cards: list[dict[str, Any]]) -> str:
    label = {
        "method": "Method pattern",
        "dataset": "Shared dataset",
        "metric": "Shared metric",
        "result": "Result pattern",
        "limitation": "Recurring limitation",
    }.get(card_type, "Cross-paper synthesis")
    topic = str(cards[0].get("title") or "").strip()
    return f"{label}: {topic[:120]}" if topic else label


def _summary_content(cards: list[dict[str, Any]]) -> str:
    paper_titles = [str(card.get("paper_title") or card.get("paper_id") or "").strip() for card in cards]
    snippets = [str(card.get("content") or "").strip() for card in cards[:5] if str(card.get("content") or "").strip()]
    return (
        f"{len(cards)} papers contain related claims: "
        + "; ".join(snippets)
        + "\n\nSupporting papers: "
        + "; ".join(paper_titles[:8])
    )


async def rebuild_synthesis_cards(*, limit: int = 500) -> dict[str, int]:
    cards = await assets.list_cards(status="verified", asset_level="action", limit=limit)
    try:
        entity_by_card = await entity_registry.card_entity_map()
    except Exception:
        entity_by_card = {}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        card_type = str(card.get("card_type") or "")
        if card_type not in SYNTHESIS_CARD_TYPES:
            continue
        if not card.get("evidence_ids"):
            continue
        groups[_group_key(card, entity_by_card)].append(card)

    created = 0
    skipped = 0
    for key, items in groups.items():
        paper_ids = sorted({str(item.get("paper_id") or "") for item in items if item.get("paper_id")})
        if len(paper_ids) < 2:
            skipped += 1
            continue
        card_type = str(items[0].get("card_type") or "claim")
        supporting_card_ids = [str(item.get("card_id") or "") for item in items if item.get("card_id")]
        title = _summary_title(card_type, items)
        normalized_key = f"synthesis:{key}"
        existing = await assets.list_cards(
            status="verified",
            asset_level="synthesis",
            query=title[:80],
            limit=50,
        )
        existing_match = next(
            (card for card in existing if str(card.get("normalized_key") or "") == normalized_key),
            None,
        )
        payload = {
            "card_type": "claim",
            "title": title,
            "content": _summary_content(items),
            "paper_id": paper_ids[0],
            "source_page": int(items[0].get("source_page") or 0),
            "source_quote": str(items[0].get("source_quote") or ""),
            "confidence": min(0.95, 0.65 + 0.05 * len(paper_ids)),
            "status": "verified",
            "tags": ",".join(sorted({tag.strip() for item in items for tag in str(item.get("tags") or "").split(",") if tag.strip()})[:8]),
            "created_by": "ai",
            "normalized_key": normalized_key,
            "quality_flags": [],
            "extractor_version": "synthesis_rule_v1",
            "asset_level": "synthesis",
            "synthesis_type": card_type,
            "action_type": "writing",
            "why_useful": "Aggregates repeated evidence-backed claims across multiple papers for comparison, writing, or idea discovery.",
            "use_case": "writing",
            "next_action": "Open the supporting cards and decide whether this synthesis should be cited, split, or rejected.",
            "expected_output": "A cross-paper comparison point with traceable supporting cards.",
            "risk_or_caveat": "This synthesis is rule-clustered and should be reviewed before use in final writing.",
            "priority": "high" if len(paper_ids) >= 3 else "medium",
            "supporting_card_ids": supporting_card_ids,
            "supporting_paper_ids": paper_ids,
            "evidence_strength": "multi-paper",
            "evidence_ids": list(dict.fromkeys(str(eid) for item in items for eid in item.get("evidence_ids", [])))[:12],
        }
        if existing_match:
            await assets.update_card(str(existing_match["card_id"]), payload)
        else:
            await assets.create_card(payload)
        created += 1
    return {"synthesis_cards": created, "groups_skipped": skipped}
