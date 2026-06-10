from __future__ import annotations

import unittest

from app.models.paper_ir import Block, PaperIR, Section
from app.services.evidence_anchorer import build_evidence_anchors


def _paper() -> PaperIR:
    blocks = [
        Block(
            type="text",
            page_idx=1,
            order_idx=1,
            section_path="Method",
            text="We train the model with AdamW for 100 epochs using a batch size of 256.",
        ),
        Block(
            type="text",
            page_idx=2,
            order_idx=2,
            section_path="Results",
            text="The method improves accuracy by 4.2% on ImageNet and outperforms prior baselines.",
        ),
    ]
    return PaperIR(
        paper_id="paper1",
        title="Anchor Test",
        blocks=blocks,
        sections=[Section(path="Method", title="Method", blocks=[blocks[0]])],
    )


class EvidenceAnchorTests(unittest.TestCase):
    def test_builds_ordered_anchors_and_marks_training_topic(self) -> None:
        markdown = (
            "- The setup uses AdamW training for 100 epochs with batch size 256 [p.2]\n"
            "- Accuracy improves by 4.2% on ImageNet [p.3]"
        )

        anchors = build_evidence_anchors(markdown=markdown, paper_ir=_paper(), run_id="run1", mode="snap")

        self.assertEqual(len(anchors), 2)
        self.assertEqual([a["citation_index"] for a in anchors], [0, 1])
        self.assertEqual(anchors[0]["source_page"], 2)
        self.assertIn("AdamW", anchors[0]["source_quote"])
        self.assertIn("training", anchors[0]["topics"])
        self.assertEqual(anchors[0]["status"], "resolved")
        self.assertEqual(anchors[1]["source_page"], 3)
        self.assertIn("4.2%", anchors[1]["source_quote"])

    def test_unmatched_page_degrades_to_page_only(self) -> None:
        anchors = build_evidence_anchors(
            markdown="This claim only has a page reference [p.9]",
            paper_ir=_paper(),
            run_id="run1",
            mode="lens",
        )

        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["status"], "page_only")
        self.assertEqual(anchors[0]["source_quote"], "")


if __name__ == "__main__":
    unittest.main()
