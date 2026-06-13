from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.workflows import translate


class TranslateWorkflowTests(unittest.TestCase):
    def test_chunk_translation_preserves_order_under_out_of_order_completion(self) -> None:
        original_max = translate._MAX_CHUNK_CHARS
        translate._MAX_CHUNK_CHARS = 20
        active = 0
        peak = 0

        async def fake_translate(text: str, model: str) -> str:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                if "## A" in text:
                    await asyncio.sleep(0.03)
                elif "## B" in text:
                    await asyncio.sleep(0.01)
                else:
                    await asyncio.sleep(0)
                return text.replace("English", "Chinese")
            finally:
                active -= 1

        try:
            with patch("app.workflows.translate._translate_chunk", side_effect=fake_translate):
                result = asyncio.run(translate.translate_output({
                    "paper_id": "paper",
                    "language": "zh",
                    "analysis_language": "en",
                    "llm_model": "model",
                    "final_markdown": "## A\nEnglish A\n\n## B\nEnglish B\n\n## C\nEnglish C",
                    "progress": [],
                }))
        finally:
            translate._MAX_CHUNK_CHARS = original_max

        self.assertLessEqual(peak, 3)
        markdown = result["final_markdown"]
        self.assertIn("## A\nChinese A", markdown)
        self.assertIn("## B\nChinese B", markdown)
        self.assertIn("## C\nChinese C", markdown)
        self.assertLess(markdown.index("## A"), markdown.index("## B"))
        self.assertLess(markdown.index("## B"), markdown.index("## C"))
        self.assertEqual(result["progress"][-1], {"step": "translate_output", "status": "done"})

    def test_translation_failure_keeps_original_markdown(self) -> None:
        original_max = translate._MAX_CHUNK_CHARS
        translate._MAX_CHUNK_CHARS = 20

        async def fail_translate(text: str, model: str) -> str:
            raise RuntimeError("translator down")

        try:
            with patch("app.workflows.translate._translate_chunk", side_effect=fail_translate):
                result = asyncio.run(translate.translate_output({
                    "paper_id": "paper",
                    "language": "zh",
                    "analysis_language": "en",
                    "llm_model": "model",
                    "final_markdown": "## A\nEnglish A\n\n## B\nEnglish B",
                    "progress": [],
                }))
        finally:
            translate._MAX_CHUNK_CHARS = original_max

        self.assertNotIn("final_markdown", result)
        self.assertEqual(result["progress"][-1]["step"], "translate_output")
        self.assertEqual(result["progress"][-1]["status"], "failed")
        self.assertIn("translator down", result["progress"][-1]["error"])


if __name__ == "__main__":
    unittest.main()
