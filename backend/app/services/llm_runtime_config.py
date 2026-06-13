from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings

CONFIG_FILE = "llm_runtime_config.json"
REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
DEFAULT_REASONING_EFFORT = "medium"


@dataclass(frozen=True)
class LLMRuntimeConfig:
    base_url: str
    api_key: str
    thinking_model: str
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    source: str = "env"

    @property
    def thinking_models(self) -> list[str]:
        return [model.strip() for model in self.thinking_model.split(",") if model.strip()]

    @property
    def default_thinking_model(self) -> str:
        models = self.thinking_models
        return models[0] if models else ""


def _config_path() -> Path:
    return get_settings().data_dir / CONFIG_FILE


def _mask_key(api_key: str) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, ""
    return True, key[-4:] if len(key) >= 4 else "****"


def get_llm_runtime_config() -> LLMRuntimeConfig:
    settings = get_settings()
    config = LLMRuntimeConfig(
        base_url=settings.llm_base_url.strip().rstrip("/"),
        api_key=settings.llm_api_key.strip(),
        thinking_model=settings.thinking_model.strip(),
        reasoning_effort=DEFAULT_REASONING_EFFORT,
        source="env",
    )
    path = _config_path()
    if not path.exists():
        return config
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return config
    if not isinstance(data, dict):
        return config
    return LLMRuntimeConfig(
        base_url=str(data.get("base_url") or config.base_url).strip().rstrip("/"),
        api_key=str(data.get("api_key") or config.api_key).strip(),
        thinking_model=str(data.get("thinking_model") or config.thinking_model).strip(),
        reasoning_effort=_clean_reasoning_effort(str(data.get("reasoning_effort") or config.reasoning_effort)),
        source="runtime",
    )


def _clean_reasoning_effort(value: str) -> str:
    effort = (value or "").strip().lower()
    if effort not in REASONING_EFFORTS:
        return DEFAULT_REASONING_EFFORT
    return effort


def llm_config_response() -> dict[str, object]:
    config = get_llm_runtime_config()
    key_configured, key_suffix = _mask_key(config.api_key)
    return {
        "base_url": config.base_url,
        "thinking_model": config.thinking_model,
        "models": config.thinking_models,
        "default": config.default_thinking_model,
        "reasoning_effort": config.reasoning_effort,
        "reasoning_efforts": sorted(REASONING_EFFORTS, key=("none", "minimal", "low", "medium", "high", "xhigh").index),
        "api_key_configured": key_configured,
        "api_key_suffix": key_suffix,
        "source": config.source,
    }


def update_llm_runtime_config(
    *,
    base_url: str,
    thinking_model: str,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    api_key: str | None = None,
    clear_api_key: bool = False,
) -> dict[str, object]:
    current = get_llm_runtime_config()
    next_key = "" if clear_api_key else current.api_key
    if api_key is not None and api_key.strip():
        next_key = api_key.strip()

    data = {
        "base_url": (base_url or "").strip().rstrip("/"),
        "api_key": next_key,
        "thinking_model": (thinking_model or "").strip(),
        "reasoning_effort": _clean_reasoning_effort(reasoning_effort),
    }
    if not data["base_url"]:
        raise ValueError("LLM base_url must not be empty")
    if not data["thinking_model"]:
        raise ValueError("thinking_model must not be empty")

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return llm_config_response()


def resolve_test_config(
    *,
    base_url: str,
    thinking_model: str,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    api_key: str = "",
    clear_api_key: bool = False,
    use_saved_api_key: bool = True,
) -> LLMRuntimeConfig:
    current = get_llm_runtime_config()
    next_key = ""
    if use_saved_api_key and not clear_api_key:
        next_key = current.api_key
    if api_key.strip():
        next_key = api_key.strip()
    return LLMRuntimeConfig(
        base_url=(base_url or "").strip().rstrip("/"),
        api_key=next_key,
        thinking_model=(thinking_model or "").strip(),
        reasoning_effort=_clean_reasoning_effort(reasoning_effort),
        source="test",
    )


def _extract_probe_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()
    for item in data.get("output", []) or []:
        for part in item.get("content", []) or []:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    for choice in data.get("choices", []) or []:
        message = choice.get("message") or {}
        text = message.get("content")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _safe_error(exc: Exception, *, api_key: str) -> str:
    text = str(exc)[:800]
    if api_key:
        text = text.replace(api_key, "[redacted]")
    return text


def _should_try_next_probe(endpoint: str, status_code: int, body: str) -> bool:
    if status_code in {404, 405, 422}:
        return True
    if endpoint.startswith("responses") and status_code == 400:
        lowered = body.lower()
        return any(token in lowered for token in ("reasoning", "unsupported", "unknown", "parameter", "responses"))
    return False


async def test_llm_connection(config: LLMRuntimeConfig) -> dict[str, object]:
    if not config.base_url:
        raise ValueError("LLM base_url must not be empty")
    if not config.default_thinking_model:
        raise ValueError("thinking_model must not be empty")
    if not config.api_key:
        raise ValueError("API key must not be empty")

    model = config.default_thinking_model
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    responses_payload = {
        "model": model,
        "input": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
        "reasoning": {"effort": config.reasoning_effort},
    }
    responses_plain_payload = {
        "model": model,
        "input": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
    }
    chat_payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
    }
    timeout = httpx.Timeout(connect=8.0, read=20.0, write=8.0, pool=8.0)
    attempts = [
        ("responses", f"{config.base_url}/responses", responses_payload),
        ("responses-plain", f"{config.base_url}/responses", responses_plain_payload),
        ("chat/completions", f"{config.base_url}/chat/completions", chat_payload),
    ]
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for index, (endpoint, url, payload) in enumerate(attempts):
            started = time.perf_counter()
            try:
                resp = await client.post(url, headers=headers, json=payload)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                body = resp.text[:800].replace(config.api_key, "[redacted]")
                if index < len(attempts) - 1 and _should_try_next_probe(endpoint, resp.status_code, body):
                    errors.append(f"{endpoint}: HTTP {resp.status_code} {body[:240]}")
                    continue
                if resp.status_code >= 400:
                    return {
                        "ok": False,
                        "base_url": config.base_url,
                        "model": model,
                        "endpoint": endpoint,
                        "status_code": resp.status_code,
                        "elapsed_ms": elapsed_ms,
                        "message": "",
                        "error": body,
                    }
                data = resp.json()
                text = _extract_probe_text(data)
                return {
                    "ok": True,
                    "base_url": config.base_url,
                    "model": model,
                    "endpoint": endpoint,
                    "status_code": resp.status_code,
                    "elapsed_ms": elapsed_ms,
                    "message": text[:200] or "connected",
                    "error": "",
                }
            except Exception as exc:
                errors.append(f"{endpoint}: {_safe_error(exc, api_key=config.api_key)}")
    return {
        "ok": False,
        "base_url": config.base_url,
        "model": model,
        "endpoint": "",
        "status_code": 0,
        "elapsed_ms": 0,
        "message": "",
        "error": "；".join(errors)[:800],
    }
