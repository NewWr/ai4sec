from __future__ import annotations

import os
import time
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class DailyRecommendationScoringTests(unittest.TestCase):
    def test_short_abbreviation_requires_strong_context(self) -> None:
        from app.services.daily_recommendation_scoring import DEFAULT_TOPICS, score_paper

        topic = next(t for t in DEFAULT_TOPICS if t["id"] == "clip_prompt_learning")
        bad = score_paper(
            title="Large-flavor route to a stable Dirac spin liquid on the maple-leaf lattice",
            abstract="We study a maple leaf lattice model in condensed matter physics.",
            categories=["cond-mat.str-el"],
            primary_category="cond-mat.str-el",
            topic=topic,
        )
        self.assertFalse(bad.keep)
        self.assertIn("类别", bad.reason)

        good = score_paper(
            title="Test-Time Prompt Tuning for CLIP Vision-Language Models",
            abstract="We study prompt learning and domain adaptation for CLIP in open-vocabulary recognition.",
            categories=["cs.CV", "cs.LG"],
            primary_category="cs.CV",
            topic=topic,
        )
        self.assertTrue(good.keep)
        self.assertGreaterEqual(good.score, 0.68)

    def test_exclude_terms_block_even_with_partial_match(self) -> None:
        from app.services.daily_recommendation_scoring import DEFAULT_TOPICS, score_paper

        topic = next(t for t in DEFAULT_TOPICS if t["id"] == "clip_model_design_transfer")
        result = score_paper(
            title="CLIP observations of black hole accretion disks",
            abstract="We study image-text alignment and CLIP contrastive model design in an astrophysics setting.",
            categories=["cs.CV"],
            primary_category="cs.CV",
            topic=topic,
        )
        self.assertFalse(result.keep)
        self.assertIn("排除词", result.reason)

    def test_sam_and_dino_topics_are_not_medical_only(self) -> None:
        from app.services.daily_recommendation_scoring import DEFAULT_TOPICS, score_paper

        sam_topic = next(t for t in DEFAULT_TOPICS if t["id"] == "sam_segmentation")
        sam = score_paper(
            title="Adapter Tuning for Segment Anything Model in Remote Sensing",
            abstract="We improve SAM segmentation with promptable masks and domain generalization.",
            categories=["cs.CV"],
            primary_category="cs.CV",
            topic=sam_topic,
        )
        self.assertTrue(sam.keep)

        dino_topic = next(t for t in DEFAULT_TOPICS if t["id"] == "dino_self_supervised")
        dino = score_paper(
            title="DINOv2 Features for Dense Visual Representation Learning",
            abstract="We study self-supervised visual representation learning with vision transformers for segmentation.",
            categories=["cs.CV", "cs.LG"],
            primary_category="cs.CV",
            topic=dino_topic,
        )
        self.assertTrue(dino.keep)

    def test_behavior_terms_can_promote_relevant_candidates(self) -> None:
        from app.services.daily_recommendation_scoring import DEFAULT_TOPICS, score_paper
        from app.services.recommendation_behavior import extract_behavior_terms

        topic = next(t for t in DEFAULT_TOPICS if t["id"] == "clip_prompt_learning")
        terms = extract_behavior_terms(
            "Vision-Language Prompt Calibration for Medical Segmentation",
            "CLIP prompt calibration and medical segmentation are active reading interests.",
        )
        result = score_paper(
            title="Vision-Language Prompt Calibration",
            abstract="A lightweight prompt method for medical segmentation and transfer.",
            categories=["cs.CV"],
            primary_category="cs.CV",
            topic=topic,
            behavior_terms=terms,
        )

        self.assertTrue(result.keep)
        self.assertGreaterEqual(result.detail["behavior_score"], 0.1)
        self.assertIn("prompt calibration", result.detail["matched_behavior"])
        self.assertIn("行为匹配", result.reason)


