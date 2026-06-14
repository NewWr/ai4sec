from __future__ import annotations

import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.db import database as db
from app.services import knowledge_assets, research_construction


class _NoLLMConfig:
    base_url = ""
    api_key = ""
    default_thinking_model = ""
    thinking_model = ""


class ResearchConstructionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmp.name) / "app.db")
        await db.init_db()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def _paper(self) -> None:
        await db.execute(
            "INSERT INTO papers (paper_id, file_path, title) VALUES ('paper1', 'papers/paper1/original.pdf', 'Paper One')"
        )
        await db.execute(
            "INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx) VALUES (?, 'text', 0, ?, 'Abstract', 1)",
            (
                "paper1",
                "Dense vision-language prediction uses CLIP-style contrastive learning on ImageNet dataset and has a limitation.",
            ),
        )

    async def test_dry_run_returns_budget_estimate_without_running_job(self) -> None:
        await self._paper()

        job = await research_construction.start_construction_job(dry_run=True, trigger_source="manual")

        self.assertEqual(job["status"], "done")
        self.assertTrue(job["dry_run"])
        self.assertIn("estimated_chat_calls", job["estimate"])
        self.assertTrue(job["result"]["dry_run"])

    async def test_run_construction_without_llm_or_embedding_uses_heuristic_path(self) -> None:
        await self._paper()

        with (
            patch("app.services.semantic_index.embedding_enabled", return_value=False),
            patch("app.services.research_construction.get_llm_runtime_config", return_value=_NoLLMConfig()),
            patch("app.services.entity_registry.get_llm_runtime_config", return_value=_NoLLMConfig()),
        ):
            job = await research_construction.start_construction_job(force=True, trigger_source="manual")
            task = research_construction._jobs[job["job_id"]]  # noqa: SLF001 - test waits for the spawned in-process job.
            finished = await asyncio.wait_for(task, timeout=10)

        self.assertEqual(finished["status"], "done")
        self.assertIn("ideas", finished["result"])
        state = await research_construction.get_state()
        self.assertEqual(state["last_paper_count"], 1)

    async def test_idea_feedback_updates_gap_status_and_records_event(self) -> None:
        await self._paper()
        await db.execute(
            """
            INSERT INTO research_gaps (
                gap_id, title, hypothesis, description, support_evidence_ids,
                counter_evidence_ids, status
            ) VALUES ('gap1', 'Idea', 'Hypothesis', 'Description', '[]', '[]', 'candidate')
            """
        )

        feedback = await research_construction.record_idea_feedback("gap1", "accepted", "useful")

        self.assertEqual(feedback["verdict"], "accepted")
        gap = await db.fetch_one("SELECT status FROM research_gaps WHERE gap_id = 'gap1'")
        self.assertEqual(gap["status"], "promoted_to_idea")
        rows = await db.fetch_all("SELECT * FROM idea_feedback WHERE item_id = 'gap1'")
        self.assertEqual(len(rows), 1)

    async def test_research_gap_construction_columns_exist_after_init(self) -> None:
        info = await db.fetch_all("PRAGMA table_info(research_gaps)")
        columns = {str(row["name"]) for row in info}

        self.assertIn("llm_rationale", columns)
        self.assertIn("construction_batch_id", columns)
        self.assertIn("lineage_parent_id", columns)

    async def test_entity_registry_tables_support_card_mentions(self) -> None:
        await self._paper()
        card = await knowledge_assets.create_card(
            {
                "card_type": "dataset",
                "title": "ImageNet evaluation",
                "content": "Dense vision-language prediction uses ImageNet dataset.",
                "paper_id": "paper1",
                "source_quote": "Dense vision-language prediction uses CLIP-style contrastive learning on ImageNet dataset and has a limitation.",
                "confidence": 0.9,
                "status": "verified",
                "created_by": "ai",
                "asset_level": "action",
                "why_useful": "Useful for comparing evaluation settings.",
                "use_case": "experiment",
                "next_action": "Add ImageNet to comparison matrix.",
                "risk_or_caveat": "Check exact split.",
            }
        )

        await db.execute(
            """
            INSERT INTO canonical_entities (
                entity_id, entity_type, canonical_name, aliases_json, definition
            ) VALUES ('ent_test', 'dataset', 'ImageNet', '["ImageNet"]', 'Dataset')
            """
        )
        await db.execute(
            """
            INSERT INTO entity_mentions (
                mention_id, entity_id, card_id, paper_id, mention_text, confidence
            ) VALUES ('ment_test', 'ent_test', ?, 'paper1', 'ImageNet evaluation', 0.9)
            """,
            (card["card_id"],),
        )
        mention = await db.fetch_one("SELECT * FROM entity_mentions WHERE card_id = ?", (card["card_id"],))

        self.assertIsNotNone(mention)
        self.assertEqual(json.loads((await db.fetch_one("SELECT aliases_json FROM canonical_entities WHERE entity_id = 'ent_test'"))["aliases_json"]), ["ImageNet"])


if __name__ == "__main__":
    unittest.main()
