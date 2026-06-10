from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


class KnowledgeAssetsApiTests(unittest.TestCase):
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
            """
            INSERT INTO papers (
                paper_id, file_path, title, doi, venue, year, reading_status, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("paper1", "papers/paper1/original.pdf", "Vision Transformer Survey", "10.1/vit", "ICML", 2024, "unread", "medium"),
        )
        con.execute(
            """
            INSERT INTO papers (
                paper_id, file_path, title, doi, venue, year, reading_status, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("paper2", "papers/paper2/original.pdf", "Vision Transformer Survey Duplicate", "10.1/vit", "", 0, "read", "low"),
        )
        con.execute(
            """
            INSERT INTO papers (
                paper_id, file_path, title, doi, venue, year, reading_status, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("paper3", "papers/paper3/original.pdf", "ArXiv Malware Embeddings", "arXiv:2401.12345", "arXiv", 2024, "unread", "medium"),
        )
        con.execute(
            """
            INSERT INTO papers (
                paper_id, file_path, title, doi, venue, year, reading_status, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("paper4", "papers/paper4/original.pdf", "Malware Embeddings Extended", "2401.12345", "arXiv", 2024, "unread", "medium"),
        )
        con.execute(
            """
            INSERT INTO papers (
                paper_id, file_path, title, doi, venue, year, reading_status, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("paper5", "papers/paper5/original.pdf", "Secure Federated Learning for Malware Classification", "", "S&P", 2023, "unread", "medium"),
        )
        con.execute(
            """
            INSERT INTO papers (
                paper_id, file_path, title, doi, venue, year, reading_status, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("paper6", "papers/paper6/original.pdf", "Secure Federated Learning for Malware Classifications", "", "S&P", 2023, "unread", "medium"),
        )
        con.execute(
            """
            INSERT INTO papers (
                paper_id, file_path, title, doi, venue, year, reading_status, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("paper7", "papers/paper7/original.pdf", "Unsynced Parsed Paper", "", "", 0, "unread", "medium"),
        )
        con.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) VALUES (?, ?, ?, ?, ?, ?)",
            ("paper1", "text", 2, "The method improves robustness on ImageNet and COCO benchmarks.", "Results", 1),
        )
        con.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) VALUES (?, ?, ?, ?, ?, ?)",
            ("paper7", "text", 0, "This paper has parsed text but no Dify sync record.", "Abstract", 1),
        )
        con.execute(
            "INSERT INTO mineru_parses (parse_id, paper_id, status) VALUES (?, ?, ?)",
            ("parse1", "paper1", "done"),
        )
        con.execute(
            "INSERT INTO dify_syncs (paper_id, dataset_id, status, error_msg) VALUES (?, ?, ?, ?)",
            ("paper1", "ds", "failed", "network"),
        )
        con.commit()
        con.close()

    def test_lifecycle_filters_and_bulk_update(self) -> None:
        resp = self.client.patch(
            "/api/papers/paper1/lifecycle",
            json={"reading_status": "reading", "priority": "high", "decision": "must_read", "read_progress": 35},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["reading_status"], "reading")
        self.assertEqual(body["priority"], "high")
        self.assertEqual(body["decision"], "must_read")
        self.assertEqual(body["read_progress"], 35)

        filtered = self.client.get("/api/papers?reading_status=reading&priority=high").json()
        self.assertEqual([item["paper_id"] for item in filtered], ["paper1"])

        resp = self.client.post(
            "/api/papers/lifecycle/bulk",
            json={"paper_ids": ["paper1", "paper2"], "reading_status": "archived"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["updated"], 2)

    def test_annotations_notes_cards_search_and_exports(self) -> None:
        note = self.client.put(
            "/api/papers/paper1/note",
            json={"summary_user": "Important", "key_takeaways": "Robustness", "open_questions": "Cost?", "reading_decision": "useful"},
        )
        self.assertEqual(note.status_code, 200, note.text)
        self.assertEqual(note.json()["summary_user"], "Important")

        ann = self.client.post(
            "/api/papers/paper1/annotations",
            json={"page": 3, "quote": "Improves robustness", "annotation_type": "highlight"},
        )
        self.assertEqual(ann.status_code, 200, ann.text)
        self.assertEqual(ann.json()["page"], 3)
        self.assertEqual(len(self.client.get("/api/papers/paper1/annotations").json()), 1)

        card = self.client.post(
            "/api/knowledge/cards",
            json={
                "card_type": "result",
                "title": "Robustness gain",
                "content": "Improves robustness on ImageNet and COCO.",
                "paper_id": "paper1",
                "source_page": 3,
                "source_quote": "Improves robustness",
                "status": "draft",
            },
        )
        self.assertEqual(card.status_code, 200, card.text)
        card_id = card.json()["card_id"]

        search = self.client.get("/api/library/local-search?mode=cards&query=robustness")
        self.assertEqual(search.status_code, 200, search.text)
        self.assertEqual(search.json()["results"][0]["id"], card_id)

        snippet = self.client.post(
            "/api/writing/snippets",
            json={"source_card_id": card_id, "content": "Robustness gain", "section_hint": "related_work"},
        )
        self.assertEqual(snippet.status_code, 200, snippet.text)
        self.assertEqual(snippet.json()["source_page"], 3)
        self.assertEqual(snippet.json()["source_quote"], "Improves robustness")

        md = self.client.get("/api/writing/export/markdown").json()["content"]
        self.assertIn("Robustness gain", md)
        self.assertIn("source: paper_id=paper1", md)
        self.assertIn("page=3", md)
        self.assertIn("quote: Improves robustness", md)

        bib = self.client.get("/api/papers/export/bibtex").json()["content"]
        self.assertIn("Vision2024paper1", bib)

    def test_health_report_counts_quality_issues(self) -> None:
        resp = self.client.get("/api/health/knowledge")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["total_papers"], 7)
        self.assertEqual(body["sync_failed_papers"], 1)
        self.assertGreaterEqual(body["duplicate_candidates"], 3)
        self.assertGreaterEqual(body["stale_index_documents"], 2)
        self.assertGreaterEqual(body["missing_metadata_papers"], 1)
        self.assertGreaterEqual(body["unresolved_issues"], 1)
        duplicate_issue = next(item for item in body["issues"] if item["issue_type"] == "duplicates")
        reasons = {group["reason"] for group in duplicate_issue["groups"]}
        self.assertIn("doi", reasons)
        self.assertIn("arxiv", reasons)
        self.assertIn("title_similarity", reasons)

    def test_invalid_local_knowledge_status_values_are_rejected(self) -> None:
        lifecycle = self.client.patch(
            "/api/papers/paper1/lifecycle",
            json={"reading_status": "finished"},
        )
        self.assertEqual(lifecycle.status_code, 422, lifecycle.text)

        annotation = self.client.post(
            "/api/papers/paper1/annotations",
            json={"page": 1, "quote": "x", "annotation_type": "bookmark"},
        )
        self.assertEqual(annotation.status_code, 422, annotation.text)

        card = self.client.post(
            "/api/knowledge/cards",
            json={"title": "Bad card", "card_type": "theme"},
        )
        self.assertEqual(card.status_code, 422, card.text)

        snippet = self.client.post(
            "/api/writing/snippets",
            json={"content": "Bad snippet", "section_hint": "intro"},
        )
        self.assertEqual(snippet.status_code, 422, snippet.text)

    def test_reference_import_export_and_duplicate_endpoint(self) -> None:
        bibtex = """
        @inproceedings{smith2025nested,
          title = {Nested {Brace} Reference Import},
          booktitle = {USENIX Security},
          year = {2025},
          doi = {10.5555/nested}
        }
        """
        imported = self.client.post(
            "/api/papers/import-references",
            json={"format": "bibtex", "content": bibtex},
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["imported"], 1)

        duplicate = self.client.post(
            "/api/papers/import-references",
            json={"format": "bibtex", "content": bibtex},
        )
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json()["skipped"], 1)

        ris = """
TY  - JOUR
ID  - lee2026ris
TI  - RIS Reference Import
JO  - IEEE TSE
PY  - 2026
DO  - 10.5555/ris
ER  -
        """
        ris_imported = self.client.post(
            "/api/papers/import-references",
            json={"format": "ris", "content": ris},
        )
        self.assertEqual(ris_imported.status_code, 200, ris_imported.text)
        self.assertEqual(ris_imported.json()["imported"], 1)

        ris_export = self.client.get("/api/papers/export/ris")
        self.assertEqual(ris_export.status_code, 200, ris_export.text)
        self.assertIn("TI  - RIS Reference Import", ris_export.json()["content"])
        self.assertIn("ID  - lee2026ris", ris_export.json()["content"])

        candidates = self.client.get("/api/knowledge/duplicates")
        self.assertEqual(candidates.status_code, 200, candidates.text)
        reasons = {item["reason"] for item in candidates.json()["candidates"]}
        self.assertIn("doi", reasons)
        self.assertIn("arxiv", reasons)
        self.assertIn("title_similarity", reasons)

    def test_health_fix_marks_sync_and_stale_index_pending(self) -> None:
        sync_fix = self.client.post(
            "/api/health/knowledge/fix",
            json={"issue_type": "sync_failed", "paper_ids": ["paper1"]},
        )
        self.assertEqual(sync_fix.status_code, 200, sync_fix.text)
        self.assertEqual(sync_fix.json()["fixed"], 1)

        con = sqlite3.connect(self.db_file)
        self.assertEqual(
            con.execute("SELECT status FROM dify_syncs WHERE paper_id = ?", ("paper1",)).fetchone()[0],
            "pending",
        )
        con.close()

        stale_fix = self.client.post(
            "/api/health/knowledge/fix",
            json={"issue_type": "stale_index", "paper_ids": ["paper7"]},
        )
        self.assertEqual(stale_fix.status_code, 200, stale_fix.text)
        self.assertEqual(stale_fix.json()["fixed"], 1)

        con = sqlite3.connect(self.db_file)
        row = con.execute(
            "SELECT status FROM dify_syncs WHERE paper_id = ? AND dataset_id = ''",
            ("paper7",),
        ).fetchone()
        con.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "pending")

    def test_health_fix_messages_are_precise(self) -> None:
        metadata_fix = self.client.post(
            "/api/health/knowledge/fix",
            json={"issue_type": "missing_metadata", "paper_ids": ["paper2"]},
        )
        self.assertEqual(metadata_fix.status_code, 200, metadata_fix.text)
        self.assertIn("DOI", metadata_fix.json()["message"])
        self.assertIn("citation key", metadata_fix.json()["message"])

        duplicate_fix = self.client.post(
            "/api/health/knowledge/fix",
            json={"issue_type": "duplicates"},
        )
        self.assertEqual(duplicate_fix.status_code, 200, duplicate_fix.text)
        self.assertIn("不会自动合并", duplicate_fix.json()["message"])


if __name__ == "__main__":
    unittest.main()
