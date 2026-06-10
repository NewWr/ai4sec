from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class KnowledgeSpaceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self._tmp.name
        os.environ["DIFY_DEFAULT_DATASET_ID"] = "main-source-ds"
        os.environ["DIFY_ANALYSIS_DATASET_ID"] = "main-analysis-ds"
        os.environ["DAILY_RECOMMENDATION_SOURCE_DATASET_ID"] = "daily-source-ds"
        os.environ["DAILY_RECOMMENDATION_ANALYSIS_DATASET_ID"] = "daily-analysis-ds"

        from app.config import get_settings

        get_settings.cache_clear()

        from fastapi.testclient import TestClient
        from app.main import app

        self._client_cm = TestClient(app)
        self.client = self._client_cm.__enter__()
        self.db_file = Path(self._tmp.name) / "app.db"

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)
        for key in (
            "DATA_DIR",
            "DIFY_DEFAULT_DATASET_ID",
            "DIFY_ANALYSIS_DATASET_ID",
            "DAILY_RECOMMENDATION_SOURCE_DATASET_ID",
            "DAILY_RECOMMENDATION_ANALYSIS_DATASET_ID",
            "DIFY_API_BASE",
        ):
            os.environ.pop(key, None)
        from app.config import get_settings

        get_settings.cache_clear()
        self._tmp.cleanup()

    def test_default_spaces_are_initialized_with_dataset_boundaries(self) -> None:
        first = self.client.get("/api/knowledge-spaces")
        second = self.client.get("/api/knowledge-spaces")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)

        spaces = {row["space_id"]: row for row in second.json()["spaces"]}
        self.assertEqual(spaces["main_source"]["dify_dataset_id"], "main-source-ds")
        self.assertEqual(spaces["main_analysis"]["dify_dataset_id"], "main-analysis-ds")
        self.assertEqual(spaces["daily_source"]["dify_dataset_id"], "daily-source-ds")
        self.assertEqual(spaces["daily_analysis"]["dify_dataset_id"], "daily-analysis-ds")

        con = sqlite3.connect(self.db_file)
        count = con.execute("SELECT COUNT(*) FROM knowledge_spaces").fetchone()[0]
        con.close()
        self.assertEqual(count, 4)

    def test_upload_paper_adds_main_source_item(self) -> None:
        pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
        resp = self.client.post(
            "/api/papers/upload",
            files={"file": ("paper.pdf", io.BytesIO(pdf), "application/pdf")},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        paper_id = resp.json()["paper_id"]

        items = self.client.get("/api/knowledge-spaces/main_source/items?item_kind=paper")
        self.assertEqual(items.status_code, 200, items.text)
        body = items.json()
        self.assertEqual(body["space"]["space_id"], "main_source")
        self.assertEqual(body["items"][0]["paper_id"], paper_id)
        self.assertEqual(body["items"][0]["source_type"], "upload")

    def test_copy_move_remove_only_changes_space_links(self) -> None:
        con = sqlite3.connect(self.db_file)
        con.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES ('paper1', 'papers/paper1/original.pdf', 'Paper One')"
        )
        con.execute(
            """
            INSERT INTO knowledge_spaces (
                space_id, name, name_zh, space_type, is_system, sort_order
            ) VALUES ('main_source', 'Main', '主研究原文知识库', 'main_source', 1, 10),
                     ('daily_source', 'Daily', '每日推荐原文知识库', 'daily_source', 1, 30)
            """
        )
        con.execute(
            """
            INSERT INTO knowledge_space_items (
                space_id, item_kind, item_id, paper_id, source_type
            ) VALUES ('daily_source', 'paper', 'paper1', 'paper1', 'daily')
            """
        )
        con.commit()
        con.close()

        copy_resp = self.client.post(
            "/api/knowledge-spaces/items/copy",
            json={
                "space_id": "daily_source",
                "item_kind": "paper",
                "item_id": "paper1",
                "target_space_id": "main_source",
            },
        )
        self.assertEqual(copy_resp.status_code, 200, copy_resp.text)

        remove_resp = self.client.post(
            "/api/knowledge-spaces/items/remove",
            json={"space_id": "daily_source", "item_kind": "paper", "item_id": "paper1"},
        )
        self.assertEqual(remove_resp.status_code, 204, remove_resp.text)

        con = sqlite3.connect(self.db_file)
        paper_count = con.execute("SELECT COUNT(*) FROM papers WHERE paper_id = 'paper1'").fetchone()[0]
        daily_count = con.execute(
            "SELECT COUNT(*) FROM knowledge_space_items WHERE space_id = 'daily_source'"
        ).fetchone()[0]
        main_count = con.execute(
            "SELECT COUNT(*) FROM knowledge_space_items WHERE space_id = 'main_source' AND paper_id = 'paper1'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(paper_count, 1)
        self.assertEqual(daily_count, 0)
        self.assertEqual(main_count, 1)

        move_resp = self.client.post(
            "/api/knowledge-spaces/items/move",
            json={
                "space_id": "main_source",
                "item_kind": "paper",
                "item_id": "paper1",
                "target_space_id": "daily_source",
            },
        )
        self.assertEqual(move_resp.status_code, 200, move_resp.text)
        self.assertEqual(move_resp.json()["space_id"], "daily_source")

    def test_update_space_and_item_note(self) -> None:
        con = sqlite3.connect(self.db_file)
        con.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES ('paper1', 'papers/paper1/original.pdf', 'Paper One')"
        )
        con.commit()
        con.close()
        self.client.get("/api/knowledge-spaces")
        create = self.client.post(
            "/api/knowledge-spaces/items/copy",
            json={
                "space_id": "daily_source",
                "item_kind": "paper",
                "item_id": "missing",
                "target_space_id": "main_source",
            },
        )
        self.assertEqual(create.status_code, 404)

        con = sqlite3.connect(self.db_file)
        con.execute(
            """
            INSERT INTO knowledge_space_items (
                space_id, item_kind, item_id, paper_id, source_type
            ) VALUES ('daily_source', 'paper', 'paper1', 'paper1', 'daily')
            """
        )
        con.commit()
        con.close()

        space_resp = self.client.patch(
            "/api/knowledge-spaces/daily_source",
            json={"name_zh": "推荐原文", "dify_dataset_id": "daily-custom"},
        )
        self.assertEqual(space_resp.status_code, 200, space_resp.text)
        self.assertEqual(space_resp.json()["name_zh"], "推荐原文")
        self.assertEqual(space_resp.json()["dify_dataset_id"], "daily-custom")

        item_resp = self.client.patch(
            "/api/knowledge-spaces/items/update",
            json={
                "space_id": "daily_source",
                "item_kind": "paper",
                "item_id": "paper1",
                "note": "candidate worth reading",
                "sync_status": "skipped",
            },
        )
        self.assertEqual(item_resp.status_code, 200, item_resp.text)
        self.assertEqual(item_resp.json()["note"], "candidate worth reading")
        self.assertEqual(item_resp.json()["sync_status"], "skipped")

    def test_promote_daily_item_copies_source_and_analysis_to_main_spaces(self) -> None:
        con = sqlite3.connect(self.db_file)
        con.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES ('paper1', 'papers/paper1/original.pdf', 'Paper One')"
        )
        con.execute(
            "INSERT INTO runs (run_id, paper_id, mode, status) VALUES ('run1', 'paper1', 'lens', 'done')"
        )
        con.execute(
            """
            INSERT INTO daily_recommendation_items (
                item_id, arxiv_id, topic_id, title_en, abstract_en, authors_json,
                primary_category, categories_json, score, score_detail_json,
                reason, fetched_date, linked_paper_id, linked_run_id
            ) VALUES ('daily1', '2601.00001', 'clip_prompt_learning', 'Paper One', 'Abs',
                      '[]', 'cs.CV', '[]', 0.9, '{}', 'reason', '2026-06-07', 'paper1', 'run1')
            """
        )
        con.execute(
            "INSERT INTO knowledge_space_items (space_id, item_kind, item_id, paper_id, source_type) "
            "VALUES ('daily_source', 'paper', 'paper1', 'paper1', 'daily')"
        )
        con.execute(
            "INSERT INTO knowledge_space_items (space_id, item_kind, item_id, paper_id, run_id, source_type) "
            "VALUES ('daily_analysis', 'run', 'run1', 'paper1', 'run1', 'daily')"
        )
        con.commit()
        con.close()

        resp = self.client.post("/api/daily/items/daily1/promote", json={"copy": True})
        self.assertEqual(resp.status_code, 200, resp.text)
        con = sqlite3.connect(self.db_file)
        main_source = con.execute(
            "SELECT COUNT(*) FROM knowledge_space_items WHERE space_id = 'main_source' AND item_id = 'paper1'"
        ).fetchone()[0]
        main_analysis = con.execute(
            "SELECT COUNT(*) FROM knowledge_space_items WHERE space_id = 'main_analysis' AND item_id = 'run1'"
        ).fetchone()[0]
        daily_source = con.execute(
            "SELECT COUNT(*) FROM knowledge_space_items WHERE space_id = 'daily_source' AND item_id = 'paper1'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(main_source, 1)
        self.assertEqual(main_analysis, 1)
        self.assertEqual(daily_source, 1)

    def test_resync_item_skips_when_space_has_no_dataset(self) -> None:
        con = sqlite3.connect(self.db_file)
        con.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES ('paper1', 'papers/paper1/original.pdf', 'Paper One')"
        )
        con.execute(
            "INSERT INTO knowledge_space_items (space_id, item_kind, item_id, paper_id, source_type) "
            "VALUES ('daily_source', 'paper', 'paper1', 'paper1', 'daily')"
        )
        con.commit()
        con.close()
        self.client.patch("/api/knowledge-spaces/daily_source", json={"dify_dataset_id": ""})

        resp = self.client.post(
            "/api/knowledge-spaces/items/resync",
            json={"space_id": "daily_source", "item_kind": "paper", "item_id": "paper1"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["sync_status"], "skipped")

    def test_create_dify_dataset_binds_space_and_marks_skipped_items_pending(self) -> None:
        os.environ["DIFY_API_BASE"] = "http://kb.test"
        from app.config import get_settings

        get_settings.cache_clear()
        con = sqlite3.connect(self.db_file)
        con.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES ('paper1', 'papers/paper1/original.pdf', 'Paper One')"
        )
        con.execute(
            """
            INSERT INTO knowledge_space_items (
                space_id, item_kind, item_id, paper_id, source_type, sync_status
            ) VALUES ('daily_source', 'paper', 'paper1', 'paper1', 'daily', 'skipped')
            """
        )
        con.commit()
        con.close()

        with patch(
            "app.services.dify_client.create_dataset",
            new=AsyncMock(return_value={"id": "daily-created-ds", "name": "每日推荐原文知识库"}),
        ) as create_dataset:
            resp = self.client.post(
                "/api/knowledge-spaces/daily_source/dify-dataset",
                json={"indexing_technique": "economy", "permission": "only_me"},
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["space"]["dify_dataset_id"], "daily-created-ds")
        create_dataset.assert_awaited_once_with(
            "每日推荐原文知识库",
            indexing_technique="economy",
            permission="only_me",
        )

        con = sqlite3.connect(self.db_file)
        sync_status = con.execute(
            "SELECT sync_status FROM knowledge_space_items WHERE space_id = 'daily_source' AND item_id = 'paper1'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(sync_status, "pending")
        os.environ.pop("DIFY_API_BASE", None)
        get_settings.cache_clear()

    def test_space_dify_documents_and_markdown_use_bound_dataset(self) -> None:
        self.client.patch("/api/knowledge-spaces/daily_source", json={"dify_dataset_id": "daily-source-ds"})

        with patch(
            "app.services.dify_client.list_documents",
            new=AsyncMock(return_value={"data": [{"id": "doc1", "name": "Doc One"}], "total": 1}),
        ) as list_documents:
            docs = self.client.get("/api/knowledge-spaces/daily_source/dify-documents?page=1&limit=20")

        self.assertEqual(docs.status_code, 200, docs.text)
        self.assertEqual(docs.json()["data"][0]["id"], "doc1")
        list_documents.assert_awaited_once_with(dataset_id="daily-source-ds", page=1, limit=20)

        with patch(
            "app.services.dify_client.get_markdown",
            new=AsyncMock(return_value={"document_name": "Doc One", "content": "# Doc One"}),
        ) as get_markdown:
            markdown = self.client.get("/api/knowledge-spaces/daily_source/dify-documents/doc1/markdown")

        self.assertEqual(markdown.status_code, 200, markdown.text)
        self.assertEqual(markdown.json()["document_name"], "Doc One")
        self.assertEqual(markdown.json()["content"], "# Doc One")
        get_markdown.assert_awaited_once_with("doc1", dataset_id="daily-source-ds")

    def test_space_dify_documents_requires_bound_dataset(self) -> None:
        self.client.patch("/api/knowledge-spaces/daily_source", json={"dify_dataset_id": ""})

        resp = self.client.get("/api/knowledge-spaces/daily_source/dify-documents")

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("no Dify dataset", resp.json()["detail"])


class KnowledgeSpaceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self._tmp.name
        os.environ["DIFY_DEFAULT_DATASET_ID"] = "main-source-ds"
        os.environ["DIFY_ANALYSIS_DATASET_ID"] = "main-analysis-ds"
        os.environ["DAILY_RECOMMENDATION_SOURCE_DATASET_ID"] = "daily-source-ds"
        os.environ["DAILY_RECOMMENDATION_ANALYSIS_DATASET_ID"] = "daily-analysis-ds"
        from app.config import get_settings
        from app.db import database as db

        get_settings.cache_clear()
        db.set_db_path(Path(self._tmp.name) / "app.db")
        await db.init_db()
        await db.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES ('paper1', 'papers/paper1/original.pdf', 'Paper One')"
        )
        await db.execute(
            "INSERT INTO runs (run_id, paper_id, mode, status) VALUES ('run1', 'paper1', 'lens', 'pending')"
        )

    async def asyncTearDown(self) -> None:
        for key in (
            "DATA_DIR",
            "DIFY_DEFAULT_DATASET_ID",
            "DIFY_ANALYSIS_DATASET_ID",
            "DAILY_RECOMMENDATION_SOURCE_DATASET_ID",
            "DAILY_RECOMMENDATION_ANALYSIS_DATASET_ID",
            "DIFY_API_BASE",
        ):
            os.environ.pop(key, None)
        from app.config import get_settings

        get_settings.cache_clear()
        self._tmp.cleanup()

    async def test_daily_space_selects_daily_dify_datasets(self) -> None:
        from app.services import knowledge_spaces as spaces

        await spaces.add_item_to_space(
            space_id="daily_source",
            item_kind="paper",
            item_id="paper1",
            paper_id="paper1",
            source_type="daily",
        )
        await spaces.add_item_to_space(
            space_id="daily_analysis",
            item_kind="run",
            item_id="run1",
            paper_id="paper1",
            run_id="run1",
            source_type="daily",
        )

        self.assertEqual(await spaces.source_dataset_for_paper("paper1"), "daily-source-ds")
        self.assertEqual(await spaces.analysis_dataset_for_run("run1", "paper1"), "daily-analysis-ds")


if __name__ == "__main__":
    unittest.main()
