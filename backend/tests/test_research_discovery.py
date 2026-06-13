from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import get_settings
from app.db import database as db
from app.services import knowledge_assets as assets
from app.services import research_discovery


class _RelationVerifierLLM:
    async def chat(self, messages, model: str = "", temperature: float = 0.0) -> str:  # noqa: ANN001
        payload = messages[-1]["content"]
        candidates = __import__("json").loads(payload)["candidates"]
        return __import__("json").dumps(
            {
                "relations": [
                    {
                        "relation_id": candidate["relation_id"],
                        "status": "needs_more_evidence",
                        "confidence": 0.91,
                        "positive_checks": ["llm compared task and evidence quotes"],
                        "negative_checks": ["llm requires dataset split confirmation"],
                        "counter_evidence_ids": [],
                    }
                    for candidate in candidates
                ]
            }
        )


class _RejectingRelationVerifierLLM:
    async def chat(self, messages, model: str = "", temperature: float = 0.0) -> str:  # noqa: ANN001
        candidates = __import__("json").loads(messages[-1]["content"])["candidates"]
        return __import__("json").dumps(
            {
                "relations": [
                    {
                        "relation_id": candidate["relation_id"],
                        "status": "rejected",
                        "confidence": 0.2,
                        "positive_checks": [],
                        "negative_checks": ["llm found incomparable settings"],
                        "counter_evidence_ids": [],
                    }
                    for candidate in candidates
                ]
            }
        )


class ResearchDiscoveryVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmp.name) / "app.db")
        await db.init_db()

    async def asyncTearDown(self) -> None:
        for key in (
            "RESEARCH_DISCOVERY_LLM_VERIFY_ENABLED",
            "RESEARCH_DISCOVERY_LLM_VERIFY_LIMIT",
            "LLM_BASEURL",
            "THINKING_MODELNAME",
        ):
            os.environ.pop(key, None)
        get_settings.cache_clear()
        self._tmp.cleanup()

    async def _paper(self, paper_id: str, title: str, text: str) -> None:
        await db.execute(
            "INSERT INTO papers (paper_id, file_path, title, year) VALUES (?, ?, ?, 2025)",
            (paper_id, f"papers/{paper_id}/original.pdf", title),
        )
        await db.execute(
            "INSERT INTO mineru_parses (parse_id, paper_id, status) VALUES (?, ?, 'done')",
            (f"parse-{paper_id}", paper_id),
        )
        await db.execute(
            """
            INSERT INTO blocks (paper_id, type, page_idx, text, section_path, order_idx)
            VALUES (?, 'text', 0, ?, 'Abstract', 1)
            """,
            (paper_id, text),
        )

    async def test_verifier_marks_exact_dataset_relation_verified(self) -> None:
        await self._paper(
            "paper1",
            "CLIP ImageNet Evaluation",
            "Dense vision-language prediction uses CLIP-style contrastive learning on ImageNet dataset and improves accuracy.",
        )
        await self._paper(
            "paper2",
            "Prompt ImageNet Evaluation",
            "Dense vision-language prediction uses visual-guided prompt evolution on ImageNet dataset and improves accuracy.",
        )

        await research_discovery.build_research_discovery(limit=20)
        edges = await db.fetch_all(
            "SELECT * FROM research_relation_edges WHERE relation_type = 'uses_same_dataset'"
        )

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["status"], "verified")
        self.assertEqual(edges[0]["verifier_version"], "rule_verifier_v1")
        self.assertIn("verifier: exact dataset label match", edges[0]["positive_checks"])
        comparability = json.loads(edges[0]["comparability_json"])
        self.assertEqual(comparability["dataset"], "matched")
        self.assertEqual(comparability["verdict"], "verified")

    async def test_transfer_relation_remains_review_candidate(self) -> None:
        await self._paper(
            "paper1",
            "CLIP Dense Prediction",
            "Dense vision-language prediction uses CLIP-style contrastive learning and improves accuracy.",
        )
        await self._paper(
            "paper2",
            "Retinal Biomarker Prediction",
            "Retinal fundus biomarker prediction requires external clinical validation.",
        )

        await research_discovery.build_research_discovery(limit=20)
        edge = await db.fetch_one(
            "SELECT * FROM research_relation_edges WHERE relation_type = 'transferable_method'"
        )

        self.assertIsNotNone(edge)
        assert edge is not None
        self.assertEqual(edge["status"], "needs_more_evidence")
        self.assertIn("verifier: transfer feasibility is not established", edge["negative_checks"])

    async def test_conflict_without_shared_dataset_records_counter_evidence(self) -> None:
        await self._paper(
            "paper1",
            "Negative ImageNet Result",
            "Dense vision-language prediction on ImageNet dataset reports accuracy but fails to improve over the baseline.",
        )
        await self._paper(
            "paper2",
            "Positive COCO Claim",
            "Dense vision-language prediction on COCO dataset improves accuracy with CLIP-style contrastive learning.",
        )

        await research_discovery.build_research_discovery(limit=20)
        edge = await db.fetch_one(
            "SELECT * FROM research_relation_edges WHERE relation_type = 'conflicting_claim'"
        )

        self.assertIsNotNone(edge)
        assert edge is not None
        self.assertEqual(edge["status"], "needs_more_evidence")
        self.assertIn("verifier: conflict lacks same dataset support", edge["negative_checks"])
        self.assertGreaterEqual(len(edge["counter_evidence_ids"]), 2)
        comparability = json.loads(edge["comparability_json"])
        self.assertIn("dataset", comparability["missing"])

    async def test_gap_status_update_appends_lifecycle_history(self) -> None:
        await self._paper(
            "paper1",
            "CLIP Dense Prediction",
            "Dense vision-language prediction has a limitation and requires external validation.",
        )
        await research_discovery.build_research_discovery(limit=20)
        gap = await db.fetch_one("SELECT * FROM research_gaps LIMIT 1")
        self.assertIsNotNone(gap)
        assert gap is not None

        await research_discovery.update_gap_status(
            gap["gap_id"],
            {
                "status": "experiment_planned",
                "research_question": "Can the limitation be tested with a small pilot?",
                "baseline_plan": "Compare against the closest local baseline.",
                "minimum_experiment": "Run a small pilot.",
            },
        )
        updated = await db.fetch_one("SELECT * FROM research_gaps WHERE gap_id = ?", (gap["gap_id"],))
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["status"], "experiment_planned")
        self.assertEqual(updated["minimum_experiment"], "Run a small pilot.")
        history = json.loads(updated["history_json"])
        self.assertEqual(history[-1]["event"], "status_changed")

    async def test_gap_response_includes_full_description_from_source_block(self) -> None:
        long_tail = " ".join(f"detail{i}" for i in range(160))
        full_text = (
            "Dense vision-language prediction has a limitation and requires external validation. "
            f"{long_tail}"
        )
        await self._paper("paper1", "CLIP Dense Prediction", full_text)

        discovery = await research_discovery.build_research_discovery(limit=20)
        gap = discovery.gaps[0]

        self.assertIn("detail159", gap.full_description)
        self.assertGreater(len(gap.full_description), len(gap.description))
        self.assertTrue(gap.description.endswith("…"))

    async def test_llm_relation_verifier_overlays_rule_result_when_enabled(self) -> None:
        os.environ["RESEARCH_DISCOVERY_LLM_VERIFY_ENABLED"] = "true"
        os.environ["RESEARCH_DISCOVERY_LLM_VERIFY_LIMIT"] = "4"
        os.environ["LLM_BASEURL"] = "http://llm.local/v1"
        os.environ["THINKING_MODELNAME"] = "test-model"
        get_settings.cache_clear()
        await self._paper(
            "paper1",
            "CLIP ImageNet Evaluation",
            "Dense vision-language prediction uses CLIP-style contrastive learning on ImageNet dataset and improves accuracy.",
        )
        await self._paper(
            "paper2",
            "Prompt ImageNet Evaluation",
            "Dense vision-language prediction uses visual-guided prompt evolution on ImageNet dataset and improves accuracy.",
        )

        with patch("app.services.research_discovery.get_llm_service", return_value=_RelationVerifierLLM()):
            await research_discovery.build_research_discovery(limit=20)
        edge = await db.fetch_one(
            "SELECT * FROM research_relation_edges WHERE relation_type = 'uses_same_dataset'"
        )

        self.assertIsNotNone(edge)
        assert edge is not None
        self.assertEqual(edge["status"], "needs_more_evidence")
        self.assertEqual(edge["verifier_version"], "llm_relation_verifier_v1")
        self.assertIn("llm compared task and evidence quotes", edge["positive_checks"])
        self.assertIn("llm requires dataset split confirmation", edge["negative_checks"])

    async def test_llm_relation_verifier_can_reject_candidate(self) -> None:
        os.environ["RESEARCH_DISCOVERY_LLM_VERIFY_ENABLED"] = "true"
        os.environ["LLM_BASEURL"] = "http://llm.local/v1"
        os.environ["THINKING_MODELNAME"] = "test-model"
        get_settings.cache_clear()
        await self._paper(
            "paper1",
            "CLIP ImageNet Evaluation",
            "Dense vision-language prediction uses CLIP-style contrastive learning on ImageNet dataset and improves accuracy.",
        )
        await self._paper(
            "paper2",
            "Prompt ImageNet Evaluation",
            "Dense vision-language prediction uses visual-guided prompt evolution on ImageNet dataset and improves accuracy.",
        )

        with patch("app.services.research_discovery.get_llm_service", return_value=_RejectingRelationVerifierLLM()):
            await research_discovery.build_research_discovery(limit=20)
        edge = await db.fetch_one(
            "SELECT * FROM research_relation_edges WHERE relation_type = 'uses_same_dataset'"
        )

        self.assertIsNotNone(edge)
        assert edge is not None
        self.assertEqual(edge["status"], "rejected")
        self.assertIn("llm: relation rejected", edge["negative_checks"])

    async def test_verified_card_promotion_triggers_incremental_relation_discovery(self) -> None:
        await self._paper(
            "paper1",
            "First ImageNet Paper",
            "The method uses ImageNet dataset for robust evaluation.",
        )
        await self._paper(
            "paper2",
            "Second ImageNet Paper",
            "The method uses ImageNet dataset for robust evaluation.",
        )
        card1 = await assets.create_card(
            {
                "card_type": "dataset",
                "title": "ImageNet evaluation",
                "content": "The method uses ImageNet dataset for robust evaluation.",
                "paper_id": "paper1",
                "source_quote": "The method uses ImageNet dataset for robust evaluation.",
                "confidence": 0.9,
                "status": "verified",
                "asset_level": "action",
                "tags": "imagenet",
                "created_by": "user",
            }
        )
        await db.execute("DELETE FROM research_relation_edges")
        card2 = await assets.create_card(
            {
                "card_type": "dataset",
                "title": "ImageNet evaluation",
                "content": "The method uses ImageNet dataset for robust evaluation.",
                "paper_id": "paper2",
                "source_quote": "The method uses ImageNet dataset for robust evaluation.",
                "confidence": 0.9,
                "status": "draft",
                "asset_level": "action",
                "tags": "imagenet",
                "created_by": "user",
            }
        )

        await assets.update_card(card2["card_id"], {"status": "verified", "reviewed_by": "tester"})
        edge = await db.fetch_one(
            "SELECT * FROM research_relation_edges WHERE relation_type = 'uses_same_dataset'"
        )

        self.assertIsNotNone(edge, f"source card {card1['card_id']} should be in the incremental discovery scope")
        assert edge is not None
        self.assertEqual(edge["status"], "verified")
        self.assertEqual({edge["source_paper_id"], edge["target_paper_id"]}, {"paper1", "paper2"})


if __name__ == "__main__":
    unittest.main()
