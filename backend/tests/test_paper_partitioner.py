from __future__ import annotations

import unittest

from app.models.paper_ir import Block, PaperIR, Section
from app.services.paper_partitioner import blocks_for_part, filter_paper_ir_by_parts, partition_paper_ir
from app.services.supplementary_indexer import build_supplementary_index, infer_supplementary_needs


def _block(order: int, page: int, text: str, section: str, type_: str = "text") -> Block:
    return Block(type=type_, page_idx=page, order_idx=order, text=text, section_path=section)


def _paper(blocks: list[Block]) -> PaperIR:
    sections: list[Section] = []
    by_section: dict[str, list[Block]] = {}
    for block in blocks:
        by_section.setdefault(block.section_path, []).append(block)
    for path, section_blocks in by_section.items():
        sections.append(Section(path=path, title=path.split("/")[-1], level=1, blocks=section_blocks))
    return PaperIR(paper_id="paper", title="Partition Test", blocks=blocks, sections=sections)


class PaperPartitionerTests(unittest.TestCase):
    def test_plain_paper_without_supplementary_keeps_main_body(self) -> None:
        paper_ir = _paper([
            _block(0, 0, "Abstract", "Abstract", "title"),
            _block(1, 0, "This paper proposes a method.", "Abstract"),
            _block(2, 1, "1 Introduction", "1 Introduction", "title"),
            _block(3, 1, "Main introduction.", "1 Introduction"),
            _block(4, 8, "References", "References", "title"),
            _block(5, 8, "Doe et al. 2025.", "References"),
        ])

        partitions = partition_paper_ir(paper_ir)

        self.assertEqual([p.part for p in partitions], ["main_body", "references"])
        self.assertEqual(partitions[0].page_start, 1)
        self.assertEqual(partitions[0].page_end, 2)

    def test_references_then_explicit_supplementary_is_split(self) -> None:
        paper_ir = _paper([
            _block(0, 0, "Abstract", "Abstract", "title"),
            _block(1, 0, "Main claim.", "Abstract"),
            _block(2, 7, "References", "References", "title"),
            _block(3, 7, "Doe et al. 2025.", "References"),
            _block(4, 8, "Supplementary Material", "Supplementary Material", "title"),
            _block(5, 8, "Implementation Details. Optimizer Adam, batch size 64.", "Supplementary Material"),
            _block(6, 9, "Figure S1: Additional ablation.", "Supplementary Material", "image"),
        ])

        partitions = partition_paper_ir(paper_ir)
        supp = next(p for p in partitions if p.part == "supplementary")

        self.assertGreaterEqual(supp.confidence, 0.90)
        self.assertEqual(supp.page_start, 9)
        self.assertEqual([b.order_idx for b in blocks_for_part(paper_ir, partitions, "supplementary")], [4, 5, 6])

    def test_appendix_and_supplementary_are_distinct(self) -> None:
        paper_ir = _paper([
            _block(0, 0, "1 Introduction", "1 Introduction", "title"),
            _block(1, 0, "Main text.", "1 Introduction"),
            _block(2, 6, "Appendix A Proofs", "Appendix A Proofs", "title"),
            _block(3, 6, "Proof of Lemma 1.", "Appendix A Proofs"),
            _block(4, 8, "Supplementary Information", "Supplementary Information", "title"),
            _block(5, 8, "Table S1 reports extra experiments.", "Supplementary Information", "table"),
        ])

        partitions = partition_paper_ir(paper_ir)

        self.assertEqual([p.part for p in partitions], ["main_body", "appendix", "supplementary"])
        appendix = next(p for p in partitions if p.part == "appendix")
        supplementary = next(p for p in partitions if p.part == "supplementary")
        self.assertEqual(appendix.page_start, 7)
        self.assertEqual(supplementary.page_start, 9)

    def test_filter_paper_ir_by_main_body_excludes_supplementary(self) -> None:
        paper_ir = _paper([
            _block(0, 0, "1 Introduction", "1 Introduction", "title"),
            _block(1, 0, "Main text.", "1 Introduction"),
            _block(2, 5, "Supplementary Material", "Supplementary Material", "title"),
            _block(3, 5, "Figure S1 extra results.", "Supplementary Material"),
        ])
        partitions = partition_paper_ir(paper_ir)

        main_ir = filter_paper_ir_by_parts(paper_ir, partitions, ["main_body"])

        self.assertEqual([block.order_idx for block in main_ir.blocks], [0, 1])
        self.assertNotIn("Supplementary", "\n".join(block.text for block in main_ir.blocks))

    def test_supplementary_index_infers_evidence_types_and_needs(self) -> None:
        paper_ir = _paper([
            _block(0, 0, "1 Introduction", "1 Introduction", "title"),
            _block(1, 0, "Main text.", "1 Introduction"),
            _block(2, 4, "Supplementary Material", "Supplementary Material", "title"),
            _block(3, 4, "Implementation Details. Optimizer Adam, learning rate 1e-4.", "Supplementary Material"),
            _block(4, 5, "Additional Ablations. Table S2 compares component variants.", "Supplementary Material", "table"),
        ])
        partitions = partition_paper_ir(paper_ir)

        index = build_supplementary_index(paper_ir, partitions)
        needs = infer_supplementary_needs(index)

        evidence_types = {etype for section in index.sections for etype in section.evidence_types}
        self.assertIn("implementation", evidence_types)
        self.assertIn("ablation", evidence_types)
        self.assertTrue(any(need["need"] == "hyperparameters for reproducibility" for need in needs))
        self.assertTrue(any(need["need"] == "ablation evidence" for need in needs))


if __name__ == "__main__":
    unittest.main()
