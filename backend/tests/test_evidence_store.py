from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import database as db
from app.services import evidence_store
from app.services import knowledge_assets as assets


class EvidenceStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmp.name) / "app.db")
        await db.init_db()
        await db.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES (?, ?, ?)",
            ("paper1", "papers/paper1/original.pdf", "Vision Benchmark Paper"),
        )
        await db.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) VALUES (?, ?, ?, ?, ?, ?)",
            ("paper1", "text", 2, "The method improves robustness on ImageNet and COCO benchmarks.", "Results", 1),
        )

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_upsert_dedup_anchor_and_version(self) -> None:
        quote = "The method improves robustness on ImageNet and COCO benchmarks."
        eid1 = await evidence_store.upsert_evidence("paper1", quote, evidence_type="result", confidence=0.9)
        eid2 = await evidence_store.upsert_evidence("paper1", "  The method improves robustness on ImageNet and COCO benchmarks.  ", evidence_type="result", confidence=0.95)
        self.assertEqual(eid1, eid2, "same (paper,type,quote) must dedup to one evidence id")

        rows = await db.fetch_all("SELECT * FROM research_evidence_items WHERE paper_id = ?", ("paper1",))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["page"], 3, "quote should anchor to block on page_idx=2 -> page 3")
        self.assertGreaterEqual(row["evidence_version"], 2, "re-upsert must bump evidence_version")
        self.assertEqual(row["evidence_type"], "result")

    async def test_unanchorable_quote_still_stores_without_page(self) -> None:
        eid = await evidence_store.upsert_evidence(
            "paper1", "A claim that appears in no block whatsoever.", evidence_type="claim"
        )
        row = await db.fetch_one("SELECT * FROM research_evidence_items WHERE evidence_id = ?", (eid,))
        self.assertIsNotNone(row)
        self.assertEqual(row["page"], 0)

    async def test_backfill_links_anchored_card_and_demotes_unanchorable_verified(self) -> None:
        # Anchored fact card with a source_quote but no bridge row yet.
        good = await assets.create_card(
            {
                "card_type": "result",
                "title": "Robustness result",
                "content": "Improves robustness on ImageNet and COCO.",
                "paper_id": "paper1",
                "source_quote": "The method improves robustness on ImageNet and COCO benchmarks.",
                "status": "draft",
                "created_by": "ai",
            }
        )
        # Drop the bridge rows create_card may have written so we exercise backfill.
        await db.execute("DELETE FROM research_evidence_cards WHERE card_id = ?", (good["card_id"],))

        # Legacy verified fact card whose quote cannot be anchored -> should be
        # demoted by the startup backfill.
        bad_card_id = "legacy_bad_card"
        await db.execute(
            """
            INSERT INTO knowledge_cards (
                card_id, card_type, title, content, paper_id, source_quote,
                status, created_by, normalized_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bad_card_id,
                "result",
                "Unanchorable result",
                "A result not present in any block.",
                "paper1",
                "This sentence is nowhere in the paper blocks.",
                "verified",
                "ai",
                "legacy:bad",
            ),
        )

        result = await evidence_store.backfill_card_evidence()
        self.assertGreaterEqual(result["linked"], 1)
        self.assertGreaterEqual(result["demoted"], 1)

        linked = await db.fetch_all(
            "SELECT evidence_id FROM research_evidence_cards WHERE card_id = ?", (good["card_id"],)
        )
        self.assertEqual(len(linked), 1, "anchored card must gain a bridge row")

        demoted = await db.fetch_one("SELECT status FROM knowledge_cards WHERE card_id = ?", (bad_card_id,))
        self.assertEqual(demoted["status"], "draft", "unanchorable verified fact card must be demoted to draft")

        # Idempotent: a second run does no further work.
        again = await evidence_store.backfill_card_evidence()
        self.assertEqual(again["linked"], 0)
        self.assertEqual(again["demoted"], 0)

    async def test_manual_fact_card_creation_auto_binds_source_quote(self) -> None:
        card = await assets.create_card(
            {
                "card_type": "result",
                "title": "Manual robustness result",
                "content": "Improves robustness on ImageNet and COCO.",
                "paper_id": "paper1",
                "source_quote": "The method improves robustness on ImageNet and COCO benchmarks.",
                "status": "verified",
                "created_by": "user",
            }
        )

        self.assertEqual(card["status"], "verified")
        self.assertEqual(card["source_page"], 3)
        self.assertEqual(len(card["evidence_ids"]), 1)
        evidence = await db.fetch_one(
            "SELECT * FROM research_evidence_items WHERE evidence_id = ?",
            (card["evidence_ids"][0],),
        )
        self.assertEqual(evidence["evidence_type"], "result")
        self.assertEqual(evidence["paper_id"], "paper1")

    async def test_status_promotion_auto_binds_existing_source_quote(self) -> None:
        card = await assets.create_card(
            {
                "card_type": "result",
                "title": "Draft robustness result",
                "content": "Improves robustness on ImageNet and COCO.",
                "paper_id": "paper1",
                "source_quote": "The method improves robustness on ImageNet and COCO benchmarks.",
                "status": "draft",
                "created_by": "user",
            }
        )
        await db.execute("DELETE FROM research_evidence_cards WHERE card_id = ?", (card["card_id"],))

        promoted = await assets.update_card(card["card_id"], {"status": "verified", "reviewed_by": "tester"})

        self.assertEqual(promoted["status"], "verified")
        self.assertEqual(promoted["source_page"], 3)
        self.assertEqual(promoted["reviewed_by"], "tester")
        self.assertEqual(len(promoted["evidence_ids"]), 1)


if __name__ == "__main__":
    unittest.main()