class DailyRecommendationSchedulerTests(unittest.TestCase):
    def test_next_refresh_at_uses_configured_timezone(self) -> None:
        import datetime as dt

        from app.services.daily_scheduler import next_refresh_at

        before = dt.datetime.fromisoformat("2026-06-08T05:59:00+08:00")
        self.assertEqual(
            next_refresh_at(before, hour=6, minute=0, timezone="Asia/Shanghai").isoformat(),
            "2026-06-08T06:00:00+08:00",
        )

        after = dt.datetime.fromisoformat("2026-06-08T06:00:00+08:00")
        self.assertEqual(
            next_refresh_at(after, hour=6, minute=0, timezone="Asia/Shanghai").isoformat(),
            "2026-06-09T06:00:00+08:00",
        )

    def test_missed_refresh_date_after_configured_time(self) -> None:
        import datetime as dt

        from app.services.daily_scheduler import missed_refresh_date

        before = dt.datetime.fromisoformat("2026-06-08T05:59:00+08:00")
        self.assertEqual(
            missed_refresh_date(before, hour=6, minute=0, timezone="Asia/Shanghai"),
            "",
        )

        after = dt.datetime.fromisoformat("2026-06-08T06:01:00+08:00")
        self.assertEqual(
            missed_refresh_date(after, hour=6, minute=0, timezone="Asia/Shanghai"),
            "2026-06-08",
        )


class DailyRecommendationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self._tmp.name
        os.environ["DEEPLX_API_BASE"] = ""
        os.environ["DAILY_RECOMMENDATION_TRANSLATE_ENABLED"] = "false"
        os.environ["DAILY_RECOMMENDATION_AUTO_REFRESH_ENABLED"] = "false"

        from app.config import get_settings

        get_settings.cache_clear()

        from fastapi.testclient import TestClient
        from app.main import app

        self._client_cm = TestClient(app)
        self.client = self._client_cm.__enter__()
        self.db_file = Path(self._tmp.name) / "app.db"
        from app.api import daily

        daily._daily_refresh_jobs.clear()
        daily._active_daily_refresh_job_id = ""

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)
        os.environ.pop("DATA_DIR", None)
        os.environ.pop("DEEPLX_API_BASE", None)
        os.environ.pop("DAILY_RECOMMENDATION_TRANSLATE_ENABLED", None)
        os.environ.pop("DAILY_RECOMMENDATION_AUTO_REFRESH_ENABLED", None)
        from app.config import get_settings

        get_settings.cache_clear()
        self._tmp.cleanup()

    def test_default_topics_are_current_medical_image_topics(self) -> None:
        resp = self.client.get("/api/daily/topics")
        self.assertEqual(resp.status_code, 200, resp.text)
        topic_ids = {topic["topic_id"] for topic in resp.json()}

        self.assertIn("medical_image_deep_learning", topic_ids)
        self.assertIn("clip_prompt_learning", topic_ids)
        self.assertIn("sam_segmentation", topic_ids)
        self.assertIn("dino_self_supervised", topic_ids)
        self.assertIn("clip_model_design_transfer", topic_ids)
        self.assertNotIn("ai_security", topic_ids)
        self.assertNotIn("vision_language_models", topic_ids)
        self.assertNotIn("prompt_learning_vlm", topic_ids)
        self.assertNotIn("medical_clip_prompt_learning", topic_ids)
        self.assertNotIn("medical_sam_segmentation", topic_ids)
        self.assertNotIn("medical_dino_self_supervised", topic_ids)

    def test_refresh_reports_arxiv_errors_without_500(self) -> None:
        with patch(
            "app.api.daily.refresh_daily_recommendations",
            new=AsyncMock(side_effect=RuntimeError("upstream 500")),
        ):
            resp = self.client.post("/api/daily/refresh", json={"date": "2026-06-07", "force": True})

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data["job_id"])
        self.assertIn(data["status"], {"started", "running"})

        status = data
        for _ in range(30):
            status_resp = self.client.get(f"/api/daily/refresh/{data['job_id']}")
            self.assertEqual(status_resp.status_code, 200, status_resp.text)
            status = status_resp.json()
            if status["status"] in {"done", "failed"}:
                break
            time.sleep(0.05)

        self.assertEqual(status["status"], "failed")
        self.assertIn("upstream 500", status["message"])
        self.assertEqual(status["fetched"], 0)

    def test_refresh_is_idempotent_while_job_running(self) -> None:
        async def slow_refresh(**kwargs):
            await __import__("asyncio").sleep(0.2)
            return {"date": kwargs.get("fetched_date") or "", "fetched": 0, "inserted_or_updated": 0, "kept": 0, "skipped": 0, "message": "ok", "errors": []}

        with patch("app.api.daily.refresh_daily_recommendations", new=AsyncMock(side_effect=slow_refresh)):
            first = self.client.post("/api/daily/refresh", json={"date": "2026-06-07", "force": True})
            second = self.client.post("/api/daily/refresh", json={"date": "2026-06-07", "force": True})

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["job_id"], second.json()["job_id"])
        job_id = first.json()["job_id"]
        for _ in range(30):
            status = self.client.get(f"/api/daily/refresh/{job_id}")
            self.assertEqual(status.status_code, 200, status.text)
            if status.json()["status"] in {"done", "failed"}:
                break
            time.sleep(0.05)

    def test_list_items_defaults_to_all_dates_desc_with_pagination(self) -> None:
        con = sqlite3.connect(self.db_file)
        rows = []
        for idx in range(25):
            fetched_date = "2026-06-08" if idx < 21 else "2026-06-07"
            score = 1.0 - idx * 0.01 if fetched_date == "2026-06-08" else 0.99 - idx * 0.01
            rows.append(
                (
                    f"item-page-{idx:02d}",
                    f"2601.1{idx:04d}",
                    "clip_prompt_learning",
                    f"Paper {idx:02d}",
                    "We study prompt learning for CLIP.",
                    "cs.CV",
                    '["cs.CV"]',
                    score,
                    "CLIP prompt learning",
                    fetched_date,
                )
            )
        con.executemany(
            """
            INSERT INTO daily_recommendation_items (
                item_id, arxiv_id, topic_id, title_en, abstract_en, authors_json,
                primary_category, categories_json, score, score_detail_json,
                reason, fetched_date
            ) VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?, '{}', ?, ?)
            """,
            rows,
        )
        con.commit()
        con.close()

        first = self.client.get("/api/daily/items")
        self.assertEqual(first.status_code, 200, first.text)
        data = first.json()
        self.assertEqual(data["date"], "")
        self.assertEqual(data["total"], 25)
        self.assertEqual(data["limit"], 20)
        self.assertEqual(data["offset"], 0)
        self.assertTrue(data["has_more"])
        self.assertEqual(len(data["items"]), 20)
        self.assertEqual(data["items"][0]["fetched_date"], "2026-06-08")
        self.assertEqual(data["items"][0]["title_en"], "Paper 00")

        second = self.client.get("/api/daily/items?offset=20&limit=20")
        self.assertEqual(second.status_code, 200, second.text)
        second_data = second.json()
        self.assertEqual(second_data["total"], 25)
        self.assertFalse(second_data["has_more"])
        self.assertEqual(len(second_data["items"]), 5)
        self.assertEqual(second_data["items"][-1]["fetched_date"], "2026-06-07")

        filtered = self.client.get("/api/daily/items?date=2026-06-07&limit=20")
        self.assertEqual(filtered.status_code, 200, filtered.text)
        filtered_data = filtered.json()
        self.assertEqual(filtered_data["date"], "2026-06-07")
        self.assertEqual(filtered_data["total"], 4)
        self.assertTrue(all(item["fetched_date"] == "2026-06-07" for item in filtered_data["items"]))

    def test_refresh_uses_local_behavior_profile_in_score_detail(self) -> None:
        from app.services.arxiv_client import ArxivPaper

        con = sqlite3.connect(self.db_file)
        con.execute(
            """
            INSERT INTO papers (
                paper_id, file_path, title, reading_status, decision, citation_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "paper-behavior",
                "papers/paper-behavior/original.pdf",
                "Vision-Language Prompt Calibration for Medical Segmentation",
                "read",
                "must_read",
                "PromptCalibration2026",
            ),
        )
        con.commit()
        con.close()

        candidate = ArxivPaper(
            arxiv_id="2601.00003",
            title="Vision-Language Prompt Calibration",
            abstract="A lightweight prompt method for medical segmentation and transfer.",
            authors=["A. Author"],
            primary_category="cs.CV",
            categories=["cs.CV"],
            published_at="2026-06-07",
            updated_at="2026-06-07",
            arxiv_url="https://arxiv.org/abs/2601.00003",
            pdf_url="https://arxiv.org/pdf/2601.00003",
        )

        with patch("app.services.daily_recommendations.search_arxiv", new=AsyncMock(return_value=[candidate])):
            resp = self.client.post(
                "/api/daily/refresh",
                json={"date": "2026-06-07", "topic_id": "clip_prompt_learning", "force": True},
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            job_id = resp.json()["job_id"]
            status = resp.json()
            for _ in range(30):
                status_resp = self.client.get(f"/api/daily/refresh/{job_id}")
                self.assertEqual(status_resp.status_code, 200, status_resp.text)
                status = status_resp.json()
                if status["status"] in {"done", "failed"}:
                    break
                time.sleep(0.05)
        self.assertEqual(status["status"], "done")
        self.assertEqual(status["kept"], 1)

        con = sqlite3.connect(self.db_file)
        row = con.execute(
            """
            SELECT score, score_detail_json, reason
              FROM daily_recommendation_items
             WHERE arxiv_id = '2601.00003'
            """
        ).fetchone()
        con.close()

        self.assertIsNotNone(row)
        detail = __import__("json").loads(row[1])
        self.assertGreaterEqual(detail["behavior_score"], 0.1)
        self.assertIn("prompt calibration", detail["matched_behavior"])
        self.assertIn("行为匹配", row[2])

    def test_refresh_marks_existing_gap_hits(self) -> None:
        from app.services.arxiv_client import ArxivPaper

        con = sqlite3.connect(self.db_file)
        con.execute(
            """
            INSERT INTO research_gaps (
                gap_id, title, hypothesis, description, minimum_experiment,
                novelty_score, feasibility_score, evidence_strength, status
            ) VALUES (?, ?, ?, ?, ?, 0.8, 0.7, 0.9, 'candidate')
            """,
            (
                "gap-prompt-calibration",
                "Prompt calibration for medical segmentation",
                "Vision-language prompt calibration may improve medical segmentation transfer.",
                "Existing CLIP prompt learning leaves medical segmentation calibration under-tested.",
                "Evaluate prompt calibration on medical segmentation datasets.",
            ),
        )
        con.commit()
        con.close()

        candidate = ArxivPaper(
            arxiv_id="2601.00004",
            title="Prompt Calibration for Medical Segmentation",
            abstract="We evaluate vision-language prompt calibration for medical segmentation transfer.",
            authors=["A. Author"],
            primary_category="cs.CV",
            categories=["cs.CV"],
            published_at="2026-06-07",
            updated_at="2026-06-07",
            arxiv_url="https://arxiv.org/abs/2601.00004",
            pdf_url="https://arxiv.org/pdf/2601.00004",
        )

        with patch("app.services.daily_recommendations.search_arxiv", new=AsyncMock(return_value=[candidate])):
            resp = self.client.post(
                "/api/daily/refresh",
                json={"date": "2026-06-07", "topic_id": "clip_prompt_learning", "force": True},
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            job_id = resp.json()["job_id"]
            status = resp.json()
            for _ in range(30):
                status_resp = self.client.get(f"/api/daily/refresh/{job_id}")
                self.assertEqual(status_resp.status_code, 200, status_resp.text)
                status = status_resp.json()
                if status["status"] in {"done", "failed"}:
                    break
                time.sleep(0.05)

        self.assertEqual(status["status"], "done")
        con = sqlite3.connect(self.db_file)
        item_row = con.execute(
            """
            SELECT score_detail_json, reason
              FROM daily_recommendation_items
             WHERE arxiv_id = '2601.00004'
            """
        ).fetchone()
        gap_row = con.execute(
            "SELECT hit_by_paper_ids, coverage_status FROM research_gaps WHERE gap_id = 'gap-prompt-calibration'"
        ).fetchone()
        con.close()

        detail = __import__("json").loads(item_row[0])
        self.assertEqual(detail["matched_gaps"][0]["gap_id"], "gap-prompt-calibration")
        self.assertIn("命中想法", item_row[1])
        self.assertIn("2601.00004", __import__("json").loads(gap_row[0]))
        self.assertEqual(gap_row[1], "partially_covered")

    def test_feedback_updates_candidate_without_creating_paper(self) -> None:
        con = sqlite3.connect(self.db_file)
        con.execute(
            """
            INSERT INTO daily_recommendation_items (
                item_id, arxiv_id, topic_id, title_en, abstract_en, authors_json,
                primary_category, categories_json, score, score_detail_json,
                reason, fetched_date
            ) VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?, '{}', ?, ?)
            """,
            (
                "item1",
                "2601.00001",
                "ai_security",
                "Jailbreak Evaluation for Multimodal Models",
                "This paper evaluates jailbreak attacks against multimodal LLMs.",
                "cs.AI",
                '["cs.AI"]',
                0.9,
                "类别 cs.AI；强条件 jailbreak",
                "2026-06-07",
            ),
        )
        con.commit()
        con.close()

        resp = self.client.post("/api/daily/items/item1/feedback", json={"action": "interested"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "interested")

        con = sqlite3.connect(self.db_file)
        paper_count = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        feedback_count = con.execute("SELECT COUNT(*) FROM daily_recommendation_feedback").fetchone()[0]
        con.close()
        self.assertEqual(paper_count, 0)
        self.assertEqual(feedback_count, 1)

    def test_ingest_routes_daily_source_and_analysis_spaces(self) -> None:
        con = sqlite3.connect(self.db_file)
        con.execute(
            """
            INSERT INTO daily_recommendation_items (
                item_id, arxiv_id, topic_id, title_en, title_zh, abstract_en, abstract_zh,
                authors_json, primary_category, categories_json, score, score_detail_json,
                reason, fetched_date, pdf_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, '{}', ?, ?, ?)
            """,
            (
                "item-ingest",
                "2601.00002",
                "clip_prompt_learning",
                "Prompt Learning for CLIP",
                "CLIP 提示学习",
                "We study prompt learning for CLIP.",
                "本文研究 CLIP 提示学习。",
                "cs.CV",
                '["cs.CV"]',
                0.9,
                "CLIP prompt learning",
                "2026-06-07",
                "https://arxiv.org/pdf/2601.00002",
            ),
        )
        con.commit()
        con.close()

        pdf = b"%PDF-1.4\ndaily recommendation paper\n%%EOF\n"

        async def _write_pdf(url: str, dest_path: Path) -> None:
            self.assertEqual(url, "https://arxiv.org/pdf/2601.00002")
            dest_path.write_bytes(pdf)

        with patch("app.services.daily_recommendations._download_pdf", new=AsyncMock(side_effect=_write_pdf)), patch(
            "app.api.daily.start_background_run",
            new=AsyncMock(return_value={"run_id": "run-daily-1"}),
        ) as start_run:
            resp = self.client.post(
                "/api/daily/items/item-ingest/ingest",
                json={
                    "parse_mode": "sphere",
                    "language": "zh",
                    "source_space_id": "daily_source",
                    "analysis_space_id": "daily_analysis",
                    "start_run": True,
                },
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        paper_id = hashlib.sha1(pdf).hexdigest()
        self.assertEqual(resp.json()["paper_id"], paper_id)
        self.assertEqual(resp.json()["run_id"], "run-daily-1")
        self.assertEqual(start_run.await_args.kwargs["mode"], "sphere")

        con = sqlite3.connect(self.db_file)
        source = con.execute(
            """
            SELECT space_id, item_kind, item_id, paper_id, source_type
              FROM knowledge_space_items
             WHERE space_id = 'daily_source' AND item_kind = 'paper'
            """
        ).fetchone()
        analysis = con.execute(
            """
            SELECT space_id, item_kind, item_id, paper_id, run_id, source_type
              FROM knowledge_space_items
             WHERE space_id = 'daily_analysis' AND item_kind = 'run'
            """
        ).fetchone()
        main_count = con.execute(
            "SELECT COUNT(*) FROM knowledge_space_items WHERE space_id = 'main_source'"
        ).fetchone()[0]
        con.close()

        self.assertEqual(source, ("daily_source", "paper", paper_id, paper_id, "daily"))
        self.assertEqual(analysis, ("daily_analysis", "run", "run-daily-1", paper_id, "run-daily-1", "daily"))
        self.assertEqual(main_count, 0)
