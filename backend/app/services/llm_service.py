from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, AsyncIterator

import httpx

from app.services.http_clients import get_llm_http_client
from app.services.llm_runtime_config import get_llm_runtime_config

logger = logging.getLogger("scholar.llm")

# Maximum timeout cap for any single LLM request (seconds)
_TIMEOUT_CAP = 900.0


class EmptyLLMResponseError(RuntimeError):
    """Raised when an LLM request succeeds but contains no assistant text."""


class LLMService:
    """Async Qwen Responses API client with retry and backoff."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        max_retries: int = 5,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ):
        runtime_config = get_llm_runtime_config()
        self.base_url = (base_url or runtime_config.base_url).rstrip("/")
        self.api_key = api_key or runtime_config.api_key
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    @staticmethod
    def _is_retryable(status_code: int) -> bool:
        # 502/504 from the upstream LLM gateway usually mean the request already
        # exceeded the provider-side generation window. Retrying the same large
        # prompt only repeats the timeout and blocks the run for minutes.
        return status_code in {408, 429, 500, 503}

    def _compute_delay(self, attempt: int) -> float:
        delay = min(self.retry_base_delay * (2 ** attempt), self.retry_max_delay)
        jitter = random.uniform(0.8, 1.2)
        return delay * jitter

    @staticmethod
    def _compute_read_timeout(prompt_chars: int) -> float:
        """Compute read timeout that accounts for prompt size and open-ended output."""
        # prompt_chars/4 ≈ rough token estimate; each prompt token adds ~0.02s processing
        timeout = 240.0 + (prompt_chars / 4) * 0.02
        return min(max(180.0, timeout), _TIMEOUT_CAP)

    def _http_client(self) -> httpx.AsyncClient:
        return self._client or get_llm_http_client()

    @staticmethod
    def _extract_response_text(data: dict[str, Any]) -> str:
        content = ""
        if isinstance(data.get("output_text"), str):
            content += data["output_text"]
        for item in data.get("output", []) or []:
            if item.get("type") != "message":
                continue
            for part in item.get("content", []) or []:
                if part.get("type") in {"output_text", "text"}:
                    content += part.get("text", "")
            break
        return content

    @staticmethod
    def _extract_chat_completion_text(data: dict[str, Any]) -> str:
        content = ""
        for choice in data.get("choices", []) or []:
            message = choice.get("message") or {}
            text = message.get("content")
            if isinstance(text, str):
                content += text
        return content

    async def _chat_completions_fallback(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        timeout: httpx.Timeout,
    ) -> tuple[str, dict[str, Any], float]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        t_req = time.perf_counter()
        resp = await self._http_client().post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )
        req_elapsed = time.perf_counter() - t_req
        resp.raise_for_status()
        data = resp.json()
        return self._extract_chat_completion_text(data), data, req_elapsed

    async def _responses_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        reasoning_effort: str,
        timeout: httpx.Timeout,
    ) -> tuple[str, dict[str, Any], float]:
        payload: dict[str, Any] = {
            "model": model,
            "input": messages,
            "temperature": temperature,
            "reasoning": {"effort": reasoning_effort},
        }
        t_req = time.perf_counter()
        resp = await self._http_client().post(
            f"{self.base_url}/responses",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )
        req_elapsed = time.perf_counter() - t_req
        resp.raise_for_status()
        data = resp.json()
        return self._extract_response_text(data), data, req_elapsed

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float = 0.3,
    ) -> str:
        """Send a chat completion request, return assistant content."""
        runtime_config = get_llm_runtime_config()
        # THINKING_MODELNAME may be a comma-separated list; the first entry is
        # the default when the caller does not pick a specific model.
        model = model or runtime_config.default_thinking_model

        # Scale timeout with expected output size + prompt size
        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        base_read_timeout = self._compute_read_timeout(prompt_chars)

        logger.info(
            f"LLM responses: model={model} reasoning={runtime_config.reasoning_effort} "
            f"prompt={prompt_chars} chars timeout={base_read_timeout:.0f}s"
        )
        t0 = time.perf_counter()

        attempt = 0
        timeout_escalations = 0
        connect_failures = 0
        while True:
            attempt += 1
            # Progressive timeout escalation: multiply base by 1.5^n on ReadTimeout retries
            read_timeout = min(
                base_read_timeout * (1.5 ** timeout_escalations),
                _TIMEOUT_CAP,
            )
            try:
                timeout = httpx.Timeout(
                    connect=30.0, read=read_timeout, write=30.0, pool=30.0,
                )
                content, data, req_elapsed = await self._responses_completion(
                    messages,
                    model=model,
                    temperature=temperature,
                    reasoning_effort=runtime_config.reasoning_effort,
                    timeout=timeout,
                )
                if not content:
                    raise EmptyLLMResponseError(
                        "LLM returned empty assistant content from /responses"
                    )
                total_elapsed = time.perf_counter() - t0

                # Log usage if available
                usage = data.get("usage", {})
                prompt_tokens = usage.get("input_tokens", usage.get("prompt_tokens", "?"))
                completion_tokens = usage.get("output_tokens", usage.get("completion_tokens", "?"))
                logger.info(
                    f"LLM responses: DONE in {total_elapsed:.1f}s (http={req_elapsed:.1f}s) — "
                    f"tokens={prompt_tokens}+{completion_tokens} response={len(content)} chars"
                )
                return content

            except httpx.ReadTimeout as e:
                req_elapsed = time.perf_counter() - t0
                if attempt > self.max_retries:
                    logger.error(
                        f"LLM chat: ReadTimeout FAILED after {attempt} attempts "
                        f"in {time.perf_counter()-t0:.1f}s — {e}"
                    )
                    raise
                timeout_escalations += 1
                new_timeout = min(
                    base_read_timeout * (1.5 ** timeout_escalations),
                    _TIMEOUT_CAP,
                )
                delay = self._compute_delay(attempt)
                logger.warning(
                    f"LLM chat: ReadTimeout after {req_elapsed:.0f}s "
                    f"(attempt {attempt}/{self.max_retries}), "
                    f"escalating timeout to {new_timeout:.0f}s, retry in {delay:.1f}s"
                )
                await asyncio.sleep(delay)

            except httpx.ConnectError as e:
                connect_failures += 1
                if connect_failures >= 2 or attempt > self.max_retries:
                    logger.error(
                        f"LLM chat: ConnectError giving up after {connect_failures} connect failures "
                        f"in {time.perf_counter()-t0:.1f}s — {e}"
                    )
                    raise
                delay = self._compute_delay(attempt)
                logger.warning(
                    f"LLM chat: ConnectError (attempt {attempt}/{self.max_retries}), "
                    f"retry in {delay:.1f}s — {e}"
                )
                await asyncio.sleep(delay)

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if not self._is_retryable(status_code):
                    logger.error(
                        f"LLM chat: HTTP {status_code} not retryable; failed after "
                        f"{attempt} attempt(s) in {time.perf_counter()-t0:.1f}s — {e}"
                    )
                    raise
                if attempt > self.max_retries:
                    logger.error(
                        f"LLM chat: HTTPStatusError FAILED after {attempt} attempts "
                        f"in {time.perf_counter()-t0:.1f}s — {e}"
                    )
                    raise
                delay = self._compute_delay(attempt)
                logger.warning(
                    f"LLM chat: {type(e).__name__} (attempt {attempt}/{self.max_retries}), "
                    f"retry in {delay:.1f}s — {e}"
                )
                await asyncio.sleep(delay)

            except EmptyLLMResponseError as e:
                if attempt > self.max_retries:
                    logger.error(
                        f"LLM chat: empty response FAILED after {attempt} attempts "
                        f"in {time.perf_counter()-t0:.1f}s — {e}"
                    )
                    raise
                delay = self._compute_delay(attempt)
                logger.warning(
                    f"LLM chat: empty response (attempt {attempt}/{self.max_retries}), "
                    f"retry in {delay:.1f}s — {e}"
                )
                await asyncio.sleep(delay)

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens."""
        runtime_config = get_llm_runtime_config()
        # THINKING_MODELNAME may be a comma-separated list; the first entry is
        # the default when the caller does not pick a specific model.
        model = model or runtime_config.default_thinking_model

        payload: dict[str, Any] = {
            "model": model,
            "input": messages,
            "temperature": temperature,
            "stream": True,
            "reasoning": {"effort": runtime_config.reasoning_effort},
        }

        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        read_timeout = self._compute_read_timeout(prompt_chars)
        logger.info(
            f"LLM stream: model={model} reasoning={runtime_config.reasoning_effort} "
            f"prompt={prompt_chars} chars timeout={read_timeout:.0f}s"
        )
        t0 = time.perf_counter()
        token_count = 0

        timeout = httpx.Timeout(connect=30.0, read=read_timeout, write=30.0, pool=30.0)
        async with self._http_client().stream(
            "POST",
            f"{self.base_url}/responses",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                event_type = chunk.get("type", "")
                if event_type == "response.output_text.delta":
                    content = chunk.get("delta", "")
                    if content:
                        token_count += 1
                        yield content
                elif event_type == "response.completed":
                    break

        logger.info(f"LLM stream: DONE in {time.perf_counter()-t0:.1f}s — {token_count} chunks")


def get_llm_service() -> LLMService:
    return LLMService()
