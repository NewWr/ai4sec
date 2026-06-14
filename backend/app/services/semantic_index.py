from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from typing import Any, Literal

from app.config import get_settings
from app.db import database as db
from app.services.llm_runtime_config import get_llm_runtime_config
from app.services.paper_search.http_client import HTTPClient
from app.services.paper_search.llm import LLMConfig, embeddings

logger = logging.getLogger("scholar.semantic_index")

EmbeddingKind = Literal["card", "node"]


@dataclass(frozen=True)
class SemanticHit:
    item_id: str
    score: float
    metadata: dict[str, Any]


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _json_vec(vec: list[float]) -> str:
    return json.dumps([round(float(v), 8) for v in vec], ensure_ascii=False)


def _loads_vec(value: str | None) -> list[float]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[float] = []
    for item in data:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = 0.0
    norm_left = 0.0
    norm_right = 0.0
    for x, y in zip(left, right, strict=False):
        dot += x * y
        norm_left += x * x
        norm_right += y * y
    if norm_left <= 0.0 or norm_right <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_left) * math.sqrt(norm_right))


def embedding_enabled() -> bool:
    runtime = get_llm_runtime_config()
    return bool(runtime.base_url and runtime.api_key and get_settings().embed_model.strip())


async def embed_texts(texts: list[str], *, batch_size: int | None = None) -> list[list[float]]:
    clean = [str(text or "").strip() for text in texts]
    if not clean or not embedding_enabled():
        return []
    runtime = get_llm_runtime_config()
    settings = get_settings()
    client = HTTPClient(timeout=60.0)
    cfg = LLMConfig(
        base_url=runtime.base_url,
        api_key=runtime.api_key,
        max_retries=2,
        retry_base_delay=1.0,
        retry_max_delay=8.0,
    )
    try:
        return await embeddings(
            client,
            cfg=cfg,
            model=settings.embed_model.strip(),
            texts=clean,
            batch_size=batch_size or max(1, min(int(settings.embedding_backfill_batch or 128), 256)),
        )
    except Exception as exc:
        logger.warning("embedding request failed; semantic path disabled for this call: %s", exc)
        return []


def card_text(row: dict[str, Any]) -> str:
    return "\n".join(
        part
        for part in (
            f"Type: {row.get('card_type') or ''}",
            f"Title: {row.get('title') or ''}",
            f"Content: {row.get('content') or ''}",
            f"Tags: {row.get('tags') or ''}",
            f"Key: {row.get('normalized_key') or ''}",
            f"Quote: {row.get('source_quote') or ''}",
        )
        if part.strip()
    )[:6000]


def node_text(row: dict[str, Any]) -> str:
    return "\n".join(
        part
        for part in (
            f"Title path: {row.get('title_path') or row.get('title') or ''}",
            f"Text: {row.get('text_for_search') or row.get('text') or ''}",
        )
        if part.strip()
    )[:6000]


async def _card_rows(limit: int) -> list[dict[str, Any]]:
    return await db.fetch_all(
        """
        SELECT card_id, card_type, title, content, tags, normalized_key, source_quote,
               paper_id, source_page, confidence, updated_at
          FROM knowledge_cards
         WHERE status NOT IN ('rejected', 'merged')
         ORDER BY updated_at DESC
         LIMIT ?
        """,
        (max(1, int(limit)),),
    )


async def _node_rows(limit: int) -> list[dict[str, Any]]:
    return await db.fetch_all(
        """
        SELECT node_id, paper_id, node_type, block_type, title, title_path,
               page_start, text, text_for_search
          FROM paper_nodes
         WHERE node_type = 'chunk'
           AND length(trim(COALESCE(text_for_search, text, ''))) > 0
         ORDER BY paper_id, order_idx ASC
         LIMIT ?
        """,
        (max(1, int(limit)),),
    )


