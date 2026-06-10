from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from app.models.paper_ir import Block, PaperIR, Section


DocumentPart = Literal["main_body", "references", "appendix", "supplementary", "unknown_tail"]


class DocumentPartition(BaseModel):
    paper_id: str
    part: DocumentPart
    title: str = ""
    page_start: int = 0
    page_end: int = 0
    block_start: int = 0
    block_end: int = 0
    section_paths: list[str] = []
    confidence: float = 0.0
    reason: str = ""


_SUPPLEMENTARY_TITLE_RE = re.compile(
    r"\b(supplementary|supplemental|supporting information|supporting material|supplement)\b|补充材料|支撑信息",
    re.IGNORECASE,
)
_APPENDIX_TITLE_RE = re.compile(r"\bappendix\b|附录", re.IGNORECASE)
_REFERENCES_TITLE_RE = re.compile(r"^\s*(?:\d+\.?\s*)?(references|bibliography|参考文献)\s*$", re.IGNORECASE)
_SUPP_FIG_TABLE_RE = re.compile(
    r"\b(?:fig(?:ure)?|table)\s*S\d+\b|\bS\d+\s*(?:fig(?:ure)?|table)\b|Supplementary\s+(?:Fig(?:ure)?|Table)",
    re.IGNORECASE,
)
_APPENDIX_SECTION_RE = re.compile(
    r"\b(appendix\s+[A-Z0-9]|additional experiments|implementation details|proofs?|extended results|ablation details)\b|附录",
    re.IGNORECASE,
)


def _text(block: Block) -> str:
    return (block.text or "").strip()


def _is_heading(block: Block) -> bool:
    return block.type == "title" or len(_text(block)) <= 120


def _section_paths(blocks: Iterable[Block]) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for block in blocks:
        path = (block.section_path or "").strip()
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _page_block_text(paper_ir: PaperIR, page_idx: int, limit: int = 1200) -> str:
    chunks: list[str] = []
    for block in paper_ir.blocks:
        if block.page_idx != page_idx:
            continue
        text = _text(block)
        if text:
            chunks.append(text)
    return " ".join(chunks)[:limit]


def _section_by_title(paper_ir: PaperIR, block: Block) -> Section | None:
    section_path = (block.section_path or "").strip()
    if not section_path:
        return None
    for section in paper_ir.sections:
        if section.path == section_path or section.title == section_path.split("/")[-1]:
            return section
    return None


def _find_references_start(blocks: list[Block]) -> Block | None:
    for block in blocks:
        text = _text(block)
        if not text:
            continue
        if block.type == "title" and _REFERENCES_TITLE_RE.search(text):
            return block
        if _REFERENCES_TITLE_RE.search(text) and len(text) <= 80:
            return block
    return None


def _find_supplementary_start(paper_ir: PaperIR, references: Block | None) -> tuple[Block | None, float, str]:
    blocks = sorted(paper_ir.blocks, key=lambda b: b.order_idx)
    references_order = references.order_idx if references else -1

    best: tuple[Block | None, float, str] = (None, 0.0, "")
    for block in blocks:
        text = _text(block)
        if not text:
            continue
        score = 0.0
        reasons: list[str] = []

        if _SUPPLEMENTARY_TITLE_RE.search(text) and _is_heading(block):
            score = max(score, 0.92)
            reasons.append(f'explicit supplementary heading "{text[:80]}"')

        if _SUPPLEMENTARY_TITLE_RE.search(_page_block_text(paper_ir, block.page_idx)) and block.type == "title":
            score = max(score, 0.85)
            reasons.append("supplementary cue on the same page as a heading")

        section = _section_by_title(paper_ir, block)
        section_text = " ".join(_text(b) for b in (section.blocks if section else [])[:20])
        if _APPENDIX_SECTION_RE.search(text) and _SUPP_FIG_TABLE_RE.search(section_text):
            score = max(score, 0.75)
            reasons.append("appendix/additional section with Figure S/Table S numbering")

        if references and block.order_idx > references_order and _SUPP_FIG_TABLE_RE.search(text):
            score = max(score, 0.60)
            reasons.append("Figure S/Table S cue after References")

        if score > best[1]:
            best = (block, score, "; ".join(reasons))

    return best


def _find_appendix_start(blocks: list[Block], supplementary_start: Block | None) -> tuple[Block | None, float, str]:
    supp_order = supplementary_start.order_idx if supplementary_start else 10**12
    for block in blocks:
        if block.order_idx >= supp_order:
            break
        text = _text(block)
        if not text:
            continue
        if _APPENDIX_TITLE_RE.search(text) and _is_heading(block):
            return block, 0.78, f'appendix heading "{text[:80]}"'
    return None, 0.0, ""


