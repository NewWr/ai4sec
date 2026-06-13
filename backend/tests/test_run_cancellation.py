from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db import database as db
from app.workflows.main_graph import generate_knowledge_cards, persist_output


class RunCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmp.name) / "app.db")
        await db.init_db()
        await db.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES (?, ?, ?)",
            ("paper", "papers/paper/original.pdf", "Paper"),
        )

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def _insert_run(self, run_id: str, status: str, owner_token: str = "owner") -> None:
        await db.execute(
            "INSERT INTO runs (run_id, paper_id, mode, language, status, owner_token) "
            "VALUES (?, ?, 'snap', 'en', ?, ?)",
            (run_id, "paper", status, owner_token),
        )

    async def test_dismiss_cancels_active_background_task(self) -> None:
        from app.api import runs

        await self._insert_run("run-cancel", "running")
        await db.execute(
            "INSERT INTO mineru_parses (parse_id, paper_id, status) VALUES (?, ?, ?)",
            ("parse-cancel", "paper", "running"),
        )
        task_started = asyncio.Event()

        async def long_running() -> None:
            task_started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(long_running())
        await task_started.wait()
        queue: asyncio.Queue = asyncio.Queue()

        with patch("app.api.runs.cancel_parse", return_value=True) as cancel_parse, patch.dict(
            runs._run_tasks, {"run-cancel": task}, clear=True
        ), patch.dict(
            runs._run_queues, {"run-cancel": {queue}}, clear=True
        ):
            response = await runs.dismiss_run.__wrapped__(SimpleNamespace(), "run-cancel", owner_token="owner")
            self.assertNotIn("run-cancel", runs._run_tasks)
            self.assertNotIn("run-cancel", runs._run_queues)
            cancel_parse.assert_called_once_with("parse-cancel")

        self.assertEqual(response.status, "failed")
        self.assertEqual(response.error_msg, "Dismissed by user")
        self.assertTrue(task.cancelled() or task.cancelling())

        error_msg = await queue.get()
        end_msg = await queue.get()
        self.assertEqual(error_msg["event"], "cancelled")
        self.assertEqual(error_msg["data"]["error"], "Dismissed by user")
        self.assertIsNone(end_msg)

        with self.assertRaises(asyncio.CancelledError):
            await task
        row = await db.fetch_one("SELECT status, error_msg FROM runs WHERE run_id = ?", ("run-cancel",))
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_msg"], "Dismissed by user")
        parse = await db.fetch_one("SELECT status, error_msg FROM mineru_parses WHERE parse_id = ?", ("parse-cancel",))
        self.assertEqual(parse["status"], "failed")
        self.assertEqual(parse["error_msg"], "Cancelled by user")

    async def test_execute_run_cleans_queue_when_cancelled_waiting_for_slot(self) -> None:
        from app.api import runs

        await self._insert_run("run-wait-cancel", "pending", owner_token="")
        queue: asyncio.Queue = asyncio.Queue()
        semaphore = asyncio.Semaphore(0)

        with patch.object(runs, "_run_semaphore", semaphore), patch.dict(
            runs._run_queues, {"run-wait-cancel": {queue}}, clear=True
        ):
            task = asyncio.create_task(
                runs._execute_run("run-wait-cancel", "paper", "snap", "", "en", "")
            )
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        error_msg = await queue.get()
        end_msg = await queue.get()
        self.assertEqual(error_msg["event"], "cancelled")
        self.assertEqual(error_msg["data"]["error"], "Cancelled by user")
        self.assertGreater(error_msg["seq"], 0)
        self.assertIsNone(end_msg)
        self.assertEqual(semaphore._value, 0)

    async def test_persist_output_skips_inactive_run_without_output_or_dify_sync(self) -> None:
        await self._insert_run("run-skipped", "failed")
        state = {
            "run_id": "run-skipped",
            "paper_id": "paper",
            "mode": "snap",
            "language": "en",
            "final_markdown": "analysis body",
            "final_json": "{}",
            "progress": [],
        }

        sync = AsyncMock()
        with patch("app.workflows.main_graph.sync_analysis_to_dify", new=sync):
            result = await persist_output(state)

        self.assertTrue(result["persist_skipped"])
        self.assertEqual(result["progress"][-1]["status"], "skipped")
        sync.assert_not_awaited()

        run = await db.fetch_one("SELECT status, error_msg FROM runs WHERE run_id = ?", ("run-skipped",))
        output = await db.fetch_one("SELECT * FROM run_outputs WHERE run_id = ?", ("run-skipped",))
        self.assertEqual(run["status"], "failed")
        self.assertIsNone(output)

    async def test_persist_output_still_saves_active_run(self) -> None:
        await self._insert_run("run-active", "running")
        state = {
            "run_id": "run-active",
            "paper_id": "paper",
            "mode": "lens",
            "language": "zh",
            "detected_intent": "lens",
            "final_markdown": "analysis body",
            "final_json": "{}",
            "progress": [],
        }

        with patch("app.workflows.main_graph.sync_analysis_to_dify", new=AsyncMock(return_value=None)):
            result = await persist_output(state)

        self.assertEqual(result["progress"][-1]["status"], "done")
        run = await db.fetch_one(
            "SELECT status, mode, detected_intent FROM runs WHERE run_id = ?",
            ("run-active",),
        )
        output = await db.fetch_one("SELECT markdown, json_data FROM run_outputs WHERE run_id = ?", ("run-active",))
        self.assertEqual(run["status"], "done")
        self.assertEqual(run["mode"], "lens")
        self.assertEqual(run["detected_intent"], "lens")
        self.assertEqual(output["markdown"], "analysis body")
        self.assertEqual(output["json_data"], "{}")

    async def test_generate_knowledge_cards_skips_after_persist_skip(self) -> None:
        with patch(
            "app.services.knowledge_card_generator.generate_cards_from_state",
            new=AsyncMock(return_value={"status": "done"}),
        ) as generate:
            result = await generate_knowledge_cards(
                {
                    "paper_id": "paper",
                    "run_id": "run-skipped",
                    "persist_skipped": True,
                    "progress": [],
                }
            )

        generate.assert_not_awaited()
        self.assertEqual(result["progress"][-1], {"step": "generate_knowledge_cards", "status": "skipped"})


if __name__ == "__main__":
    unittest.main()
