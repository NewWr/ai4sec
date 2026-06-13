from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app.db import database as db
from app.models.paper_ir import Block, PaperIR
from app.services.paper_ir import clear_cached_paper_ir, get_cached_paper_ir
from app.workflows.progress import persist_run_event


class DatabaseConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmp.name) / "app.db")
        await db.init_db()
        await db.open_db()

    async def asyncTearDown(self) -> None:
        await db.close_db()
        self._tmp.cleanup()

    async def test_read_pool_reads_during_open_write_transaction(self) -> None:
        await db.execute("INSERT INTO papers (paper_id, file_path, title) VALUES ('p1', 'x.pdf', 'P1')")
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold_write() -> None:
            async with db.transaction() as conn:
                await conn.execute("INSERT INTO papers (paper_id, file_path, title) VALUES ('p2', 'y.pdf', 'P2')")
                entered.set()
                await release.wait()

        task = asyncio.create_task(hold_write())
        await entered.wait()
        row = await asyncio.wait_for(db.fetch_one("SELECT title FROM papers WHERE paper_id = 'p1'"), timeout=1.0)
        self.assertEqual(row["title"], "P1")
        release.set()
        await task

    async def test_transaction_connection_reads_own_uncommitted_write(self) -> None:
        async with db.transaction() as conn:
            await conn.execute("INSERT INTO papers (paper_id, file_path, title) VALUES ('p3', 'z.pdf', 'P3')")
            cursor = await conn.execute("SELECT title FROM papers WHERE paper_id = 'p3'")
            row = await cursor.fetchone()
            self.assertEqual(row["title"], "P3")

    async def test_persist_run_event_seq_is_monotonic_under_concurrency(self) -> None:
        await db.execute("INSERT INTO papers (paper_id, file_path) VALUES ('paper', 'x.pdf')")
        await db.execute("INSERT INTO runs (run_id, paper_id, mode, language, status) VALUES ('run', 'paper', 'snap', 'en', 'running')")

        seqs = await asyncio.gather(*[
            persist_run_event("run", "progress", {"idx": idx})
            for idx in range(20)
        ])

        self.assertEqual(sorted(seqs), list(range(1, 21)))
        rows = await db.fetch_all("SELECT seq FROM run_progress_events WHERE run_id = 'run' ORDER BY seq")
        self.assertEqual([row["seq"] for row in rows], list(range(1, 21)))


class PaperIRCacheTests(unittest.TestCase):
    def test_cache_hit_and_digest_invalidation(self) -> None:
        ir1 = PaperIR(
            paper_id="paper",
            title="One",
            blocks=[Block(type="text", page_idx=0, order_idx=1, text="A")],
            sections=[],
        )
        ir2 = PaperIR(
            paper_id="paper",
            title="Two",
            blocks=[Block(type="text", page_idx=0, order_idx=1, text="B")],
            sections=[],
        )
        state = {"run_id": "run", "paper_ir_json": ir1.model_dump_json()}
        first = get_cached_paper_ir(state)
        second = get_cached_paper_ir(state)
        self.assertIs(first, second)

        state["paper_ir_json"] = ir2.model_dump_json()
        third = get_cached_paper_ir(state)
        self.assertIsNot(first, third)
        self.assertEqual(third.title, "Two")
        clear_cached_paper_ir("run")


if __name__ == "__main__":
    unittest.main()
