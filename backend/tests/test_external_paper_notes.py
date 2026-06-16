from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.db import database as db
from app.services import external_paper_notes
from app.services.external_note_parser import parse_external_note
from app.services.paper_notes_client import PaperNotesClient


class ExternalNoteParserTests(unittest.TestCase):
    def test_parser_extracts_path_title_arxiv_code_and_sections(self) -> None:
        markdown = """# Vision-Language Prompt Calibration

Authors: Ada Lovelace, Alan Turing
Keywords: CLIP, prompt learning, medical segmentation

arXiv: https://arxiv.org/abs/2601.12345
Code: https://github.com/example/prompt-calibration

## Abstract
This paper studies prompt calibration for medical segmentation.

## Method
It calibrates CLIP prompts with uncertainty.

## Experiments
It improves Dice on multiple datasets.

## Limitations
It needs more modality coverage.
"""
        ir = parse_external_note("docs/CVPR2026/ai_safety/prompt-calibration.md", markdown)

        self.assertEqual(ir.conference, "CVPR")
        self.assertEqual(ir.year, 2026)
        self.assertEqual(ir.domain, "ai safety")
        self.assertEqual(ir.title, "Vision-Language Prompt Calibration")
        self.assertEqual(ir.arxiv_id, "2601.12345")
        self.assertEqual(ir.pdf_url, "https://arxiv.org/pdf/2601.12345")
        self.assertEqual(ir.code_url, "https://github.com/example/prompt-calibration")
        self.assertIn("prompt calibration", ir.summary)
        self.assertIn("uncertainty", ir.method)
        self.assertIn("Dice", ir.experiments)
        self.assertIn("modality", ir.limitations)
        self.assertIn("CLIP", ir.keywords)


class PaperNotesClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_falls_back_to_contents_when_recursive_tree_is_truncated(self) -> None:
        client = PaperNotesClient(owner="owner", repo="repo", branch="main", docs_path="docs")
        client.latest_commit_sha = AsyncMock(return_value="abc123")  # type: ignore[method-assign]

        async def fake_get_json(url: str):
            if "/git/trees/" in url:
                return {"truncated": True, "tree": []}
            if "/contents/docs?" in url:
                return [
                    {"type": "dir", "path": "docs/CVPR2026"},
                    {"type": "dir", "path": "docs/assets"},
                ]
            if "/contents/docs/CVPR2026?" in url:
                return [
                    {
                        "type": "file",
                        "path": "docs/CVPR2026/prompt-calibration.md",
                        "sha": "file123",
                        "size": 128,
                        "html_url": "https://github.com/owner/repo/blob/abc123/docs/CVPR2026/prompt-calibration.md",
                        "download_url": "https://raw.githubusercontent.com/owner/repo/abc123/docs/CVPR2026/prompt-calibration.md",
                    },
                    {"type": "file", "path": "docs/CVPR2026/README.md", "sha": "readme", "size": 10},
                ]
            self.fail(f"unexpected GitHub request: {url}")

        client._get_json = fake_get_json  # type: ignore[method-assign]

        files = await client.list_markdown_files()

        self.assertEqual([file.path for file in files], ["docs/CVPR2026/prompt-calibration.md"])
        self.assertEqual(files[0].sha, "file123")


class ExternalPaperNoteServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmp.name) / "app.db")
        await db.init_db()

    async def asyncTearDown(self) -> None:
        await db.close_db()
        self._tmp.cleanup()

    async def test_tables_exist_after_init_and_default_source_is_created(self) -> None:
        source = await external_paper_notes.ensure_default_source()
        self.assertEqual(source["source_id"], "paper_notes")

        tables = await db.fetch_all(
            """
            SELECT name FROM sqlite_master
             WHERE type = 'table'
               AND name IN (
                   'external_sources',
                   'external_paper_notes',
                   'external_note_versions',
                   'external_note_sync_runs',
                   'external_note_matches'
               )
            """
        )
        self.assertEqual({row["name"] for row in tables}, {
            "external_sources",
            "external_paper_notes",
            "external_note_versions",
            "external_note_sync_runs",
            "external_note_matches",
        })

    async def test_sync_upserts_note_and_list_returns_utility_reason(self) -> None:
        class FakeFile:
            path = "docs/CVPR2026/ai_safety/prompt-calibration.md"
            raw_url = "https://raw.example/note.md"
            html_url = "https://github.com/zhaoyang97/Paper-Notes/blob/abc123/docs/CVPR2026/ai_safety/prompt-calibration.md"

        class FakeClient:
            async def latest_commit_sha(self) -> str:
                return "abc123"

            async def list_markdown_files(self, *, max_files: int = 0):
                self.max_files = max_files
                return [FakeFile()]

            async def fetch_markdown(self, raw_url: str) -> str:
                return """# Vision-Language Prompt Calibration

arXiv: https://arxiv.org/abs/2601.12345

## Abstract
CLIP prompt calibration for medical segmentation.

## Method
Prompt learning with uncertainty.
"""

        fake_client = FakeClient()
        with (
            patch("app.services.external_paper_notes.PaperNotesClient", return_value=fake_client),
            patch("app.services.external_note_utility.build_behavior_terms", new=AsyncMock(return_value=["prompt calibration", "medical segmentation"])),
            patch("app.services.external_note_utility.build_profile_terms", new=AsyncMock(return_value=["clip prompt learning"])),
        ):
            sync = await external_paper_notes.sync_paper_notes(force=True)

        self.assertEqual(sync["status"], "done")
        self.assertEqual(sync["inserted"], 1)
        self.assertEqual(fake_client.max_files, 0)
        listed = await external_paper_notes.list_items(limit=10)
        self.assertEqual(listed["total"], 1)
        item = listed["items"][0]
        self.assertEqual(item["arxiv_id"], "2601.12345")
        self.assertGreater(item["utility_score"], 0)
        self.assertIn("Paper-Notes", item["source_url"])

    async def test_add_to_daily_requires_arxiv_and_writes_candidate(self) -> None:
        ir = parse_external_note(
            "docs/CVPR2026/ai_safety/prompt-calibration.md",
            "# Prompt Calibration\n\nhttps://arxiv.org/abs/2601.12345\n\n## Abstract\nUseful note.",
        )
        note_id = await external_paper_notes._upsert_note(  # noqa: SLF001 - service-level persistence test.
            ir,
            source_url="https://github.com/zhaoyang97/Paper-Notes/blob/main/docs/CVPR2026/ai_safety/prompt-calibration.md",
            raw_url="https://raw.githubusercontent.com/zhaoyang97/Paper-Notes/main/docs/CVPR2026/ai_safety/prompt-calibration.md",
            commit_sha="abc123",
        )

        result = await external_paper_notes.add_note_to_daily(note_id)

        self.assertTrue(result["item_id"])
        row = await db.fetch_one("SELECT * FROM daily_recommendation_items WHERE item_id = ?", (result["item_id"],))
        self.assertIsNotNone(row)
        self.assertEqual(row["arxiv_id"], "2601.12345")
        self.assertEqual(row["status"], "candidate")

    async def test_start_note_run_auto_promotes_and_links_run(self) -> None:
        ir = parse_external_note(
            "docs/CVPR2026/ai_safety/prompt-calibration.md",
            "# Prompt Calibration\n\nhttps://arxiv.org/abs/2601.12345\n\n## Abstract\nUseful note.",
        )
        note_id = await external_paper_notes._upsert_note(  # noqa: SLF001 - service-level persistence test.
            ir,
            source_url="https://github.com/zhaoyang97/Paper-Notes/blob/main/docs/CVPR2026/ai_safety/prompt-calibration.md",
            raw_url="https://raw.githubusercontent.com/zhaoyang97/Paper-Notes/main/docs/CVPR2026/ai_safety/prompt-calibration.md",
            commit_sha="abc123",
        )

        async def write_pdf(_url: str, dest_path: Path) -> None:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"%PDF-1.4\n% test\n")

        async def fake_run(**kwargs):
            self.assertEqual(kwargs["mode"], "lens")
            self.assertEqual(kwargs["language"], "zh")
            self.assertEqual(kwargs["owner_token"], "owner-a")
            return {
                "run_id": "run123",
                "paper_id": kwargs["paper_id"],
                "status": "pending",
            }

        with (
            patch("app.services.external_paper_notes._download_pdf", new=AsyncMock(side_effect=write_pdf)),
            patch("app.api.runs.start_background_run", new=AsyncMock(side_effect=fake_run)),
        ):
            result = await external_paper_notes.start_note_run(
                note_id,
                mode="lens",
                language="zh",
                owner_token="owner-a",
                auto_promote=True,
            )

        self.assertEqual(result["run_id"], "run123")
        self.assertTrue(result["paper_id"])
        updated = await external_paper_notes.get_item(note_id)
        self.assertEqual(updated["linked_paper_id"], result["paper_id"])
        self.assertEqual(updated["linked_run_id"], "run123")
        self.assertEqual(updated["status"], "promoted")

    async def test_facets_return_conference_year_and_domain_options(self) -> None:
        ir = parse_external_note(
            "docs/CVPR2026/ai_safety/prompt-calibration.md",
            "# Prompt Calibration\n\nhttps://arxiv.org/abs/2601.12345",
        )
        await external_paper_notes._upsert_note(  # noqa: SLF001 - service-level persistence test.
            ir,
            source_url="https://github.com/zhaoyang97/Paper-Notes/blob/main/docs/CVPR2026/ai_safety/prompt-calibration.md",
            raw_url="https://raw.githubusercontent.com/zhaoyang97/Paper-Notes/main/docs/CVPR2026/ai_safety/prompt-calibration.md",
            commit_sha="abc123",
        )

        facets = await external_paper_notes.list_facets()

        self.assertEqual(facets["conferences"], [{"value": "CVPR", "count": 1}])
        self.assertEqual(facets["years"], [{"value": 2026, "count": 1}])
        self.assertEqual(facets["domains"], [{"value": "ai safety", "count": 1}])
