from __future__ import annotations

import os
import tempfile
import unittest


class SettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self._tmp.name
        os.environ["LLM_BASEURL"] = "https://env.example/v1"
        os.environ["LLM_APIKEY"] = "env-secret"
        os.environ["THINKING_MODELNAME"] = "env-model"
        os.environ["DAILY_RECOMMENDATION_AUTO_REFRESH_ENABLED"] = "false"

        from app.config import get_settings

        get_settings.cache_clear()

        from fastapi.testclient import TestClient
        from app.main import app

        self._client_cm = TestClient(app)
        self.client = self._client_cm.__enter__()

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)
        for key in (
            "DATA_DIR",
            "LLM_BASEURL",
            "LLM_APIKEY",
            "THINKING_MODELNAME",
            "DAILY_RECOMMENDATION_AUTO_REFRESH_ENABLED",
        ):
            os.environ.pop(key, None)
        from app.config import get_settings

        get_settings.cache_clear()
        self._tmp.cleanup()

    def test_update_llm_settings_updates_models_and_masks_key(self) -> None:
        before = self.client.get("/api/settings/llm")
        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual(before.json()["source"], "env")

        saved = self.client.patch(
            "/api/settings/llm",
            json={
                "base_url": "https://runtime.example/v1/",
                "thinking_model": "model-a,model-b",
                "reasoning_effort": "xhigh",
                "api_key": "runtime-secret-5678",
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        data = saved.json()
        self.assertEqual(data["base_url"], "https://runtime.example/v1")
        self.assertEqual(data["models"], ["model-a", "model-b"])
        self.assertEqual(data["default"], "model-a")
        self.assertEqual(data["reasoning_effort"], "xhigh")
        self.assertIn("xhigh", data["reasoning_efforts"])
        self.assertEqual(data["api_key_suffix"], "5678")
        self.assertNotIn("runtime-secret", saved.text)

        models = self.client.get("/api/models")
        self.assertEqual(models.status_code, 200, models.text)
        self.assertEqual(models.json(), {"models": ["model-a", "model-b"], "default": "model-a"})

    def test_update_daily_topics_persists_without_docker_rebuild(self) -> None:
        saved = self.client.put(
            "/api/settings/daily-topics",
            json={
                "topics": [
                    {
                        "topic_id": "custom_security",
                        "name": "Custom Security",
                        "name_zh": "自定义安全方向",
                        "enabled": True,
                        "sort_order": 5,
                        "config": {
                            "arxiv_categories": ["cs.CR", "cs.AI"],
                            "must": {"any": [["watermark"], ["backdoor", "detection"]]},
                            "should": ["diffusion", "llm"],
                            "exclude": ["quantum"],
                            "min_score": 0.6,
                        },
                    }
                ]
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        data = saved.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["topic_id"], "custom_security")
        self.assertEqual(data[0]["config"]["must"], {"any": [["watermark"], ["backdoor", "detection"]]})

        topics = self.client.get("/api/daily/topics")
        self.assertEqual(topics.status_code, 200, topics.text)
        topic_ids = {topic["topic_id"] for topic in topics.json()}
        self.assertEqual(topic_ids, {"custom_security"})


if __name__ == "__main__":
    unittest.main()
