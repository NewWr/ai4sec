from __future__ import annotations

import os
import json
import tempfile
import unittest

from pathlib import Path

import httpx

from app.services.llm_service import LLMService


class LLMServiceParsingTests(unittest.TestCase):
    def test_extracts_responses_output_text(self) -> None:
        data = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "hello"},
                    ],
                },
            ],
        }

        self.assertEqual(LLMService._extract_response_text(data), "hello")

    def test_extracts_top_level_output_text(self) -> None:
        self.assertEqual(
            LLMService._extract_response_text({"output_text": "hello"}),
            "hello",
        )

    def test_extracts_chat_completion_text(self) -> None:
        data = {
            "choices": [
                {"message": {"role": "assistant", "content": "你好"}},
            ],
        }

        self.assertEqual(LLMService._extract_chat_completion_text(data), "你好")


class LLMRuntimeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self._tmp.name
        os.environ["LLM_BASEURL"] = "https://env.example/v1"
        os.environ["LLM_APIKEY"] = "env-secret"
        os.environ["THINKING_MODELNAME"] = "env-model"
        from app.config import get_settings

        get_settings.cache_clear()

    def tearDown(self) -> None:
        for key in ("DATA_DIR", "LLM_BASEURL", "LLM_APIKEY", "THINKING_MODELNAME"):
            os.environ.pop(key, None)
        from app.config import get_settings

        get_settings.cache_clear()
        self._tmp.cleanup()

    def test_runtime_config_overrides_env_without_exposing_key(self) -> None:
        from app.services.llm_runtime_config import llm_config_response, update_llm_runtime_config

        data = update_llm_runtime_config(
            base_url="https://runtime.example/v1/",
            thinking_model="model-a,model-b",
            reasoning_effort="xhigh",
            api_key="runtime-secret-1234",
        )

        self.assertEqual(data["base_url"], "https://runtime.example/v1")
        self.assertEqual(data["models"], ["model-a", "model-b"])
        self.assertEqual(data["reasoning_effort"], "xhigh")
        self.assertTrue(data["api_key_configured"])
        self.assertEqual(data["api_key_suffix"], "1234")
        self.assertNotIn("runtime-secret", str(data))

        service = LLMService()
        self.assertEqual(service.base_url, "https://runtime.example/v1")
        self.assertEqual(service.api_key, "runtime-secret-1234")

        stored = Path(self._tmp.name, "llm_runtime_config.json").read_text(encoding="utf-8")
        self.assertIn("runtime-secret-1234", stored)
        self.assertIn('"reasoning_effort": "xhigh"', stored)
        self.assertEqual(llm_config_response()["default"], "model-a")

    def test_connection_probe_masks_api_key_on_failure(self) -> None:
        import asyncio

        from app.services.llm_runtime_config import LLMRuntimeConfig, test_llm_connection

        async def _run() -> dict[str, object]:
            def handler(request: httpx.Request) -> httpx.Response:
                self.assertEqual(request.headers["authorization"], "Bearer runtime-secret-1234")
                self.assertEqual(request.url.path, "/v1/responses")
                payload = json.loads(request.content.decode("utf-8"))
                self.assertEqual(payload["reasoning"]["effort"], "high")
                self.assertNotIn("max_output_tokens", payload)
                return httpx.Response(403, text="bad runtime-secret-1234")

            transport = httpx.MockTransport(handler)
            original = httpx.AsyncClient

            class MockedAsyncClient(httpx.AsyncClient):
                def __init__(self, *args, **kwargs):
                    kwargs["transport"] = transport
                    super().__init__(*args, **kwargs)

            httpx.AsyncClient = MockedAsyncClient
            try:
                return await test_llm_connection(
                    LLMRuntimeConfig(
                        base_url="https://runtime.example/v1",
                        api_key="runtime-secret-1234",
                        thinking_model="model-a",
                        reasoning_effort="high",
                    )
                )
            finally:
                httpx.AsyncClient = original

        data = asyncio.run(_run())
        self.assertFalse(data["ok"])
        self.assertEqual(data["status_code"], 403)
        self.assertIn("[redacted]", str(data["error"]))
        self.assertNotIn("runtime-secret-1234", str(data))

    def test_chat_uses_responses_with_reasoning_effort(self) -> None:
        import asyncio

        from app.services.llm_runtime_config import update_llm_runtime_config

        requests: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append({"path": request.url.path, "json": json.loads(request.content.decode("utf-8"))})
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "ok"}],
                        }
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )

        update_llm_runtime_config(
            base_url="https://runtime.example/v1",
            thinking_model="model-a",
            reasoning_effort="xhigh",
            api_key="runtime-secret-1234",
        )
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = asyncio.run(
                LLMService(client=client).chat(
                    [{"role": "user", "content": "hello"}],
                )
            )
        finally:
            asyncio.run(client.aclose())

        self.assertEqual(result, "ok")
        self.assertEqual(requests[0]["path"], "/v1/responses")
        payload = requests[0]["json"]
        self.assertEqual(payload["model"], "model-a")
        self.assertEqual(payload["reasoning"], {"effort": "xhigh"})
        self.assertNotIn("max_output_tokens", payload)

    def test_chat_does_not_retry_gateway_timeouts(self) -> None:
        import asyncio

        from app.services.llm_runtime_config import update_llm_runtime_config

        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            return httpx.Response(504, request=request, text="gateway timeout")

        update_llm_runtime_config(
            base_url="https://runtime.example/v1",
            thinking_model="model-a",
            reasoning_effort="medium",
            api_key="runtime-secret-1234",
        )
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(httpx.HTTPStatusError):
                asyncio.run(
                    LLMService(client=client, max_retries=5).chat(
                        [{"role": "user", "content": "hello"}],
                    )
                )
        finally:
            asyncio.run(client.aclose())

        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
