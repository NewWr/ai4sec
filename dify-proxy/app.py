from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException


app = FastAPI(title="AI4Sec Dify Proxy")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _dify_base() -> str:
    value = _env("DIFY_BASE_URL")
    if not value:
        raise HTTPException(status_code=500, detail="DIFY_BASE_URL is not configured")
    return value.rstrip("/")


def _api_key() -> str:
    value = _env("DIFY_DATASET_API_KEY")
    if not value:
        raise HTTPException(status_code=500, detail="DIFY_DATASET_API_KEY is not configured")
    return value


def _default_dataset() -> str:
    return _env("DIFY_DEFAULT_DATASET_ID")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}"}


def _client() -> httpx.AsyncClient:
    timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=120.0)
    return httpx.AsyncClient(timeout=timeout)


async def _request(method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None) -> Any:
    url = f"{_dify_base()}/v1{path}"
    try:
        async with _client() as client:
            resp = await client.request(method, url, headers=_headers(), params=params, json=json)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Dify request failed: {exc}") from exc

    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:500]
        raise HTTPException(status_code=resp.status_code, detail=detail)

    if resp.status_code == 204:
        return {}
    try:
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Dify returned non-JSON response: {exc}") from exc


def _dataset_or_default(dataset_id: str | None = None) -> str:
    ds = (dataset_id or "").strip() or _default_dataset()
    if not ds:
        raise HTTPException(status_code=400, detail="dataset_id is required")
    return ds


def _clean_params(page: int, limit: int) -> dict[str, int]:
    return {"page": max(1, page), "limit": max(1, min(limit, 100))}


