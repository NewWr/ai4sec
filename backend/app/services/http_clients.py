from __future__ import annotations

import httpx

from app.config import get_settings

_dify_client: httpx.AsyncClient | None = None
_llm_client: httpx.AsyncClient | None = None
_default_client: httpx.AsyncClient | None = None


async def init_http_clients() -> None:
    """Initialize process-level HTTP clients for connection reuse."""
    global _dify_client, _llm_client, _default_client
    settings = get_settings()
    if _dify_client is None:
        read = float(settings.dify_timeout_seconds)
        _dify_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=read, write=30.0, pool=read))
    if _llm_client is None:
        _llm_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=900.0, write=30.0, pool=30.0))
    if _default_client is None:
        _default_client = httpx.AsyncClient(timeout=30.0)


async def close_http_clients() -> None:
    """Close process-level HTTP clients."""
    global _dify_client, _llm_client, _default_client
    for client in (_dify_client, _llm_client, _default_client):
        if client is not None:
            await client.aclose()
    _dify_client = None
    _llm_client = None
    _default_client = None


def get_dify_http_client() -> httpx.AsyncClient:
    global _dify_client
    if _dify_client is None:
        read = float(get_settings().dify_timeout_seconds)
        _dify_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=read, write=30.0, pool=read))
    return _dify_client


def get_llm_http_client() -> httpx.AsyncClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=900.0, write=30.0, pool=30.0))
    return _llm_client


def get_default_http_client() -> httpx.AsyncClient:
    global _default_client
    if _default_client is None:
        _default_client = httpx.AsyncClient(timeout=30.0)
    return _default_client
