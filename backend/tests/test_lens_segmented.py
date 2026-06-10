from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from app.models.paper_ir import Block, PaperIR, Section
from app.workflows.lens_subgraph import run_logic_lens


class _FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def chat(self, messages, model="", temperature=0.3):
        self.calls.append({
            "messages": messages,
            "model": model,
            "temperature": temperature,
        })
        heading = messages[0]["content"].split("`")[1]
        return f"{heading}\n\nSegment response [p.1]"


def _large_paper_ir() -> PaperIR:
    intro = Block(
        type="text",
        page_idx=0,
        order_idx=1,
        text=("This paper studies dense vision-language inference and motivates VIP. " * 80).strip(),
        section_path="1 Introduction",
    )
    method = Block(
        type="text",
        page_idx=2,
        order_idx=2,
        text=("The method evolves visual-guided prompts through modular optimization. " * 180).strip(),
        section_path="3 Method",
    )
    experiment = Block(
        type="text",
        page_idx=6,
        order_idx=3,
        text=("Experiments evaluate segmentation and detection benchmarks with multiple metrics. " * 180).strip(),
        section_path="4 Experiments",
    )
    figure = Block(
        type="image",
        page_idx=3,
        order_idx=4,
        text="Figure 1: Overview of the proposed VIP framework.",
        section_path="3 Method",
        img_path="images/fig1.jpg",
    )
    table = Block(
        type="table",
        page_idx=7,
        order_idx=5,
        text="Table 1 reports benchmark scores.",
        section_path="4 Experiments",
    )
    equation = Block(
        type="equation",
        page_idx=4,
        order_idx=6,
        text=r"L = L_{task} + \lambda L_{prompt}",
        section_path="3 Method",
    )
    return PaperIR(
        paper_id="paper",
        title="VIP Test Paper",
        blocks=[intro, method, experiment, figure, table, equation],
        sections=[
            Section(path="1 Introduction", title="1 Introduction", level=1, blocks=[intro]),
            Section(path="3 Method", title="3 Method", level=1, blocks=[method, figure, equation]),
            Section(path="4 Experiments", title="4 Experiments", level=1, blocks=[experiment, table]),
        ],
    )


class LensSegmentedTests(unittest.TestCase):
    def test_logic_lens_splits_method_into_two_llm_calls(self) -> None:
        fake_llm = _FakeLLM()
        state = {
            "paper_id": "paper",
            "run_id": "run",
            "paper_ir_json": _large_paper_ir().model_dump_json(),
            "pub_rank_json": json.dumps({"venue": "arXiv.org", "year": 2026}),
            "language": "zh",
            "llm_model": "model",
            "progress": [],
        }

        with patch("app.workflows.lens_subgraph.get_llm_service", return_value=fake_llm), patch(
            "app.workflows.lens_subgraph._emit_progress",
        ):
            result = asyncio.run(run_logic_lens(state))

        self.assertEqual(len(fake_llm.calls), 5)
        self.assertLessEqual(
            max(sum(len(m["content"]) for m in c["messages"]) for c in fake_llm.calls),
            9000,
        )
        self.assertIn("## 1. 概览与动机", result["final_markdown"])
        self.assertIn("## 2. 方法深读", result["final_markdown"])
        self.assertIn("## 3. 实验与结果", result["final_markdown"])
        self.assertIn("## 4. 批判性评估", result["final_markdown"])
        self.assertEqual([p["step"] for p in result["progress"][-6:-1]], [
            "lens_overview",
            "lens_method_pipeline",
            "lens_method_formulas",
            "lens_experiments",
            "lens_assessment",
        ])

    def test_logic_lens_keeps_supplementary_out_of_main_context(self) -> None:
        fake_llm = _FakeLLM()
        paper_ir = _large_paper_ir()
        supplement_title = Block(
            type="title",
            page_idx=10,
            order_idx=7,
            text="Supplementary Material",
            section_path="Supplementary Material",
        )
        supplement_text = Block(
            type="text",
            page_idx=10,
            order_idx=8,
            text="Supplementary secret optimizer detail and Figure S1 ablation.",
            section_path="Supplementary Material",
        )
        paper_ir.blocks.extend([supplement_title, supplement_text])
        paper_ir.sections.append(
            Section(
                path="Supplementary Material",
                title="Supplementary Material",
                level=1,
                blocks=[supplement_title, supplement_text],
            )
        )
        state = {
            "paper_id": "paper",
            "run_id": "run",
            "paper_ir_json": paper_ir.model_dump_json(),
            "pub_rank_json": "{}",
            "language": "en",
            "llm_model": "model",
            "progress": [],
        }

        with patch("app.workflows.lens_subgraph.get_llm_service", return_value=fake_llm), patch(
            "app.workflows.lens_subgraph._emit_progress",
        ):
            result = asyncio.run(run_logic_lens(state))

        prompts = [call["messages"][1]["content"] for call in fake_llm.calls]
        self.assertNotIn("Supplementary secret optimizer detail", prompts[1])
        supplementary_prompts = [p for p in prompts if "Supplementary / Appendix Index" in p]
        self.assertTrue(supplementary_prompts)
        self.assertIn("Supplementary secret optimizer detail", supplementary_prompts[0])
        data = json.loads(result["final_json"])
        self.assertTrue(any(p["part"] == "supplementary" for p in data["document_partitions"]))


if __name__ == "__main__":
    unittest.main()
