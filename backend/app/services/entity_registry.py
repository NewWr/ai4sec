from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from app.config import get_settings
from app.db import database as db
from app.services import semantic_index
from app.services.llm_runtime_config import get_llm_runtime_config
from app.services.llm_service import get_llm_service

logger = logging.getLogger("scholar.entity_registry")

ENTITY_CARD_TYPES = {"method", "dataset", "metric", "result", "limitation"}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(value or "").lower())).strip()


def _entity_id(entity_type: str, canonical_name: str) -> str:
    seed = f"{entity_type}:{_norm(canonical_name)}"
    return "ent_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


def _mention_id(entity_id: str, card_id: str) -> str:
    return "ment_" + hashlib.sha1(f"{entity_id}:{card_id}".encode("utf-8")).hexdigest()[:24]


def _loads_vec(value: str | None) -> list[float]:
    return [float(v) for v in _loads_list(value) if isinstance(v, (int, float))]


def _centroid(vectors: list[list[float]]) -> list[float]:
    vectors = [vec for vec in vectors if vec]
    if not vectors:
        return []
    width = min(len(vec) for vec in vectors)
    if width <= 0:
        return []
    return [sum(vec[idx] for vec in vectors) / len(vectors) for idx in range(width)]


async def _cards_for_registry(limit: int) -> list[dict[str, Any]]:
    return await db.fetch_all(
        """
        SELECT kc.card_id, kc.card_type, kc.title, kc.content, kc.paper_id,
               kc.normalized_key, kc.tags, kc.confidence, ce.embedding_json
          FROM knowledge_cards kc
          LEFT JOIN card_embeddings ce ON ce.card_id = kc.card_id
         WHERE kc.status IN ('verified', 'draft')
           AND kc.card_type IN ('method', 'dataset', 'metric', 'result', 'limitation')
         ORDER BY kc.updated_at DESC
         LIMIT ?
        """,
        (max(1, int(limit)),),
    )


