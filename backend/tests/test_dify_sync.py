from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db import database as db
from app.models.paper_ir import Block, PaperIR
from app.services import dify_sync


def _paper_ir() -> PaperIR:
    return PaperIR(
        paper_id="paper",
        title="Paper Title",
        blocks=[
            Block(type="title", order_idx=0, text="Paper Title", section_path="Paper Title", page_idx=0),
            Block(type="text", order_idx=1, text="Abstract text.", section_path="Abstract", page_idx=1),
            Block(type="table", order_idx=2, text="<table>data</table>", section_path="Results", page_idx=2),
            Block(type="header", order_idx=3, text="ignored"),
        ],
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        dify_enabled=True,
        dify_default_dataset_id="DS123",
        dify_analysis_dataset_id="ADS123",
    )


class DifySyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmp.name) / "app.db")
        await db.init_db()
        await db.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES (?, ?, ?)",
            ("paper", "papers/paper/original.pdf", ""),
        )
        await db.execute(
            "INSERT INTO runs (run_id, paper_id, mode, language, status) VALUES (?, ?, ?, ?, ?)",
            ("run1", "paper", "lens", "zh", "running"),
        )
        await db.execute(
            "INSERT INTO runs (run_id, paper_id, mode, language, status) VALUES (?, ?, ?, ?, ?)",
            ("run2", "paper", "snap", "en", "running"),
        )

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    def test_paper_ir_to_markdown_skips_boilerplate(self) -> None:
        text = dify_sync.paper_ir_to_markdown(_paper_ir())
        self.assertIn("# Paper Title", text)
        self.assertIn("[p.2] Abstract text.", text)
        self.assertIn("[Table [p.3]]\n<table>data</table>", text)
        self.assertNotIn("ignored", text)

    async def test_sync_uploads_once_and_skips_unchanged_source(self) -> None:
        create = AsyncMock(return_value={"document": {"id": "doc123"}})
        with patch.object(dify_sync, "get_settings", return_value=_settings()), patch(
            "app.services.dify_client.create_document_by_text",
            new=create,
        ):
            first = await dify_sync.sync_paper_ir_to_dify("paper", _paper_ir())
            second = await dify_sync.sync_paper_ir_to_dify("paper", _paper_ir())

        self.assertEqual(first.status, "synced")
        self.assertEqual(first.document_id, "doc123")
        self.assertEqual(second.status, "skipped")
        self.assertEqual(create.await_count, 1)

        row = await db.fetch_one("SELECT * FROM dify_syncs WHERE paper_id = ?", ("paper",))
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "synced")
        self.assertEqual(row["dify_document_id"], "doc123")

    async def test_force_sync_uploads_even_when_source_unchanged(self) -> None:
        create = AsyncMock(return_value={"document": {"id": "doc123"}})
        with patch.object(dify_sync, "get_settings", return_value=_settings()), patch(
            "app.services.dify_client.create_document_by_text",
            new=create,
        ):
            await dify_sync.sync_paper_ir_to_dify("paper", _paper_ir())
            forced = await dify_sync.sync_paper_ir_to_dify("paper", _paper_ir(), force=True)

        self.assertEqual(forced.status, "synced")
        self.assertEqual(create.await_count, 2)

    async def test_sync_analysis_uploads_to_analysis_dataset(self) -> None:
        create = AsyncMock(return_value={"document": {"id": "analysis-doc"}})
        with patch.object(dify_sync, "get_settings", return_value=_settings()), patch(
            "app.services.dify_client.create_document_by_text",
            new=create,
        ):
            first = await dify_sync.sync_analysis_to_dify(
                run_id="run1",
                paper_id="paper",
                markdown="## Summary\nAnalysis body.",
                mode="lens",
                language="zh",
                title="Paper Title",
            )
            second = await dify_sync.sync_analysis_to_dify(
                run_id="run1",
                paper_id="paper",
                markdown="## Summary\nAnalysis body.",
                mode="lens",
                language="zh",
                title="Paper Title",
            )

        self.assertEqual(first.status, "synced")
        self.assertEqual(first.document_id, "analysis-doc")
        self.assertEqual(second.status, "skipped")
        self.assertEqual(create.await_count, 1)
        self.assertEqual(create.await_args.kwargs["dataset_id"], "ADS123")
        self.assertIn("source_type: analysis", create.await_args.args[1])
        self.assertIn("run_id: run1", create.await_args.args[1])

        row = await db.fetch_one("SELECT * FROM analysis_dify_syncs WHERE run_id = ?", ("run1",))
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "synced")
        self.assertEqual(row["paper_id"], "paper")
        self.assertEqual(row["dify_document_id"], "analysis-doc")

    async def test_sync_analysis_can_target_multiple_datasets_for_same_run(self) -> None:
        create = AsyncMock(side_effect=[
            {"document": {"id": "analysis-doc-a"}},
            {"document": {"id": "analysis-doc-b"}},
        ])
        with patch.object(dify_sync, "get_settings", return_value=_settings()), patch(
            "app.services.dify_client.create_document_by_text",
            new=create,
        ):
            first = await dify_sync.sync_analysis_to_dify(
                run_id="run1",
                paper_id="paper",
                markdown="Analysis body.",
                mode="lens",
                language="zh",
                dataset_id="ADS-A",
            )
            second = await dify_sync.sync_analysis_to_dify(
                run_id="run1",
                paper_id="paper",
                markdown="Analysis body.",
                mode="lens",
                language="zh",
                dataset_id="ADS-B",
            )

        self.assertEqual(first.document_id, "analysis-doc-a")
        self.assertEqual(second.document_id, "analysis-doc-b")
        rows = await db.fetch_all("SELECT * FROM analysis_dify_syncs WHERE run_id = ?", ("run1",))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["dataset_id"] for row in rows}, {"ADS-A", "ADS-B"})

    async def test_sync_analysis_skips_without_analysis_dataset(self) -> None:
        settings = SimpleNamespace(
            dify_enabled=True,
            dify_default_dataset_id="DS123",
            dify_analysis_dataset_id="",
        )
        create = AsyncMock(return_value={"document": {"id": "analysis-doc"}})
        with patch.object(dify_sync, "get_settings", return_value=settings), patch(
            "app.services.dify_client.create_document_by_text",
            new=create,
        ):
            result = await dify_sync.sync_analysis_to_dify(
                run_id="run2",
                paper_id="paper",
                markdown="Analysis body.",
                mode="snap",
                language="en",
            )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(create.await_count, 0)


if __name__ == "__main__":
    unittest.main()
