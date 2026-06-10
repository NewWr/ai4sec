from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class PaperLibraryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self._tmp.name

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
        os.environ.pop("DATA_DIR", None)
        from app.config import get_settings

        get_settings.cache_clear()
        self._tmp.cleanup()

    def _seed(self) -> None:
        con = sqlite3.connect(self.db_file)
        con.execute(
            "INSERT INTO papers (paper_id, file_path, title, doi, venue, year) VALUES (?, ?, ?, ?, ?, ?)",
            ("paper1", "papers/paper1/original.pdf", "Paper One", "10.1/x", "Venue", 2024),
        )
        con.execute(
            "INSERT INTO papers (paper_id, file_path, title, doi, venue, year) VALUES (?, ?, ?, ?, ?, ?)",
            ("paper2", "papers/paper2/original.pdf", "Paper Two", "10.2/x", "Venue", 2025),
        )
        con.execute(
            "INSERT INTO runs (run_id, paper_id, mode, status, started_at, current_step) "
            "VALUES ('run1', 'paper1', 'lens', 'done', datetime('now'), 'persist_output')"
        )
        con.execute(
            "INSERT INTO mineru_parses (parse_id, paper_id, status, updated_at) "
            "VALUES ('parse1', 'paper1', 'done', datetime('now'))"
        )
        con.execute(
            "INSERT INTO mineru_parses (parse_id, paper_id, status, updated_at) "
            "VALUES ('parse2', 'paper2', 'done', datetime('now'))"
        )
        con.execute(
            "INSERT INTO dify_syncs "
            "(paper_id, dataset_id, dify_document_id, source_hash, status, attempts, updated_at) "
            "VALUES ('paper1', 'ds', 'doc1', 'hash1', 'synced', 1, datetime('now'))"
        )
        con.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) "
            "VALUES ('paper1', 'title', 0, 'Paper One', 'Paper One', 0)"
        )
        con.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) "
            "VALUES ('paper1', 'text', 1, 'Vision-language biomarker prediction from retinal fundus images', 'Abstract', 1)"
        )
        con.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) "
            "VALUES ('paper1', 'text', 2, 'A limitation is that the approach does not address external clinical validation.', 'Limitations', 2)"
        )
        con.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) "
            "VALUES ('paper2', 'title', 0, 'Paper Two', 'Paper Two', 0)"
        )
        con.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) "
            "VALUES ('paper2', 'text', 1, 'Dense vision-language prediction uses CLIP-style contrastive learning on the RETFound dataset and improves accuracy.', 'Abstract', 1)"
        )
        con.commit()
        con.close()

    def test_list_papers_returns_latest_run_and_sync_status(self) -> None:
        resp = self.client.get("/api/papers")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(len(body), 2)
        by_id = {item["paper_id"]: item for item in body}
        self.assertEqual(by_id["paper1"]["latest_run"]["run_id"], "run1")
        self.assertEqual(by_id["paper1"]["dify_sync"]["status"], "synced")
        self.assertEqual(by_id["paper1"]["dify_sync"]["document_id"], "doc1")

    def test_discovery_returns_local_research_map(self) -> None:
        resp = self.client.get("/api/papers/discovery")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["stats"]["total_papers"], 2)
        self.assertEqual(body["stats"]["parsed_papers"], 2)
        self.assertEqual(body["stats"]["analyzed_papers"], 1)
        self.assertGreaterEqual(body["stats"]["evidence_items"], 2)
        self.assertGreaterEqual(body["stats"]["gap_candidates"], 1)
        nodes = {item["paper_id"]: item for item in body["nodes"]}
        self.assertGreaterEqual(nodes["paper1"]["evidence_count"], 1)
        self.assertGreaterEqual(len(body["themes"]), 1)
        self.assertGreaterEqual(len(body["gaps"]), 1)
        self.assertGreaterEqual(len(body["evidence"]), 1)
        first_evidence = body["evidence"][0]
        self.assertIn("evidence_id", first_evidence)
        self.assertIn("paper_id", first_evidence)
        self.assertIn("quote", first_evidence)
        gap = body["gaps"][0]
        self.assertIn("support_evidence_ids", gap)
        self.assertIn("counter_evidence_ids", gap)
        self.assertIn("scores", gap)
        self.assertIn("minimum_experiment", gap)
        if body["edges"]:
            edge = body["edges"][0]
            self.assertIn("relation_id", edge)
            self.assertIn("rule_id", edge)
            self.assertIn("positive_checks", edge)
            self.assertIn("negative_checks", edge)

    def test_get_sync_status_returns_paper_and_analysis_rows(self) -> None:
        resp = self.client.get("/api/papers/paper1/sync-status")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["paper"]["status"], "synced")
        self.assertEqual(body["analysis"], [])

    def test_retry_paper_sync_builds_ir_from_blocks(self) -> None:
        create = AsyncMock(return_value={"document": {"id": "doc2"}})
        settings = type(
            "Settings",
            (),
            {
                "dify_enabled": True,
                "dify_default_dataset_id": "ds",
                "dify_analysis_dataset_id": "",
            },
        )()
        with patch("app.services.dify_sync.get_settings", return_value=settings), patch(
            "app.services.dify_client.create_document_by_text",
            new=create,
        ):
            resp = self.client.post("/api/papers/paper1/sync-dify")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "synced")
        self.assertEqual(body["document_id"], "doc2")
        self.assertIn("[p.2] Vision-language biomarker prediction", create.await_args.args[1])

    def test_delete_paper_cleans_dependent_rows(self) -> None:
        con = sqlite3.connect(self.db_file)
        con.execute("INSERT INTO knowledge_card_generations (generation_id, paper_id, run_id, status) VALUES ('gen1', 'paper1', 'run1', 'done')")
        con.execute(
            "INSERT INTO knowledge_cards (card_id, card_type, title, content, paper_id, run_id) "
            "VALUES ('card1', 'claim', 'Claim', 'Content', 'paper1', 'run1')"
        )
        con.execute(
            "INSERT INTO writing_snippets (snippet_id, content, source_card_id, paper_id) "
            "VALUES ('snippet1', 'Snippet', 'card1', 'paper1')"
        )
        con.execute(
            "INSERT INTO research_evidence_items (evidence_id, evidence_type, paper_id, quote) "
            "VALUES ('evidence1', 'claim', 'paper1', 'Evidence')"
        )
        con.execute("INSERT INTO research_evidence_cards (evidence_id, card_id) VALUES ('evidence1', 'card1')")
        con.execute("INSERT INTO daily_recommendation_topics (topic_id, name) VALUES ('topic1', 'Topic')")
        con.execute(
            """
            INSERT INTO daily_recommendation_items (
                item_id, arxiv_id, topic_id, title_en, status, linked_paper_id, linked_run_id, fetched_date
            ) VALUES ('daily1', '2501.00001', 'topic1', 'Daily Item', 'ingested', 'paper1', 'run1', '2026-06-08')
            """
        )
        con.execute("INSERT INTO knowledge_spaces (space_id, name, space_type) VALUES ('space1', 'Space', 'custom')")
        con.execute(
            "INSERT INTO knowledge_space_items (space_id, item_kind, item_id, paper_id, run_id, source_type) "
            "VALUES ('space1', 'paper', 'paper1', 'paper1', '', 'upload')"
        )
        con.execute(
            "INSERT INTO knowledge_space_items (space_id, item_kind, item_id, paper_id, run_id, source_type) "
            "VALUES ('space1', 'run', 'run1', 'paper1', 'run1', 'generated')"
        )
        con.execute(
            "INSERT INTO knowledge_space_items (space_id, item_kind, item_id, paper_id, run_id, source_type) "
            "VALUES ('space1', 'card', 'card1', 'paper1', 'run1', 'generated')"
        )
        con.commit()
        con.close()

        resp = self.client.delete("/api/papers/paper1")
        self.assertEqual(resp.status_code, 204, resp.text)

        con = sqlite3.connect(self.db_file)
        try:
            tables = [
                "papers",
                "runs",
                "knowledge_card_generations",
                "knowledge_cards",
                "writing_snippets",
                "research_evidence_items",
                "research_evidence_cards",
                "dify_syncs",
                "paper_collection_items",
                "knowledge_space_items",
            ]
            counts = {
                table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
            daily = con.execute(
                "SELECT status, linked_paper_id, linked_run_id FROM daily_recommendation_items WHERE item_id = 'daily1'"
            ).fetchone()
        finally:
            con.close()

        self.assertEqual(counts["papers"], 1)
        for table, count in counts.items():
            if table == "papers":
                continue
            self.assertEqual(count, 0, table)
        self.assertEqual(daily, ("candidate", "", ""))


if __name__ == "__main__":
    unittest.main()