async def _llm_entity_name(entity_type: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    runtime = get_llm_runtime_config()
    if not runtime.base_url or not runtime.api_key or not runtime.default_thinking_model:
        return {}
    payload = {
        "entity_type": entity_type,
        "mentions": [
            {
                "title": str(card.get("title") or ""),
                "content": str(card.get("content") or "")[:500],
                "tags": str(card.get("tags") or ""),
            }
            for card in cards[:8]
        ],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Name a canonical research entity from evidence cards. "
                "Return strict JSON: {\"canonical_name\":\"...\",\"aliases\":[\"...\"],\"definition\":\"...\"}. "
                "Use only provided mentions."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        raw = await get_llm_service().chat(messages, temperature=0.0)
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.debug("entity canonical naming skipped: %s", exc)
        return {}


async def _upsert_entity(
    *,
    entity_type: str,
    canonical_name: str,
    aliases: list[str],
    definition: str,
    vectors: list[list[float]],
    cards: list[dict[str, Any]],
    created_by: str,
) -> str:
    entity_id = _entity_id(entity_type, canonical_name)
    centroid = _centroid(vectors)
    existing = await db.fetch_one("SELECT * FROM canonical_entities WHERE entity_id = ?", (entity_id,))
    if existing:
        merged_aliases = list(
            dict.fromkeys(
                [str(item) for item in _loads_list(str(existing.get("aliases_json") or "[]"))]
                + aliases
                + [str(card.get("title") or "") for card in cards]
            )
        )[:24]
        await db.execute(
            """
            UPDATE canonical_entities
               SET aliases_json = ?,
                   definition = CASE WHEN definition = '' THEN ? ELSE definition END,
                   centroid_json = CASE WHEN ? != '[]' THEN ? ELSE centroid_json END,
                   mention_count = (
                       SELECT COUNT(*) FROM entity_mentions WHERE entity_id = canonical_entities.entity_id
                   ),
                   updated_at = datetime('now')
             WHERE entity_id = ?
            """,
            (_json(merged_aliases), definition, _json(centroid), _json(centroid), entity_id),
        )
    else:
        await db.execute(
            """
            INSERT INTO canonical_entities (
                entity_id, entity_type, canonical_name, aliases_json, definition,
                centroid_json, mention_count, created_by, model_version
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                entity_id,
                entity_type,
                canonical_name,
                _json(list(dict.fromkeys(aliases))[:24]),
                definition,
                _json(centroid),
                created_by,
                get_settings().default_thinking_model,
            ),
        )
    return entity_id


async def _insert_mentions(entity_id: str, cards: list[dict[str, Any]]) -> int:
    inserted = 0
    for card in cards:
        card_id = str(card.get("card_id") or "")
        if not card_id:
            continue
        await db.execute(
            """
            INSERT OR IGNORE INTO entity_mentions (
                mention_id, entity_id, card_id, paper_id, mention_text, confidence
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _mention_id(entity_id, card_id),
                entity_id,
                card_id,
                str(card.get("paper_id") or ""),
                str(card.get("title") or ""),
                float(card.get("confidence") or 0.0),
            ),
        )
        inserted += 1
    await db.execute(
        """
        UPDATE canonical_entities
           SET mention_count = (
               SELECT COUNT(*) FROM entity_mentions WHERE entity_id = canonical_entities.entity_id
           ),
               updated_at = datetime('now')
         WHERE entity_id = ?
        """,
        (entity_id,),
    )
    return inserted


async def normalize_entities(*, limit: int = 500) -> dict[str, int | bool]:
    stats = await semantic_index.backfill_embeddings("card", limit=limit)
    cards = await _cards_for_registry(limit)
    if not cards:
        return {"enabled": bool(stats.get("enabled")), "cards": 0, "entities_created": 0, "mentions": 0}

    threshold = float(get_settings().entity_sim_threshold)
    max_new = max(0, int(get_settings().max_entities_per_run or 20))
    by_type: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        card_type = str(card.get("card_type") or "")
        if card_type in ENTITY_CARD_TYPES:
            by_type.setdefault(card_type, []).append(card)

    entities_created = 0
    mentions = 0
    for entity_type, items in by_type.items():
        entity_rows = await db.fetch_all(
            "SELECT * FROM canonical_entities WHERE entity_type = ?",
            (entity_type,),
        )
        entity_vectors = {
            str(row.get("entity_id") or ""): _loads_vec(str(row.get("centroid_json") or "[]"))
            for row in entity_rows
        }
        unassigned: list[dict[str, Any]] = []
        for card in items:
            existing_mention = await db.fetch_one(
                "SELECT entity_id FROM entity_mentions WHERE card_id = ? LIMIT 1",
                (str(card.get("card_id") or ""),),
            )
            if existing_mention:
                continue
            vec = _loads_vec(str(card.get("embedding_json") or "[]"))
            best_id = ""
            best_score = 0.0
            if vec:
                for entity_id, entity_vec in entity_vectors.items():
                    score = semantic_index.cosine_similarity(vec, entity_vec)
                    if score > best_score:
                        best_id = entity_id
                        best_score = score
            if best_id and best_score >= threshold:
                mentions += await _insert_mentions(best_id, [card])
            else:
                unassigned.append(card)

        clusters: list[list[dict[str, Any]]] = []
        for card in unassigned:
            card_vec = _loads_vec(str(card.get("embedding_json") or "[]"))
            placed = False
            for cluster in clusters:
                head_vec = _loads_vec(str(cluster[0].get("embedding_json") or "[]"))
                same_key = _norm(str(card.get("normalized_key") or card.get("title") or "")) == _norm(
                    str(cluster[0].get("normalized_key") or cluster[0].get("title") or "")
                )
                similar = card_vec and head_vec and semantic_index.cosine_similarity(card_vec, head_vec) >= threshold
                if same_key or similar:
                    cluster.append(card)
                    placed = True
                    break
            if not placed:
                clusters.append([card])

        for cluster in clusters[:max_new]:
            titles = [str(card.get("title") or "") for card in cluster if str(card.get("title") or "")]
            fallback_name = titles[0] if titles else entity_type
            llm_named = await _llm_entity_name(entity_type, cluster)
            canonical_name = str(llm_named.get("canonical_name") or fallback_name).strip()[:240] or fallback_name
            aliases = [
                str(item).strip()
                for item in (llm_named.get("aliases") if isinstance(llm_named.get("aliases"), list) else titles)
                if str(item).strip()
            ]
            definition = str(llm_named.get("definition") or str(cluster[0].get("content") or "")[:300]).strip()
            vectors = [_loads_vec(str(card.get("embedding_json") or "[]")) for card in cluster]
            entity_id = await _upsert_entity(
                entity_type=entity_type,
                canonical_name=canonical_name,
                aliases=aliases or titles,
                definition=definition,
                vectors=vectors,
                cards=cluster,
                created_by="llm" if llm_named else "rule",
            )
            entities_created += 1
            mentions += await _insert_mentions(entity_id, cluster)

    return {
        "enabled": bool(stats.get("enabled")),
        "cards": len(cards),
        "entities_created": entities_created,
        "mentions": mentions,
    }


async def semantic_duplicate_card(card: dict[str, Any], *, threshold: float | None = None) -> str:
    card_type = str(card.get("card_type") or "")
    if card_type not in ENTITY_CARD_TYPES:
        return ""
    text = semantic_index.card_text(card)
    vecs = await semantic_index.embed_texts([text])
    if not vecs:
        return ""
    threshold = threshold if threshold is not None else float(get_settings().entity_sim_threshold)
    rows = await db.fetch_all(
        """
        SELECT kc.card_id, ce.embedding_json
          FROM card_embeddings ce
          JOIN knowledge_cards kc ON kc.card_id = ce.card_id
         WHERE kc.card_type = ?
           AND kc.paper_id != ?
           AND kc.status NOT IN ('rejected', 'merged')
        """,
        (card_type, str(card.get("paper_id") or "")),
    )
    best_card = ""
    best_score = 0.0
    for row in rows:
        score = semantic_index.cosine_similarity(vecs[0], _loads_vec(str(row.get("embedding_json") or "[]")))
        if score > best_score:
            best_score = score
            best_card = str(row.get("card_id") or "")
    return best_card if best_score >= threshold else ""


async def list_entities(
    *,
    entity_type: str = "",
    query: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List canonical entities with the papers/cards that mention them.

    This is the read side of the entity registry (module D): the comparison /
    synthesis surfaces use it to render one row per canonical method/dataset/
    metric instead of repeating near-duplicate cards.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if entity_type:
        clauses.append("ce.entity_type = ?")
        params.append(entity_type)
    if query.strip():
        like = f"%{query.strip().lower()}%"
        clauses.append("(lower(ce.canonical_name) LIKE ? OR lower(ce.aliases_json) LIKE ? OR lower(ce.definition) LIKE ?)")
        params.extend([like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await db.fetch_all(
        f"""
        SELECT ce.entity_id, ce.entity_type, ce.canonical_name, ce.aliases_json,
               ce.definition, ce.mention_count, ce.created_by, ce.updated_at
          FROM canonical_entities ce
          {where}
         ORDER BY ce.mention_count DESC, ce.updated_at DESC
         LIMIT ?
        """,
        tuple(params + [max(1, min(int(limit), 200))]),
    )
    entities: list[dict[str, Any]] = []
    for row in rows:
        entity_id = str(row.get("entity_id") or "")
        mentions = await db.fetch_all(
            """
            SELECT em.card_id, em.paper_id, em.mention_text, em.confidence,
                   COALESCE(p.title, '') AS paper_title
              FROM entity_mentions em
              LEFT JOIN papers p ON p.paper_id = em.paper_id
             WHERE em.entity_id = ?
             ORDER BY em.confidence DESC
             LIMIT 50
            """,
            (entity_id,),
        )
        paper_ids = list(dict.fromkeys(str(item.get("paper_id") or "") for item in mentions if item.get("paper_id")))
        entities.append(
            {
                "entity_id": entity_id,
                "entity_type": str(row.get("entity_type") or ""),
                "canonical_name": str(row.get("canonical_name") or ""),
                "aliases": _loads_list(str(row.get("aliases_json") or "[]")),
                "definition": str(row.get("definition") or ""),
                "mention_count": int(row.get("mention_count") or 0),
                "paper_count": len(paper_ids),
                "paper_ids": paper_ids,
                "mentions": [
                    {
                        "card_id": str(item.get("card_id") or ""),
                        "paper_id": str(item.get("paper_id") or ""),
                        "paper_title": str(item.get("paper_title") or ""),
                        "mention_text": str(item.get("mention_text") or ""),
                        "confidence": float(item.get("confidence") or 0.0),
                    }
                    for item in mentions
                ],
                "created_by": str(row.get("created_by") or ""),
                "updated_at": str(row.get("updated_at") or ""),
            }
        )
    return entities


async def card_entity_map() -> dict[str, str]:
    """Map card_id -> entity_id for every registered mention.

    Used by knowledge_synthesis to cluster cross-paper synthesis on canonical
    entities instead of literal normalized keys / tags.
    """
    rows = await db.fetch_all("SELECT card_id, entity_id FROM entity_mentions WHERE card_id != ''")
    mapping: dict[str, str] = {}
    for row in rows:
        card_id = str(row.get("card_id") or "")
        entity_id = str(row.get("entity_id") or "")
        if card_id and entity_id and card_id not in mapping:
            mapping[card_id] = entity_id
    return mapping


async def expand_terms_with_aliases(terms: list[str], *, max_extra: int = 12) -> list[str]:
    """Expand query terms with canonical-entity aliases for lexical recall.

    When a query term matches a canonical entity's name or one of its aliases,
    surface that entity's other aliases as additional lexical terms (e.g.
    ``imagenet`` also pulls ``ImageNet-1k``). Returns the original terms plus
    bounded, deduped alias terms. With an empty registry this is a no-op, so
    callers degrade gracefully when entities have not been built yet.
    """
    clean = [str(term or "").strip() for term in terms if str(term or "").strip()]
    if not clean:
        return list(terms)
    rows = await db.fetch_all("SELECT canonical_name, aliases_json FROM canonical_entities LIMIT 2000")
    if not rows:
        return list(terms)
    lowered = {term.lower() for term in clean}
    extra: list[str] = []
    for row in rows:
        surfaces = [str(row.get("canonical_name") or "")]
        surfaces.extend(_loads_list(str(row.get("aliases_json") or "[]")))
        surfaces = [name for name in surfaces if name.strip()]
        surfaces_l = {name.lower() for name in surfaces}
        matched = bool(lowered & surfaces_l) or any(
            term in name_l for name_l in surfaces_l for term in lowered if len(term) >= 4
        )
        if not matched:
            continue
        for name in surfaces:
            if name.lower() not in lowered and name not in extra:
                extra.append(name)
        if len(extra) >= max_extra:
            break
    return clean + extra[:max_extra]
