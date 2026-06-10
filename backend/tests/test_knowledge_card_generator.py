from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class _FakeLLM:
    async def chat(self, *args, **kwargs) -> str:
        return json.dumps(
            [
                {
                    "card_type": "result",
                    "title": "Robustness improves on ImageNet and COCO",
                    "content": "The method improves robustness on ImageNet and COCO benchmarks.",
                    "source_page": 3,
                    "source_quote": "The method improves robustness on ImageNet and COCO benchmarks.",
                    "confidence": 0.91,
                    "tags": ["robustness", "benchmark"],
                    "source_ref": "evidence:E01",
                    "why_useful": "Useful as cited result evidence for robustness comparisons.",
                    "use_case": "writing",
                    "next_action": "Use this result as a comparison point in related work or experiments.",
                    "risk_or_caveat": "Only reuse after checking the exact benchmark setup.",
                },
                {
                    "card_type": "result",
                    "title": "Unsupported hallucinated result",
                    "content": "The model beats every baseline.",
                    "source_page": 9,
                    "source_quote": "The model beats every baseline.",
                    "confidence": 0.88,
                    "tags": ["bad"],
                    "source_ref": "evidence:E02",
                },
            ]
        )


class KnowledgeCardGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self._tmp.name
        os.environ["AUTO_KNOWLEDGE_CARDS_ENABLED"] = "true"

        from app.config import get_settings

        get_settings.cache_clear()

        from fastapi.testclient import TestClient
        from app.main import app

        self._client_cm = TestClient(app)
        self.client = self._client_cm.__enter__()
        self.db_file = Path(self._tmp.name) / "app.db"
        self._seed()

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)
        for key in ("DATA_DIR", "AUTO_KNOWLEDGE_CARDS_ENABLED"):
            os.environ.pop(key, None)
        from app.config import get_settings

        get_settings.cache_clear()
        self._tmp.cleanup()

    def _seed(self) -> None:
        con = sqlite3.connect(self.db_file)
        con.execute(
            """
            INSERT INTO papers (paper_id, file_path, title, venue, year, reading_status, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("paper1", "papers/paper1/original.pdf", "Vision Benchmark Paper", "ICML", 2024, "read", "medium"),
        )
        con.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) VALUES (?, ?, ?, ?, ?, ?)",
            ("paper1", "text", 2, "The method improves robustness on ImageNet and COCO benchmarks.", "Results", 1),
        )
        con.execute(
            """
            INSERT INTO runs (run_id, paper_id, mode, llm_model, language, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("run1", "paper1", "snap", "fake-model", "en", "done"),
        )
        con.execute(
            "INSERT INTO run_outputs (run_id, markdown, json_data) VALUES (?, ?, ?)",
            (
                "run1",
                "The method improves robustness on ImageNet and COCO benchmarks. [p.3]",
                json.dumps(
                    {
                        "evidence_pool": [
                            {
                                "id": "E01",
                                "page": 3,
                                "slot": "result",
                                "quote": "The method improves robustness on ImageNet and COCO benchmarks.",
                                "paraphrase": "robustness gain",
                            }
                        ]
                    }
                ),
            ),
        )
        con.commit()
        con.close()

    def test_generate_cards_for_run_creates_traceable_ai_drafts_and_dedupes(self) -> None:
        with patch("app.services.knowledge_card_generator.get_llm_service", return_value=_FakeLLM()):
            resp = self.client.post("/api/knowledge/cards/generate", json={"run_id": "run1", "max_cards": 5})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["cards_created"], 1)
        self.assertEqual(body["cards_skipped"], 1)

        cards = self.client.get("/api/knowledge/cards?created_by=ai&status=draft&run_id=run1").json()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["created_by"], "ai")
        self.assertEqual(cards[0]["source_page"], 3)
        self.assertEqual(cards[0]["source_kind"], "evidence_pool")
        self.assertEqual(cards[0]["asset_level"], "action")
        self.assertEqual(cards[0]["action_type"], "writing")
        self.assertIn("comparison", cards[0]["next_action"])
        self.assertIn("robustness", cards[0]["tags"])

        with patch("app.services.knowledge_card_generator.get_llm_service", return_value=_FakeLLM()):
            again = self.client.post("/api/knowledge/cards/generate", json={"run_id": "run1", "max_cards": 5})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["generation_id"], body["generation_id"])
        self.assertEqual(len(self.client.get("/api/knowledge/cards?created_by=ai&status=draft&run_id=run1").json()), 1)

    def test_verified_factual_card_requires_traceable_source(self) -> None:
        card = self.client.post(
            "/api/knowledge/cards",
            json={
                "card_type": "result",
                "title": "No source",
                "content": "A result without traceable source.",
                "paper_id": "paper1",
                "status": "draft",
            },
        )
        self.assertEqual(card.status_code, 200, card.text)
        card_id = card.json()["card_id"]
        failed = self.client.patch(f"/api/knowledge/cards/{card_id}", json={"status": "verified"})
        self.assertEqual(failed.status_code, 400, failed.text)

        ok = self.client.patch(
            f"/api/knowledge/cards/{card_id}",
            json={"status": "verified", "allow_untraceable": True, "reviewed_by": "tester"},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["status"], "verified")
        self.assertEqual(ok.json()["reviewed_by"], "tester")

    def test_batch_status_rejects_untraceable_verified_cards(self) -> None:
        card = self.client.post(
            "/api/knowledge/cards",
            json={
                "card_type": "result",
                "title": "No source",
                "content": "A result without traceable source.",
                "paper_id": "paper1",
            },
        ).json()
        failed = self.client.patch(
            "/api/knowledge/cards/batch-status",
            json={"card_ids": [card["card_id"]], "status": "verified"},
        )
        self.assertEqual(failed.status_code, 400, failed.text)
        ok = self.client.patch(
            "/api/knowledge/cards/batch-status",
            json={"card_ids": [card["card_id"]], "status": "rejected"},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()[0]["status"], "rejected")
