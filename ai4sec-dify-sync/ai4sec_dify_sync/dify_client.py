from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True)
class DifyConfig:
    dataset_id: str
    base_url: str = ""
    dataset_api_key: str = ""
    proxy_base_url: str = ""
    timeout_seconds: float = 120.0
    indexing_technique: str = "economy"
    process_rule_mode: str = "automatic"


class DifyClient:
    def __init__(self, config: DifyConfig) -> None:
        self.config = config

    async def create_document_by_text(self, name: str, text: str) -> str:
        payload = {
            "name": name,
            "text": text,
            "indexing_technique": self.config.indexing_technique,
            "process_rule": {"mode": self.config.process_rule_mode},
        }
        dataset_id = quote(self.config.dataset_id, safe="")
        if self.config.proxy_base_url:
            url = f"{self.config.proxy_base_url.rstrip('/')}/api/datasets/{dataset_id}/documents/create-by-text"
            headers: dict[str, str] = {}
        else:
            if not self.config.base_url:
                raise ValueError("DIFY_BASE_URL or DIFY_PROXY_BASE_URL is required")
            if not self.config.dataset_api_key:
                raise ValueError("DIFY_DATASET_API_KEY is required when DIFY_PROXY_BASE_URL is not set")
            url = f"{self.config.base_url.rstrip('/')}/v1/datasets/{dataset_id}/document/create-by-text"
            headers = {"Authorization": f"Bearer {self.config.dataset_api_key}"}

        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise RuntimeError("httpx is required for uploading; run `pip install -e .`") from exc

        timeout = httpx.Timeout(
            connect=15.0,
            read=self.config.timeout_seconds,
            write=self.config.timeout_seconds,
            pool=self.config.timeout_seconds,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)

        if response.status_code >= 400:
            detail = _response_detail(response)
            raise RuntimeError(f"Dify upload failed: HTTP {response.status_code}: {detail}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Dify upload failed: response is not JSON") from exc

        doc_id = _extract_document_id(data)
        if not doc_id:
            raise RuntimeError(f"Dify upload failed: cannot find document id in response: {data}")
        return doc_id


def _response_detail(response: Any) -> str:
    try:
        return str(response.json())[:1000]
    except ValueError:
        return response.text[:1000]


def _extract_document_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    candidates: list[Any] = [
        data.get("id"),
        data.get("document_id"),
    ]
    document = data.get("document")
    if isinstance(document, dict):
        candidates.extend([document.get("id"), document.get("document_id")])
    data_obj = data.get("data")
    if isinstance(data_obj, dict):
        candidates.extend([data_obj.get("id"), data_obj.get("document_id")])
        nested = data_obj.get("document")
        if isinstance(nested, dict):
            candidates.extend([nested.get("id"), nested.get("document_id")])
    for value in candidates:
        if value:
            return str(value)
    return ""
