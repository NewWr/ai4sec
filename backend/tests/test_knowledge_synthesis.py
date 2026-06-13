from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import database as db
from app.services import knowledge_assets as assets
from app.services import knowledge_synthesis


class KnowledgeSynthesisTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmp.name) / "app.db")
        await db.init_db()
        for paper_id, title in (("paper1", "Paper One"), ("paper2", "Paper Two")):
            await db.execute(
                "INSERT INTO papers (paper_id, file_path, title) VALUES (?, ?, ?)",
                (paper_id, f"papers/{paper_id}/original.pdf", title),
            )
            await db.execute(
                "INSERT INTO blocks (paper_id, type, page_idx, text, order_idx) VALUES (?, 'text', 0, ?, 1)",
                (paper_id, "The method uses ImageNet for robust evaluation."),
            )

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_rebuild_synthesis_cards_groups_verified_action_cards(self) -> None:
        for paper_id in ("paper1", "paper2"):
            await assets.create_card(
                {
                    "card_type": "dataset",
                    "title": "ImageNet evaluation",
                    "content": "The method uses ImageNet for robust evaluation.",
                    "paper_id": paper_id,
                    "source_quote": "The method uses ImageNet for robust evaluation.",
                    "confidence": 0.9,
                    "status": "verified",
                    "created_by": "ai",
                    "tags": "imagenet,evaluation",
                    "asset_level": "action",
                    "why_useful": "Useful for comparing evaluation settings.",
                    "use_case": "experiment",
                    "next_action": "Add ImageNet to the comparison matrix.",
                    "risk_or_caveat": "Check exact split and metric.",
                }
            )

        result = await knowledge_synthesis.rebuild_synthesis_cards()
        self.assertGreaterEqual(result["synthesis_cards"], 1)
        cards = await assets.list_cards(asset_level="synthesis", status="verified", limit=10)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["evidence_strength"], "multi-paper")
        self.assertEqual(set(cards[0]["supporting_paper_ids"]), {"paper1", "paper2"})
        self.assertEqual(len(cards[0]["supporting_card_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
