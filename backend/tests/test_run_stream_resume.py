from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


def _event_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("data: ") or line.startswith("id: ")]


class RunStreamResumeTests(unittest.TestCase):
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
            "INSERT INTO papers (paper_id, file_path, title) VALUES (?, ?, ?)",
            ("paper", "papers/paper/original.pdf", "Paper"),
        )
        con.execute(
            "INSERT INTO runs (run_id, paper_id, mode, language, status) VALUES (?, ?, 'snap', 'en', 'done')",
            ("run-done", "paper"),
        )
        con.execute(
            "INSERT INTO runs (run_id, paper_id, mode, language, status, error_msg) "
            "VALUES (?, ?, 'snap', 'en', 'failed', 'boom')",
            ("run-failed", "paper"),
        )
        con.execute(
            "INSERT INTO runs (run_id, paper_id, mode, language, status) VALUES (?, ?, 'snap', 'en', 'running')",
            ("run-orphan", "paper"),
        )
        con.execute(
            "INSERT INTO run_progress_events (run_id, seq, event_type, data_json) VALUES (?, 1, 'progress', ?)",
            ("run-done", '{"step":"ingest_pdf","status":"done"}'),
        )
        con.execute(
            "INSERT INTO run_progress_events (run_id, seq, event_type, data_json) VALUES (?, 2, 'progress', ?)",
            ("run-done", '{"step":"mineru_parse","status":"done"}'),
        )
        con.execute(
            "INSERT INTO run_progress_events (run_id, seq, event_type, data_json) VALUES (?, 3, 'done', ?)",
            ("run-done", '{"run_id":"run-done","status":"done"}'),
        )
        con.commit()
        con.close()

    def test_migration_created_progress_event_table(self) -> None:
        con = sqlite3.connect(self.db_file)
        try:
            table = con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'run_progress_events'"
            ).fetchone()
            index = con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_run_progress_events_run_seq'"
            ).fetchone()
        finally:
            con.close()
        self.assertIsNotNone(table)
        self.assertIsNotNone(index)

    def test_stream_replays_history_with_sse_ids(self) -> None:
        resp = self.client.get("/api/runs/run-done/stream")
        self.assertEqual(resp.status_code, 200, resp.text)
        lines = _event_lines(resp.text)
        self.assertIn("id: 1", lines)
        self.assertIn("id: 2", lines)
        self.assertIn("id: 3", lines)
        self.assertIn('data: {"event": "progress", "data": {"step": "ingest_pdf", "status": "done"}, "seq": 1}', lines)
        self.assertIn('data: {"event": "done", "data": {"run_id": "run-done", "status": "done"}, "seq": 3}', lines)
        self.assertIn('data: {"event": "end", "data": {}}', lines)

    def test_stream_honors_since_seq(self) -> None:
        resp = self.client.get("/api/runs/run-done/stream", params={"since_seq": 1})
        self.assertEqual(resp.status_code, 200, resp.text)
        lines = _event_lines(resp.text)
        self.assertNotIn("id: 1", lines)
        self.assertIn("id: 2", lines)
        self.assertIn("id: 3", lines)

    def test_stream_prefers_last_event_id_header(self) -> None:
        resp = self.client.get("/api/runs/run-done/stream?since_seq=1", headers={"Last-Event-ID": "2"})
        self.assertEqual(resp.status_code, 200, resp.text)
        lines = _event_lines(resp.text)
        self.assertNotIn("id: 1", lines)
        self.assertNotIn("id: 2", lines)
        self.assertIn("id: 3", lines)

    def test_stream_without_queue_returns_failed_terminal_event(self) -> None:
        resp = self.client.get("/api/runs/run-failed/stream")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn('"event": "error"', resp.text)
        self.assertIn('"error": "boom"', resp.text)
        self.assertIn('"event": "end"', resp.text)

    def test_stream_orphan_running_run_returns_interrupted_terminal_event(self) -> None:
        resp = self.client.get("/api/runs/run-orphan/stream")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn('"event": "error"', resp.text)
        self.assertIn('"Interrupted (task no longer running)"', resp.text)
        con = sqlite3.connect(self.db_file)
        try:
            row = con.execute(
                "SELECT status, error_msg FROM runs WHERE run_id = ?",
                ("run-orphan",),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(row, ("failed", "Interrupted (task no longer running)"))


if __name__ == "__main__":
    unittest.main()