def _document_payload(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    text = str(payload.get("text") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name must be non-empty")
    if not text:
        raise HTTPException(status_code=400, detail="text must be non-empty")

    body = dict(payload)
    body["name"] = name
    body["text"] = text
    body.setdefault("indexing_technique", "economy")
    body.setdefault("process_rule", {"mode": "automatic"})
    return body


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/datasets")
async def list_datasets(page: int = 1, limit: int = 20) -> Any:
    return await _request("GET", "/datasets", params=_clean_params(page, limit))


@app.post("/api/datasets")
async def create_dataset(payload: dict[str, Any]) -> Any:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name must be non-empty")
    body = dict(payload)
    body["name"] = name
    body.setdefault("indexing_technique", "economy")
    body.setdefault("permission", "only_me")
    return await _request("POST", "/datasets", json=body)


@app.patch("/api/datasets/{dataset_id}")
async def update_dataset(dataset_id: str, payload: dict[str, Any]) -> Any:
    ds = quote(_dataset_or_default(dataset_id), safe="")
    return await _request("PATCH", f"/datasets/{ds}", json=payload)


@app.get("/api/documents")
async def list_default_documents(page: int = 1, limit: int = 20) -> Any:
    return await list_documents(_dataset_or_default(), page, limit)


@app.get("/api/datasets/{dataset_id}/documents")
async def list_documents(dataset_id: str, page: int = 1, limit: int = 20) -> Any:
    ds = quote(_dataset_or_default(dataset_id), safe="")
    return await _request("GET", f"/datasets/{ds}/documents", params=_clean_params(page, limit))


@app.post("/api/documents/create-by-text")
async def create_default_document_by_text(payload: dict[str, Any]) -> Any:
    return await create_document_by_text(_dataset_or_default(), payload)


@app.post("/api/datasets/{dataset_id}/documents/create-by-text")
async def create_document_by_text(dataset_id: str, payload: dict[str, Any]) -> Any:
    ds = quote(_dataset_or_default(dataset_id), safe="")
    return await _request("POST", f"/datasets/{ds}/document/create-by-text", json=_document_payload(payload))


@app.get("/api/documents/{document_id}")
async def get_default_document(document_id: str) -> Any:
    return await get_document(_dataset_or_default(), document_id)


@app.get("/api/datasets/{dataset_id}/documents/{document_id}")
async def get_document(dataset_id: str, document_id: str) -> Any:
    ds = quote(_dataset_or_default(dataset_id), safe="")
    doc = quote(document_id, safe="")
    return await _request("GET", f"/datasets/{ds}/documents/{doc}")


@app.delete("/api/datasets/{dataset_id}/documents/{document_id}")
async def delete_document(dataset_id: str, document_id: str) -> Any:
    ds = quote(_dataset_or_default(dataset_id), safe="")
    doc = quote(document_id, safe="")
    return await _request("DELETE", f"/datasets/{ds}/documents/{doc}")


@app.get("/api/documents/{document_id}/segments")
async def list_default_segments(document_id: str, page: int = 1, limit: int = 100) -> Any:
    return await list_segments(_dataset_or_default(), document_id, page, limit)


@app.get("/api/datasets/{dataset_id}/documents/{document_id}/segments")
async def list_segments(dataset_id: str, document_id: str, page: int = 1, limit: int = 100) -> Any:
    ds = quote(_dataset_or_default(dataset_id), safe="")
    doc = quote(document_id, safe="")
    return await _request("GET", f"/datasets/{ds}/documents/{doc}/segments", params=_clean_params(page, limit))


@app.get("/api/documents/{document_id}/markdown")
async def get_default_markdown(document_id: str) -> dict[str, Any]:
    return await get_markdown(_dataset_or_default(), document_id)


@app.get("/api/datasets/{dataset_id}/documents/{document_id}/markdown")
async def get_markdown(dataset_id: str, document_id: str) -> dict[str, Any]:
    document = await get_document(dataset_id, document_id)
    segments = await list_segments(dataset_id, document_id, page=1, limit=100)
    content = "\n\n".join(
        str(item.get("content") or "")
        for item in segments.get("data", [])
        if isinstance(item, dict) and item.get("content")
    )
    return {
        "document_id": document_id,
        "document_name": document.get("name") or document_id,
        "content": content,
    }


@app.get("/api/documents/{document_id}/download")
async def get_default_download(document_id: str) -> Any:
    return await get_download(_dataset_or_default(), document_id)


@app.get("/api/datasets/{dataset_id}/documents/{document_id}/download")
async def get_download(dataset_id: str, document_id: str) -> Any:
    ds = quote(_dataset_or_default(dataset_id), safe="")
    doc = quote(document_id, safe="")
    return await _request("GET", f"/datasets/{ds}/documents/{doc}/download")


def _retrieval_model(payload: dict[str, Any]) -> dict[str, Any]:
    method = str(payload.get("search_method") or "keyword_search")
    if method not in {"semantic_search", "full_text_search", "hybrid_search", "keyword_search"}:
        method = "keyword_search"
    # Economy-indexed datasets can be retrieved without configured embedding
    # models via keyword/full-text search. Semantic/hybrid retrieval calls the
    # model provider and returns Dify "[models] ... 404 page not found" when the
    # provider base URL/key is not valid, so keep the proxy fault-tolerant.
    if method in {"semantic_search", "hybrid_search"}:
        method = "keyword_search"
    model: dict[str, Any] = {
        "search_method": method,
        "top_k": max(1, min(int(payload.get("top_k") or 10), 100)),
        "reranking_enable": False,
        "score_threshold_enabled": payload.get("score_threshold") is not None,
    }
    if payload.get("score_threshold") is not None:
        model["score_threshold"] = float(payload["score_threshold"])
    return model


def _record_from_hit(item: dict[str, Any]) -> dict[str, Any]:
    segment = item.get("segment") or {}
    document = segment.get("document") or {}
    return {
        "document_id": segment.get("document_id") or document.get("id") or "",
        "document_name": document.get("name") or "",
        "segment_id": segment.get("id") or "",
        "content": segment.get("content") or "",
        "score": item.get("score"),
        "metadata": {"document": document, "segment": segment},
    }


@app.post("/api/search")
async def search_default(payload: dict[str, Any]) -> dict[str, Any]:
    return await search(_default_dataset(), payload)


@app.post("/api/datasets/{dataset_id}/search")
async def search(dataset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ds = quote(_dataset_or_default(dataset_id), safe="")
    query = str(payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must be non-empty")

    data = await _request(
        "POST",
        f"/datasets/{ds}/retrieve",
        json={"query": query, "retrieval_model": _retrieval_model(payload)},
    )
    raw_records = data.get("records") if isinstance(data, dict) else []
    records = [_record_from_hit(item) for item in raw_records if isinstance(item, dict)]
    return {"query": query, "records": records}