def _make_partition(paper_id: str, part: DocumentPart, blocks: list[Block], title: str, confidence: float, reason: str) -> DocumentPartition | None:
    content_blocks = [b for b in blocks if _text(b) or b.type in {"image", "table", "equation"}]
    if not content_blocks:
        return None
    pages = [b.page_idx for b in content_blocks]
    orders = [b.order_idx for b in content_blocks]
    return DocumentPartition(
        paper_id=paper_id,
        part=part,
        title=title,
        page_start=min(pages) + 1,
        page_end=max(pages) + 1,
        block_start=min(orders),
        block_end=max(orders),
        section_paths=_section_paths(content_blocks),
        confidence=confidence,
        reason=reason,
    )


def partition_paper_ir(paper_ir: PaperIR) -> list[DocumentPartition]:
    blocks = sorted(paper_ir.blocks, key=lambda b: b.order_idx)
    if not blocks:
        return []

    references = _find_references_start(blocks)
    supplementary_start, supp_confidence, supp_reason = _find_supplementary_start(paper_ir, references)
    appendix_start, appendix_confidence, appendix_reason = _find_appendix_start(blocks, supplementary_start)

    ref_order = references.order_idx if references else 10**12
    app_order = appendix_start.order_idx if appendix_start else 10**12
    supp_order = supplementary_start.order_idx if supplementary_start else 10**12
    main_end = min(ref_order, app_order, supp_order)

    partitions: list[DocumentPartition] = []

    main_blocks = [b for b in blocks if b.order_idx < main_end]
    main_reason = "content before References/Appendix/Supplementary boundary"
    main_conf = 0.86 if main_blocks and main_end < 10**12 else 0.70
    main = _make_partition(paper_ir.paper_id, "main_body", main_blocks or blocks, "Main Body", main_conf, main_reason)
    if main:
        partitions.append(main)

    if references:
        ref_end = min(app_order, supp_order)
        ref_blocks = [b for b in blocks if references.order_idx <= b.order_idx < ref_end]
        part = _make_partition(
            paper_ir.paper_id,
            "references",
            ref_blocks,
            "References",
            0.90,
            f'references heading "{_text(references)[:80]}"',
        )
        if part:
            partitions.append(part)

    if appendix_start:
        app_blocks = [b for b in blocks if appendix_start.order_idx <= b.order_idx < supp_order]
        part = _make_partition(
            paper_ir.paper_id,
            "appendix",
            app_blocks,
            _text(appendix_start)[:120] or "Appendix",
            appendix_confidence,
            appendix_reason,
        )
        if part:
            partitions.append(part)

    if supplementary_start and supp_confidence >= 0.60:
        supp_blocks = [b for b in blocks if b.order_idx >= supplementary_start.order_idx]
        part = _make_partition(
            paper_ir.paper_id,
            "supplementary",
            supp_blocks,
            _text(supplementary_start)[:120] or "Supplementary",
            supp_confidence,
            supp_reason,
        )
        if part:
            partitions.append(part)

    if not any(p.part == "main_body" for p in partitions):
        fallback = _make_partition(
            paper_ir.paper_id,
            "main_body",
            blocks,
            "Main Body",
            0.35,
            "partition fallback: no reliable structural boundary found",
        )
        if fallback:
            partitions.insert(0, fallback)

    return sorted(partitions, key=lambda p: (p.block_start, p.part))


def partition_confidence(partitions: list[DocumentPartition]) -> float:
    if not partitions:
        return 0.0
    return min(p.confidence for p in partitions)


def blocks_for_part(paper_ir: PaperIR, partitions: list[DocumentPartition], part: str) -> list[Block]:
    ranges = [(p.block_start, p.block_end) for p in partitions if p.part == part]
    if not ranges:
        return []
    blocks = []
    for block in paper_ir.blocks:
        if any(start <= block.order_idx <= end for start, end in ranges):
            blocks.append(block)
    return blocks


def block_doc_part(block: Block, partitions: list[DocumentPartition]) -> DocumentPart:
    matching = [p for p in partitions if p.block_start <= block.order_idx <= p.block_end]
    if not matching:
        return "unknown_tail"
    matching.sort(key=lambda p: (p.block_end - p.block_start, -p.confidence))
    return matching[0].part


def filter_paper_ir_by_parts(paper_ir: PaperIR, partitions: list[DocumentPartition], allowed_parts: Iterable[str]) -> PaperIR:
    allowed = set(allowed_parts)
    ranges = [(p.block_start, p.block_end) for p in partitions if p.part in allowed]
    if not ranges:
        return paper_ir

    blocks = [
        block for block in paper_ir.blocks
        if any(start <= block.order_idx <= end for start, end in ranges)
    ]
    kept_orders = {block.order_idx for block in blocks}
    sections: list[Section] = []
    for section in paper_ir.sections:
        section_blocks = [block for block in section.blocks if block.order_idx in kept_orders]
        if section_blocks:
            sections.append(section.model_copy(update={"blocks": section_blocks}))

    return paper_ir.model_copy(update={"blocks": blocks, "sections": sections})


def partitions_to_jsonable(partitions: list[DocumentPartition]) -> list[dict[str, object]]:
    return [partition.model_dump() for partition in partitions]
