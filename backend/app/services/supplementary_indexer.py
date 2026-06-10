from __future__ import annotations

import re
from collections import defaultdict

from pydantic import BaseModel

from app.models.paper_ir import Block, PaperIR
from app.services.paper_partitioner import DocumentPartition, block_doc_part


class SupplementaryIndexSection(BaseModel):
    title: str
    part: str
    page_start: int = 0
    page_end: int = 0
    summary: str = ""
    evidence_types: list[str] = []
    use_when: list[str] = []


class SupplementaryIndex(BaseModel):
    paper_id: str
    sections: list[SupplementaryIndexSection] = []
    total_chars: int = 0
    truncated: bool = False


_EVIDENCE_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("implementation", ("implementation", "optimizer", "batch", "learning rate", "hyperparameter", "training detail", "architecture"), ("reproducibility", "method detail")),
    ("ablation", ("ablation", "component", "variant", "sensitivity"), ("component contribution", "evidence strength")),
    ("extended_experiment", ("additional experiment", "extended result", "more results", "benchmark", "dataset"), ("experiment validation", "robustness")),
    ("proof", ("proof", "lemma", "theorem", "derivation"), ("theoretical validation", "method detail")),
    ("figure_table", ("figure s", "fig. s", "table s", "supplementary table"), ("evidence lookup", "result details")),
)


def _cap_text(text: str, cap: int) -> tuple[str, bool]:
    text = " ".join(text.split())
    if len(text) <= cap:
        return text, False
    return text[:cap].rstrip() + " ...", True


def _infer_evidence_types(text: str) -> tuple[list[str], list[str]]:
    text_l = text.lower()
    evidence: list[str] = []
    use_when: list[str] = []
    for evidence_type, keywords, uses in _EVIDENCE_RULES:
        if any(keyword in text_l for keyword in keywords):
            evidence.append(evidence_type)
            for use in uses:
                if use not in use_when:
                    use_when.append(use)
    return evidence or ["supplementary_detail"], use_when or ["source verification"]


def _section_title(block: Block) -> str:
    path = (block.section_path or "").strip()
    if path:
        return path.split("/")[-1].strip()
    if block.type == "title" and block.text.strip():
        return block.text.strip()
    return "Supplementary"


def build_supplementary_index(
    paper_ir: PaperIR,
    partitions: list[DocumentPartition],
    *,
    max_chars: int = 18000,
    section_summary_chars: int = 900,
) -> SupplementaryIndex:
    grouped: dict[tuple[str, str], list[Block]] = defaultdict(list)
    for block in sorted(paper_ir.blocks, key=lambda b: b.order_idx):
        part = block_doc_part(block, partitions)
        if part not in {"supplementary", "appendix"}:
            continue
        text = (block.text or "").strip()
        if not text:
            continue
        grouped[(part, _section_title(block))].append(block)

    sections: list[SupplementaryIndexSection] = []
    total_chars = 0
    truncated = False

    for (part, title), blocks in sorted(grouped.items(), key=lambda item: min(b.order_idx for b in item[1])):
        pages = [block.page_idx + 1 for block in blocks]
        raw_text = "\n".join(block.text.strip() for block in blocks if block.text.strip())
        summary, was_truncated = _cap_text(raw_text, section_summary_chars)
        evidence_types, use_when = _infer_evidence_types(f"{title}\n{raw_text}")
        total_chars += len(raw_text)
        truncated = truncated or was_truncated
        sections.append(
            SupplementaryIndexSection(
                title=title or part,
                part=part,
                page_start=min(pages),
                page_end=max(pages),
                summary=summary,
                evidence_types=evidence_types,
                use_when=use_when,
            )
        )
        if sum(len(section.summary) for section in sections) >= max_chars:
            truncated = True
            break

    return SupplementaryIndex(
        paper_id=paper_ir.paper_id,
        sections=sections,
        total_chars=total_chars,
        truncated=truncated,
    )


def format_supplementary_index(index: SupplementaryIndex, max_chars: int = 6000) -> str:
    if not index.sections:
        return ""
    lines = ["## Supplementary / Appendix Index"]
    for section in index.sections:
        page = f"p.{section.page_start}" if section.page_start == section.page_end else f"p.{section.page_start}-p.{section.page_end}"
        evidence = ", ".join(section.evidence_types)
        uses = ", ".join(section.use_when)
        lines.append(
            f"- [{section.part} {page}] {section.title}: {section.summary} "
            f"(evidence: {evidence}; use when: {uses})"
        )
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n[...supplementary index truncated...]"
    return text


_NEED_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hyperparameters for reproducibility": ("implementation", "hyperparameter", "optimizer", "batch", "learning rate", "training detail"),
    "ablation evidence": ("ablation", "component", "variant", "sensitivity"),
    "additional experimental evidence": ("additional experiment", "extended result", "benchmark", "dataset", "robustness"),
    "proof or derivation details": ("proof", "theorem", "lemma", "derivation"),
}


def infer_supplementary_needs(index: SupplementaryIndex) -> list[dict[str, str]]:
    needs: list[dict[str, str]] = []
    index_text = "\n".join(f"{s.title}\n{s.summary}\n{' '.join(s.evidence_types)}" for s in index.sections).lower()
    for need, keywords in _NEED_KEYWORDS.items():
        if any(keyword in index_text for keyword in keywords):
            target_sections = [
                section.title for section in index.sections
                if any(keyword in f"{section.title} {section.summary} {' '.join(section.evidence_types)}".lower() for keyword in keywords)
            ][:5]
            needs.append({
                "need": need,
                "target_sections": ", ".join(target_sections),
                "reason": f"Supplementary index contains cues for {need}.",
            })
    return needs
