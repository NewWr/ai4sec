from __future__ import annotations

import unittest
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db import database as db
from app.services import corpus_qa
from app.services import knowledge_assets as assets


_RECORDS = [
    {
        "document_id": "d1",
        "document_name": "BadCLIP_CVPR_2024.md",
        "segment_id": "s1",
        "content": "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP.",
        "score": 0.95,
    },
    {
        "document_id": "d2",
        "document_name": "BadT2I.md",
        "segment_id": "s2",
        "content": "BadT2I backdoors text-to-image diffusion via multimodal data poisoning.",
        "score": 0.81,
    },
]


class CorpusQaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        try:
            await db.close_db()
        except Exception:
            pass

    async def asyncTearDown(self) -> None:
        try:
            await db.close_db()
        except Exception:
            pass

    async def _init_empty_db(self, tmp: str) -> None:
        db.set_db_path(Path(tmp) / "app.db")
        await db.init_db()

    async def test_answer_builds_cited_context_and_sources(self) -> None:
        chat = AsyncMock(return_value="BadCLIP attacks CLIP [L1].")
        with tempfile.TemporaryDirectory() as tmp:
            await self._init_empty_db(tmp)
            with patch(
                "app.services.dify_client.search_records",
                new=AsyncMock(return_value=_RECORDS),
            ), patch("app.services.corpus_qa.get_llm_service") as gls:
                gls.return_value.chat = chat
                result = await corpus_qa.answer_corpus_question(
                    "What is BadCLIP?", search_method="full_text_search", language="en"
                )

        self.assertEqual(result["markdown"], "BadCLIP attacks CLIP [L1].")
        self.assertEqual(result["blocks_used"], 2)
        self.assertEqual([s["idx"] for s in result["sources"]], [1, 2])
        self.assertEqual(result["sources"][0]["document_id"], "d1")
        self.assertEqual(result["sources"][0]["segment_id"], "s1")

        # The context handed to the LLM is numbered [L1]/[L2] with source names.
        messages = chat.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        self.assertIn("[L1]", user_content)
        self.assertIn("[L2]", user_content)
        self.assertIn("BadCLIP_CVPR_2024.md", user_content)
        # English prompt selected.
        self.assertEqual(messages[0]["content"], corpus_qa._SYSTEM_PROMPT_EN)

    async def test_no_records_skips_llm(self) -> None:
        chat = AsyncMock(return_value="should not be called")
        with tempfile.TemporaryDirectory() as tmp:
            await self._init_empty_db(tmp)
            with patch(
                "app.services.dify_client.search_records",
                new=AsyncMock(return_value=[]),
            ), patch("app.services.corpus_qa.get_llm_service") as gls:
                gls.return_value.chat = chat
                result = await corpus_qa.answer_corpus_question(
                    "obscure question", search_method="full_text_search", language="en"
                )

        self.assertEqual(result["sources"], [])
        self.assertEqual(result["blocks_used"], 0)
        chat.assert_not_called()

    async def test_graph_only_skips_dify_and_answers_from_local_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db.set_db_path(Path(tmp) / "app.db")
            await db.init_db()
            await db.execute(
                "INSERT INTO papers (paper_id, file_path, title) VALUES (?, ?, ?)",
                ("paper1", "papers/paper1/original.pdf", "CLIP Prompt Paper"),
            )
            card = await assets.create_card(
                {
                    "card_type": "method",
                    "title": "BadCLIP trigger-aware prompt learning",
                    "content": "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP.",
                    "paper_id": "paper1",
                    "source_quote": "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP.",
                    "status": "verified",
                    "confidence": 0.9,
                    "allow_untraceable": True,
                }
            )
            search_records = AsyncMock(return_value=_RECORDS)
            chat = AsyncMock(return_value="BadCLIP attacks CLIP [L1].")
            with patch("app.services.dify_client.search_records", new=search_records), patch(
                "app.services.corpus_qa.get_llm_service"
            ) as gls:
                gls.return_value.chat = chat
                result = await corpus_qa.answer_corpus_question(
                    "BadCLIP CLIP",
                    language="en",
                    graph_only=True,
                )
            event = await db.fetch_one("SELECT * FROM library_qa_events ORDER BY created_at DESC LIMIT 1")

        search_records.assert_not_called()
        self.assertEqual(result["search_method"], "graph_only")
        self.assertEqual(result["sources"][0]["source_type"], "knowledge_graph")
        self.assertEqual(result["sources"][0]["card_id"], card["card_id"])
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["search_method"], "graph_only")
        self.assertEqual(event["graph_sources"], 1)

    async def test_dify_error_falls_back_to_local_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db.set_db_path(Path(tmp) / "app.db")
            await db.init_db()
            await db.execute(
                "INSERT INTO papers (paper_id, file_path, title) VALUES (?, ?, ?)",
                ("paper1", "papers/paper1/original.pdf", "CLIP Prompt Paper"),
            )
            await assets.create_card(
                {
                    "card_type": "method",
                    "title": "BadCLIP trigger-aware prompt learning",
                    "content": "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP.",
                    "paper_id": "paper1",
                    "source_quote": "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP.",
                    "status": "verified",
                    "confidence": 0.9,
                    "allow_untraceable": True,
                }
            )
            chat = AsyncMock(return_value="BadCLIP attacks CLIP [L1].")
            with patch(
                "app.services.corpus_qa.get_settings",
                return_value=SimpleNamespace(dify_enabled=True, dify_search_method="keyword_search"),
            ), patch(
                "app.services.dify_client.search_records",
                new=AsyncMock(side_effect=corpus_qa.dify_client.DifyError("down", upstream_status=502)),
            ), patch("app.services.corpus_qa.get_llm_service") as gls:
                gls.return_value.chat = chat
                result = await corpus_qa.answer_corpus_question("BadCLIP CLIP", language="en")

        self.assertEqual(result["search_method"], "graph_fallback")
        self.assertTrue(result["sources"])
        self.assertTrue(all(src["source_type"] != "dify" for src in result["sources"]))

    async def test_chinese_language_selects_zh_prompt(self) -> None:
        chat = AsyncMock(return_value="答案 [L1]。")
        with tempfile.TemporaryDirectory() as tmp:
            await self._init_empty_db(tmp)
            with patch(
                "app.services.dify_client.search_records",
                new=AsyncMock(return_value=_RECORDS),
            ), patch("app.services.corpus_qa.get_llm_service") as gls:
                gls.return_value.chat = chat
                await corpus_qa.answer_corpus_question(
                    "什么是 BadCLIP?", search_method="full_text_search", language="zh"
                )

        messages = chat.call_args.kwargs["messages"]
        self.assertEqual(messages[0]["content"], corpus_qa._SYSTEM_PROMPT_ZH)
        self.assertIn("问题:", messages[1]["content"])

    async def test_multi_dataset_retrieval_preserves_dataset_ids(self) -> None:
        records = [
            {**_RECORDS[0], "dataset_id": "ds1"},
            {**_RECORDS[1], "dataset_id": "ds2"},
        ]
        search_multi = AsyncMock(return_value=records)
        chat = AsyncMock(return_value="BadCLIP attacks CLIP [L1] and BadT2I [L2].")
        with tempfile.TemporaryDirectory() as tmp:
            await self._init_empty_db(tmp)
            with patch(
                "app.services.corpus_qa.get_settings",
                return_value=SimpleNamespace(dify_enabled=True, dify_search_method="keyword_search"),
            ), patch(
                "app.services.dify_client.search_records_multi",
                new=search_multi,
            ), patch(
                "app.services.dify_client.search_records",
                new=AsyncMock(return_value=[]),
            ) as search_one, patch("app.services.corpus_qa.get_llm_service") as gls:
                gls.return_value.chat = chat
                result = await corpus_qa.answer_corpus_question(
                    "BadCLIP and BadT2I",
                    search_method="keyword_search",
                    language="en",
                    dataset_ids=["ds1", "ds2"],
                )

        search_multi.assert_awaited_once()
        self.assertEqual(search_multi.await_args.kwargs["dataset_ids"], ["ds1", "ds2"])
        search_one.assert_not_awaited()
        self.assertEqual(result["search_method"], "keyword_search:multi_dataset")
        self.assertEqual([source["dataset_id"] for source in result["sources"]], ["ds1", "ds2"])

    async def test_blank_passages_are_skipped(self) -> None:
        records = [
            {"document_id": "d1", "document_name": "A.md", "segment_id": "s1", "content": "   ", "score": 0.5},
            {"document_id": "d2", "document_name": "B.md", "segment_id": "s2", "content": "real content", "score": 0.4},
        ]
        chat = AsyncMock(return_value="ok")
        with tempfile.TemporaryDirectory() as tmp:
            await self._init_empty_db(tmp)
            with patch(
                "app.services.dify_client.search_records",
                new=AsyncMock(return_value=records),
            ), patch("app.services.corpus_qa.get_llm_service") as gls:
                gls.return_value.chat = chat
                result = await corpus_qa.answer_corpus_question(
                    "q", search_method="full_text_search", language="en"
                )

        # Only the non-blank passage becomes a source, renumbered to L1.
        self.assertEqual(result["blocks_used"], 1)
        self.assertEqual(result["sources"][0]["document_id"], "d2")
        self.assertEqual(result["sources"][0]["idx"], 1)

    async def test_graph_records_are_fused_before_dify_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db.set_db_path(Path(tmp) / "app.db")
            await db.init_db()
            await db.execute(
                "INSERT INTO papers (paper_id, file_path, title) VALUES (?, ?, ?)",
                ("paper1", "papers/paper1/original.pdf", "CLIP Prompt Paper"),
            )
            await db.execute(
                "INSERT INTO blocks (paper_id, type, page_idx, text, order_idx) VALUES (?, 'text', 0, ?, 1)",
                ("paper1", "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP."),
            )
            card = await assets.create_card(
                {
                    "card_type": "method",
                    "title": "BadCLIP trigger-aware prompt learning",
                    "content": "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP.",
                    "paper_id": "paper1",
                    "source_quote": "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP.",
                    "status": "verified",
                    "confidence": 0.9,
                    "why_useful": "Useful for threat modeling prompt-learning attacks.",
                    "use_case": "writing",
                    "next_action": "Use as local card evidence.",
                    "risk_or_caveat": "Check the exact threat model.",
                }
            )
            chat = AsyncMock(return_value="BadCLIP attacks CLIP [L1].")
            with patch(
                "app.services.dify_client.search_records",
                new=AsyncMock(return_value=_RECORDS),
            ), patch("app.services.corpus_qa.get_llm_service") as gls:
                gls.return_value.chat = chat
                result = await corpus_qa.answer_corpus_question("BadCLIP CLIP", language="en")

            self.assertEqual(result["sources"][0]["source_type"], "knowledge_graph")
            self.assertEqual(result["sources"][0]["card_id"], card["card_id"])
            dify_indexes = [idx for idx, source in enumerate(result["sources"]) if source["source_type"] == "dify"]
            self.assertTrue(dify_indexes)
            self.assertGreater(dify_indexes[0], 0)


class LibraryAskApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self._tmp.name
        os.environ["DIFY_API_BASE"] = ""
        from app.config import get_settings

        get_settings.cache_clear()
        from fastapi.testclient import TestClient
        from app.main import app

        self._client_cm = TestClient(app)
        self.client = self._client_cm.__enter__()
        self.db_file = Path(self._tmp.name) / "app.db"

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)
        os.environ.pop("DATA_DIR", None)
        os.environ.pop("DIFY_API_BASE", None)
        from app.config import get_settings

        get_settings.cache_clear()
        self._tmp.cleanup()

    def _seed_verified_card(self) -> str:
        import sqlite3

        con = sqlite3.connect(self.db_file)
        con.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES (?, ?, ?)",
            ("paper1", "papers/paper1/original.pdf", "CLIP Prompt Paper"),
        )
        con.execute(
            """
            INSERT INTO knowledge_cards (
                card_id, card_type, title, content, paper_id, source_page,
                source_quote, confidence, status, asset_level, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "card1",
                "method",
                "BadCLIP trigger-aware prompt learning",
                "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP.",
                "paper1",
                1,
                "BadCLIP is a trigger-aware prompt-learning backdoor attack on CLIP.",
                0.9,
                "verified",
                "action",
                "high",
            ),
        )
        con.commit()
        con.close()
        return "card1"

    def test_library_ask_allows_local_graph_when_dify_disabled(self) -> None:
        card_id = self._seed_verified_card()
        chat = AsyncMock(return_value="BadCLIP attacks CLIP [L1].")
        with patch("app.services.corpus_qa.get_llm_service") as gls, patch(
            "app.services.dify_client.search_records",
            new=AsyncMock(return_value=_RECORDS),
        ) as search_records:
            gls.return_value.chat = chat
            resp = self.client.post(
                "/api/library/ask",
                json={"question": "BadCLIP CLIP", "language": "en"},
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["search_method"], "graph_only")
        self.assertEqual(body["sources"][0]["card_id"], card_id)
        self.assertEqual(body["sources"][0]["source_type"], "knowledge_graph")
        search_records.assert_not_called()

    def test_library_ask_reuses_history_and_exposes_records(self) -> None:
        self._seed_verified_card()
        chat = AsyncMock(return_value="BadCLIP attacks CLIP [L1].")
        with patch("app.services.corpus_qa.get_llm_service") as gls:
            gls.return_value.chat = chat
            first = self.client.post(
                "/api/library/ask",
                json={"question": "BadCLIP CLIP", "language": "en"},
            )
            second = self.client.post(
                "/api/library/ask",
                json={"question": "  BadCLIP   CLIP  ", "language": "en"},
            )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        first_body = first.json()
        second_body = second.json()
        self.assertFalse(first_body["from_cache"])
        self.assertTrue(second_body["from_cache"])
        self.assertEqual(first_body["qa_id"], second_body["qa_id"])
        chat.assert_awaited_once()

        history = self.client.get("/api/library/ask/history")
        self.assertEqual(history.status_code, 200, history.text)
        items = history.json()["data"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qa_id"], first_body["qa_id"])

        detail = self.client.get(f"/api/library/ask/history/{first_body['qa_id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["markdown"], "BadCLIP attacks CLIP [L1].")

        deleted = self.client.delete(f"/api/library/ask/history/{first_body['qa_id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["deleted"])

        missing_detail = self.client.get(f"/api/library/ask/history/{first_body['qa_id']}")
        self.assertEqual(missing_detail.status_code, 404, missing_detail.text)

        history_after_delete = self.client.get("/api/library/ask/history")
        self.assertEqual(history_after_delete.status_code, 200, history_after_delete.text)
        self.assertEqual(history_after_delete.json()["data"], [])

        missing_delete = self.client.delete(f"/api/library/ask/history/{first_body['qa_id']}")
        self.assertEqual(missing_delete.status_code, 404, missing_delete.text)


if __name__ == "__main__":
    unittest.main()