async def backfill_embeddings(kind: EmbeddingKind, *, limit: int = 500) -> dict[str, int | str | bool]:
    if not embedding_enabled():
        return {"kind": kind, "enabled": False, "scanned": 0, "embedded": 0, "skipped": 0}
    settings = get_settings()
    model = settings.embed_model.strip()
    rows = await (_card_rows(limit) if kind == "card" else _node_rows(limit))
    pending: list[tuple[dict[str, Any], str, str]] = []
    for row in rows:
        item_id = str(row.get("card_id" if kind == "card" else "node_id") or "")
        text = card_text(row) if kind == "card" else node_text(row)
        text_hash = _hash_text(text)
        table = "card_embeddings" if kind == "card" else "node_embeddings"
        id_col = "card_id" if kind == "card" else "node_id"
        cached = await db.fetch_one(
            f"SELECT text_hash, model_name FROM {table} WHERE {id_col} = ?",
            (item_id,),
        )
        if cached and str(cached.get("text_hash") or "") == text_hash and str(cached.get("model_name") or "") == model:
            continue
        if item_id and text.strip():
            pending.append((row, item_id, text))

    if not pending:
        return {"kind": kind, "enabled": True, "scanned": len(rows), "embedded": 0, "skipped": len(rows)}

    vecs = await embed_texts([item[2] for item in pending])
    if len(vecs) != len(pending):
        return {"kind": kind, "enabled": True, "scanned": len(rows), "embedded": 0, "skipped": len(rows)}

    if kind == "card":
        await db.execute_many(
            """
            INSERT INTO card_embeddings (card_id, embedding_json, text_hash, model_name, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(card_id) DO UPDATE SET
                embedding_json = excluded.embedding_json,
                text_hash = excluded.text_hash,
                model_name = excluded.model_name,
                updated_at = datetime('now')
            """,
            [
                (item_id, _json_vec(vec), _hash_text(text), model)
                for (_, item_id, text), vec in zip(pending, vecs, strict=False)
            ],
        )
    else:
        await db.execute_many(
            """
            INSERT INTO node_embeddings (node_id, paper_id, embedding_json, text_hash, model_name, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(node_id) DO UPDATE SET
                paper_id = excluded.paper_id,
                embedding_json = excluded.embedding_json,
                text_hash = excluded.text_hash,
                model_name = excluded.model_name,
                updated_at = datetime('now')
            """,
            [
                (item_id, str(row.get("paper_id") or ""), _json_vec(vec), _hash_text(text), model)
                for (row, item_id, text), vec in zip(pending, vecs, strict=False)
            ],
        )
    return {
        "kind": kind,
        "enabled": True,
        "scanned": len(rows),
        "embedded": len(pending),
        "skipped": len(rows) - len(pending),
    }


async def semantic_search_cards(query: str, *, limit: int = 20) -> list[SemanticHit]:
    if not query.strip() or not embedding_enabled():
        return []
    query_vecs = await embed_texts([query])
    if not query_vecs:
        return []
    model = get_settings().embed_model.strip()
    rows = await db.fetch_all(
        """
        SELECT ce.card_id, ce.embedding_json, kc.title, kc.card_type, kc.paper_id,
               kc.source_page, kc.content, kc.confidence
          FROM card_embeddings ce
          JOIN knowledge_cards kc ON kc.card_id = ce.card_id
         WHERE ce.model_name = ?
           AND kc.status NOT IN ('rejected', 'merged')
        """,
        (model,),
    )
    query_vec = query_vecs[0]
    hits: list[SemanticHit] = []
    for row in rows:
        score = cosine_similarity(query_vec, _loads_vec(str(row.get("embedding_json") or "[]")))
        if score <= 0.0:
            continue
        hits.append(SemanticHit(str(row.get("card_id") or ""), round(score, 6), dict(row)))
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[: max(1, min(int(limit), 100))]


async def semantic_search_nodes(query: str, *, paper_id: str = "", limit: int = 40) -> list[SemanticHit]:
    if not query.strip() or not embedding_enabled():
        return []
    query_vecs = await embed_texts([query])
    if not query_vecs:
        return []
    model = get_settings().embed_model.strip()
    clauses = ["ne.model_name = ?"]
    params: list[Any] = [model]
    if paper_id:
        clauses.append("ne.paper_id = ?")
        params.append(paper_id)
    rows = await db.fetch_all(
        f"""
        SELECT ne.node_id, ne.paper_id, ne.embedding_json, pn.title, pn.title_path,
               pn.page_start, pn.block_type, pn.text, pn.text_for_search
          FROM node_embeddings ne
          JOIN paper_nodes pn ON pn.node_id = ne.node_id
         WHERE {' AND '.join(clauses)}
        """,
        tuple(params),
    )
    query_vec = query_vecs[0]
    hits: list[SemanticHit] = []
    for row in rows:
        score = cosine_similarity(query_vec, _loads_vec(str(row.get("embedding_json") or "[]")))
        if score <= 0.0:
            continue
        hits.append(SemanticHit(str(row.get("node_id") or ""), round(score, 6), dict(row)))
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[: max(1, min(int(limit), 200))]


def rrf_merge(
    lexical: list[tuple[str, float, dict[str, Any]]],
    semantic: list[SemanticHit],
    *,
    limit: int,
    k: int = 60,
) -> list[tuple[str, float, dict[str, Any]]]:
    scores: dict[str, float] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for rank, (item_id, base_score, meta) in enumerate(lexical, start=1):
        scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + rank)) + float(base_score) * 0.001
        metadata[item_id] = {**meta, "lexical_score": float(base_score)}
    for rank, hit in enumerate(semantic, start=1):
        scores[hit.item_id] = scores.get(hit.item_id, 0.0) + (1.0 / (k + rank)) + hit.score * 0.01
        metadata[hit.item_id] = {**metadata.get(hit.item_id, {}), **hit.metadata, "semantic_score": hit.score}
    merged = [(item_id, round(score, 6), metadata.get(item_id, {})) for item_id, score in scores.items()]
    merged.sort(key=lambda item: item[1], reverse=True)
    return merged[: max(1, int(limit))]
