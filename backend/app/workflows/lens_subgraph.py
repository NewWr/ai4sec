from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.config import get_settings
from app.models.paper_ir import PaperIR
from app.services.citation_validator import (
    format_coverage_summary,
    validate_citation_coverage,
)
from app.services.evidence_anchorer import build_evidence_anchors
from app.services.llm_service import get_llm_service
from app.services.paper_partitioner import DocumentPartition, filter_paper_ir_by_parts, partition_paper_ir
from app.services.supplementary_indexer import (
    SupplementaryIndex,
    build_supplementary_index,
    format_supplementary_index,
    infer_supplementary_needs,
)
from app.workflows.progress import emit_progress as _emit_progress
from app.workflows.state import MainGraphState

logger = logging.getLogger("scholar.graph")

# Slot names exposed to the evidence extractor. Aligned with the four parts of
# the reader-oriented Lens prompt (overview/motivation → method → experiments →
# critical assessment) so the second LLM call can map quotes back to a section.
LENS_SLOTS: list[str] = [
    "motivation",
    "contribution",
    "method",
    "equation",
    "algorithm",
    "figure",
    "dataset_metric",
    "results",
    "limitation",
]

_SECTION_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)")


def _section_match_keys(paper_ir: PaperIR) -> dict[str, str]:
    """Map each ``section.title`` to a lowercased match string that also includes
    the titles of its numeric ancestors.

    MinerU sometimes flattens heading levels, collapsing ``section_path`` to the
    leaf (e.g. ``5.3 Optimizer`` loses its ``5 Training`` parent). We rebuild the
    ancestor chain from section numbering so a sub-section inherits its parent's
    keyword matches — e.g. ``5.3 Optimizer`` then matches the ``training`` keyword
    and its optimizer/batch/hardware details are no longer dropped.
    """
    num_to_title: dict[str, str] = {}
    for section in paper_ir.sections:
        m = _SECTION_NUM_RE.match(section.title)
        if m:
            num_to_title[m.group(1)] = section.title

    keys: dict[str, str] = {}
    for section in paper_ir.sections:
        titles = [section.title]
        m = _SECTION_NUM_RE.match(section.title)
        if m:
            parts = m.group(1).split(".")
            for i in range(1, len(parts)):
                anc_title = num_to_title.get(".".join(parts[:i]))
                if anc_title:
                    titles.append(anc_title)
        keys[section.title] = " ".join(titles).lower()
    return keys


def _extract_equations(paper_ir: PaperIR) -> list[dict[str, Any]]:
    """Extract equation blocks with context."""
    equations = []
    for block in paper_ir.blocks:
        if block.type in ("equation", "isolate_formula") or "formula" in block.sub_type.lower():
            equations.append({
                "text": block.text,
                "page": block.page_idx + 1,
                "section": block.section_path,
                "bbox": block.bbox,
            })
    return equations


def _extract_algorithms(paper_ir: PaperIR) -> list[dict[str, Any]]:
    """Extract algorithm/code blocks."""
    algos = []
    for block in paper_ir.blocks:
        if block.type in ("code", "algorithm") or "algorithm" in block.sub_type.lower():
            algos.append({
                "text": block.text,
                "page": block.page_idx + 1,
                "section": block.section_path,
                "bbox": block.bbox,
            })
    return algos


def _extract_tables(paper_ir: PaperIR) -> list[dict[str, Any]]:
    """Extract table blocks."""
    tables = []
    for block in paper_ir.blocks:
        if block.type == "table":
            tables.append({
                "text": block.text,
                "page": block.page_idx + 1,
                "section": block.section_path,
                "bbox": block.bbox,
            })
    return tables


def _extract_method_section(paper_ir: PaperIR) -> str:
    """Extract method-related text.

    Matches each section against an ancestor-aware key so nested sub-sections
    (e.g. ``3.2.1 Scaled Dot-Product Attention``) inherit the match from their
    parent (``3 Model Architecture``).
    """
    method_keywords = {
        "method", "approach", "model", "framework", "architecture",
        "proposed", "algorithm", "implementation", "design",
    }
    match_keys = _section_match_keys(paper_ir)
    parts: list[str] = []
    for section in paper_ir.sections:
        key = match_keys.get(section.title, section.title.lower())
        if not any(kw in key for kw in method_keywords):
            continue
        for block in section.blocks:
            if block.type in ("text", "title", "list", "equation"):
                text = block.text.strip()
                if text:
                    parts.append(f"{text} [p.{block.page_idx + 1}]")
    return "\n".join(parts)


def _extract_experiment_section(paper_ir: PaperIR) -> str:
    """Extract experiment / training / results text.

    Includes ``training`` and ``dataset`` keywords and matches against an
    ancestor-aware section key, so reproduction details (optimizer, batch size,
    hardware, schedule) that papers nest under a "Training" section are captured
    instead of surfacing as "not reported".
    """
    exp_keywords = {
        "experiment", "evaluation", "result", "empirical", "ablation",
        "setup", "training", "implementation", "dataset", "benchmark",
    }
    match_keys = _section_match_keys(paper_ir)
    parts: list[str] = []
    for section in paper_ir.sections:
        key = match_keys.get(section.title, section.title.lower())
        if not any(kw in key for kw in exp_keywords):
            continue
        for block in section.blocks:
            if block.type in ("text", "title", "list", "table"):
                text = block.text.strip()
                if text:
                    parts.append(f"{text} [p.{block.page_idx + 1}]")
    return "\n".join(parts)


def _extract_framing_section(paper_ir: PaperIR) -> str:
    """Extract abstract / introduction / related-work / conclusion text.

    Feeds the *Overview & Motivation* part of the report (background, the gap in
    prior work, and the paper's contributions) — material the method/experiment
    extractors do not cover.
    """
    framing_keywords = {
        "abstract", "introduction", "related work", "related", "background",
        "motivation", "conclusion", "conclusions", "summary", "discussion",
    }
    match_keys = _section_match_keys(paper_ir)
    parts: list[str] = []
    for section in paper_ir.sections:
        key = match_keys.get(section.title, section.title.lower())
        if not any(kw in key for kw in framing_keywords):
            continue
        for block in section.blocks:
            if block.type in ("text", "title", "list"):
                text = block.text.strip()
                if text:
                    parts.append(f"{text} [p.{block.page_idx + 1}]")
    return "\n".join(parts)


def _extract_figures(paper_ir: PaperIR) -> list[dict[str, Any]]:
    """Extract figure/image captions with page + section context.

    MinerU stores each figure's caption as the image block's ``text``; empty or
    placeholder captions are skipped so the LLM only sees figures it can actually
    describe to the reader.
    """
    figures: list[dict[str, Any]] = []
    for block in paper_ir.blocks:
        if block.type != "image":
            continue
        caption = block.text.strip()
        if not caption or caption == "[image]":
            continue
        figures.append({
            "text": caption,
            "page": block.page_idx + 1,
            "section": block.section_path,
            "bbox": block.bbox,
            "img_path": block.img_path,
        })
    return figures


# Caption cues that a figure depicts the overall method rather than a result plot.
_FRAMEWORK_FIG_KEYWORDS = (
    "architecture", "framework", "overview", "pipeline", "structure",
    "our method", "our approach", "our model", "proposed method",
    "proposed framework", "proposed model", "overall", "workflow",
    "schematic", "illustration of", "system",
)


def _figure_embed_url(paper_id: str, img_path: str) -> str:
    """Relative URL the frontend resolves (via the Next.js /api rewrite) to the
    backend image route. Empty when the figure has no extracted image file."""
    name = img_path.rsplit("/", 1)[-1] if img_path else ""
    return f"/api/papers/{paper_id}/images/{name}" if name else ""


def _select_framework_figures(
    figures: list[dict[str, Any]], max_n: int = 3
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split figures into (architecture/framework candidates, the rest).

    Candidates are ranked by caption cues and a bonus for "Figure 1" (commonly
    the overview). Only figures that actually have an image file can be
    embedded; if none score, the earliest embeddable figure is used as a
    fallback so the report still shows the paper's lead diagram.
    """
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for i, fig in enumerate(figures):
        cl = fig["text"].lower()
        score = sum(2 for kw in _FRAMEWORK_FIG_KEYWORDS if kw in cl)
        if re.search(r"\b(?:figure|fig\.?)\s*1\b", cl):
            score += 3
        scored.append((score, i, fig))

    embeddable = [s for s in scored if s[2].get("img_path")]
    candidates = sorted((s for s in embeddable if s[0] > 0), key=lambda s: (-s[0], s[1]))
    key = [s[2] for s in candidates[:max_n]]
    if not key and embeddable:
        key = [min(embeddable, key=lambda s: s[1])[2]]

    key_ids = {id(f) for f in key}
    others = [f for f in figures if id(f) not in key_ids]
    return key, others


def _cap_text(text: str, cap: int) -> str:
    text = text.strip()
    if len(text) <= cap:
        return text
    return text[:cap].rstrip() + "\n[...truncated...]"


def _format_pub_rank(pub_rank_json: str) -> str:
    if not pub_rank_json:
        return ""
    try:
        pr = json.loads(pub_rank_json)
    except (json.JSONDecodeError, TypeError):
        return ""

    meta_parts: list[str] = []
    if pr.get("venue"):
        meta_parts.append(f"Published in: {pr['venue']}")
    if pr.get("year"):
        meta_parts.append(f"Year: {pr['year']}")
    if pr.get("sci"):
        meta_parts.append(f"SCI Tier: {pr['sci']}")
    if pr.get("ccf"):
        meta_parts.append(f"CCF Rating: {pr['ccf']}")
    return "[Publication Info: " + " | ".join(meta_parts) + "]" if meta_parts else ""


def _format_key_figures(paper_id: str, figures: list[dict[str, Any]]) -> tuple[str, str]:
    key_figs, other_figs = _select_framework_figures(figures)

    key_lines: list[str] = []
    for f in key_figs:
        cap = _cap_text(f["text"], 300)
        url = _figure_embed_url(paper_id, f.get("img_path", ""))
        alt = cap[:80]
        if url:
            key_lines.append(f"- [p.{f['page']}] {cap}\n  embed: ![{alt}]({url})")
        else:
            key_lines.append(f"- [p.{f['page']}] {cap}  (no image file to embed)")

    other_lines: list[str] = []
    for f in other_figs:
        other_lines.append(f"- [p.{f['page']}] {_cap_text(f['text'], 300)}")

    key_text = ""
    if key_lines:
        key_text = (
            "## Key Architecture Figures (embed these in the Method section)\n"
            + "\n".join(key_lines)
        )
    other_text = ""
    if other_lines:
        other_text = "## Other Figures (captions, for reference)\n" + _cap_text(
            "\n".join(other_lines), 1400
        )
    return key_text, other_text


def _format_equations(equations: list[dict[str, Any]], cap: int = 1800) -> str:
    if not equations:
        return ""
    text = "\n".join(f"- {e['text']} [p.{e['page']}]" for e in equations)
    return "## Extracted Equations\n" + _cap_text(text, cap)


def _format_algorithms(algorithms: list[dict[str, Any]], cap: int = 1200) -> str:
    if not algorithms:
        return ""
    text = "\n".join(f"- {a['text']} [p.{a['page']}]" for a in algorithms)
    return "## Extracted Algorithms\n" + _cap_text(text, cap)


def _format_tables(tables: list[dict[str, Any]], cap: int = 1800) -> str:
    if not tables:
        return ""
    text = "\n".join(f"- [p.{t['page']}] {_cap_text(t['text'], 500)}" for t in tables)
    return "## Extracted Tables\n" + _cap_text(text, cap)


def _full_text_excerpt(paper_ir: PaperIR, cap: int) -> str:
    all_text: list[str] = []
    for block in paper_ir.blocks:
        if block.type in ("text", "title", "list"):
            text = block.text.strip()
            if text:
                all_text.append(f"{text} [p.{block.page_idx + 1}]")
    return _cap_text("\n".join(all_text), cap)


def _join_context(parts: list[str]) -> str:
    return "\n\n".join(p for p in parts if p and p.strip())


def _strip_repeated_heading(markdown: str, heading: str) -> str:
    lines = markdown.strip().splitlines()
    if lines and lines[0].strip() == heading:
        return "\n".join(lines[1:]).lstrip()
    return markdown.strip()


def _load_partitions(state: MainGraphState, paper_ir: PaperIR) -> list[DocumentPartition]:
    raw = state.get("document_partitions_json") or ""
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [DocumentPartition.model_validate(item) for item in data]
        except Exception as exc:
            logger.warning("[%s] lens: failed to parse document_partitions_json — %s", paper_ir.paper_id, exc)
    return partition_paper_ir(paper_ir)


def _load_supplementary_index(
    state: MainGraphState,
    paper_ir: PaperIR,
    partitions: list[DocumentPartition],
) -> SupplementaryIndex:
    raw = state.get("supplementary_index_json") or ""
    if raw:
        try:
            return SupplementaryIndex.model_validate_json(raw)
        except Exception as exc:
            logger.warning("[%s] lens: failed to parse supplementary_index_json — %s", paper_ir.paper_id, exc)
    return build_supplementary_index(paper_ir, partitions)


def _format_partition_summary(partitions: list[DocumentPartition], language: str) -> str:
    if not partitions:
        return ""
    if language == "zh":
        labels = {
            "main_body": "正文",
            "references": "References",
            "appendix": "Appendix",
            "supplementary": "Supplementary",
            "unknown_tail": "未知尾部",
        }
        lines = ["## 文档结构识别"]
        for part in partitions:
            label = labels.get(part.part, part.part)
            lines.append(
                f"- {label}: p.{part.page_start}-p.{part.page_end}, "
                f"confidence={part.confidence:.2f}; {part.reason}"
            )
        return "\n".join(lines)

    lines = ["## Document Partitions"]
    for part in partitions:
        lines.append(
            f"- {part.part}: p.{part.page_start}-p.{part.page_end}, "
            f"confidence={part.confidence:.2f}; {part.reason}"
        )
    return "\n".join(lines)


def _format_supplementary_used(index: SupplementaryIndex, language: str, max_sections: int = 8) -> str:
    if not index.sections:
        return ""
    if language == "zh":
        lines = ["## Supplementary 证据索引"]
        for section in index.sections[:max_sections]:
            page = f"p.{section.page_start}" if section.page_start == section.page_end else f"p.{section.page_start}-p.{section.page_end}"
            evidence = ", ".join(section.evidence_types)
            lines.append(f"- [{section.part} {page}] {section.title}: {evidence}")
        return "\n".join(lines)

    lines = ["## Supplementary Evidence Index"]
    for section in index.sections[:max_sections]:
        page = f"p.{section.page_start}" if section.page_start == section.page_end else f"p.{section.page_start}-p.{section.page_end}"
        evidence = ", ".join(section.evidence_types)
        lines.append(f"- [{section.part} {page}] {section.title}: {evidence}")
    return "\n".join(lines)


def _lens_section_system_prompt(language: str, section_title: str) -> str:
    if language == "zh":
        return f"""你是一名资深的科研论文分析专家。请只撰写 Logic Lens 报告中的 `{section_title}` 这一节。

规则:
1. 只输出这一节,不要输出其他章节、总标题、前言或总结。
2. 使用 Markdown,章节标题必须严格写作 `{section_title}`。
3. 每一条事实性陈述都必须带形如 [p.X] 的页码引用。
4. 所有数学内容使用 LaTeX:行内用 `$...$`,独立公式用 `$$...$$`。
5. 不得编造;只陈述上下文支持的内容。重要信息缺失时简短说明即可。
6. 输出语言为简体中文;LaTeX、页码引用、图片 URL、论文标题、作者姓名、期刊/会议名称保持原样。"""

    return f"""You are an expert research-paper analyst. Write only the `{section_title}` section of a Logic Lens report.

Rules:
1. Output only this section, with no global title, preface, or other sections.
2. Use Markdown, and the section heading must be exactly `{section_title}`.
3. Every factual claim MUST carry a page citation in the form [p.X].
4. Use LaTeX for mathematical content: `$...$` inline and `$$...$$` for display formulas.
5. Do not fabricate; state only what the provided context supports.
6. Keep the section substantive but bounded."""


def _lens_section_specs(language: str) -> list[dict[str, Any]]:
    if language == "zh":
        return [
            {
                "key": "overview",
                "step": "lens_overview",
                "title": "## 1. 概览与动机",
                "instruction": (
                    "说明具体问题、重要性、先前工作的空白或局限、核心贡献及其分别解决的问题。"
                    "若上下文提供期刊/会议、年份或分级,在本节简要说明。"
                ),
            },
            {
                "key": "method_pipeline",
                "step": "lens_method_pipeline",
                "title": "## 2. 方法深读",
                "instruction": (
                    "解释核心思想、端到端流程、主要模块和数据流。"
                    "如有 `embed:` 图片行,在讲解流程的位置逐字复制该 Markdown 图片,随后走读图中组件和数据流。"
                ),
            },
            {
                "key": "method_formulas",
                "step": "lens_method_formulas",
                "title": "## 2. 方法深读",
                "instruction": (
                    "继续撰写方法深读,聚焦关键公式、变量含义、算法步骤、训练机制和这些设计为何有效。"
                    "不要重复概览、模块流程或架构图走读。"
                ),
            },
            {
                "key": "experiments",
                "step": "lens_experiments",
                "title": "## 3. 实验与结果",
                "instruction": (
                    "说明数据集、指标、实验设置和结果解读。不要只复述数字,要结合任务和数据集解释结果意味着什么。"
                ),
            },
            {
                "key": "assessment",
                "step": "lens_assessment",
                "title": "## 4. 批判性评估",
                "instruction": (
                    "分析为何有效、局限与风险、可复现性、要点与开放问题。"
                    "只能依据上下文作出有证据支持的判断。"
                ),
            },
        ]

    return [
        {
            "key": "overview",
            "step": "lens_overview",
            "title": "## 1. Overview & Motivation",
            "instruction": (
                "Explain the concrete problem, why it matters, the gap or limitation in prior work, "
                "and the core contributions. Mention venue/year/rank metadata if present."
            ),
        },
        {
            "key": "method_pipeline",
            "step": "lens_method_pipeline",
            "title": "## 2. Method Deep-Dive",
            "instruction": (
                "Explain the core intuition, pipeline, modules, and data flow. "
                "If an `embed:` line is provided, copy that Markdown image verbatim where you explain the pipeline, "
                "then walk through the diagram."
            ),
        },
        {
            "key": "method_formulas",
            "step": "lens_method_formulas",
            "title": "## 2. Method Deep-Dive",
            "instruction": (
                "Continue the method deep-dive, focusing on key formulas, variable meanings, procedures, "
                "training mechanics, and why these design choices work. Do not repeat the overview, pipeline, "
                "or architecture figure walk-through."
            ),
        },
        {
            "key": "experiments",
            "step": "lens_experiments",
            "title": "## 3. Experiments & Results",
            "instruction": (
                "Explain datasets, metrics, setup, and result interpretation. Do not merely restate numbers."
            ),
        },
        {
            "key": "assessment",
            "step": "lens_assessment",
            "title": "## 4. Critical Assessment",
            "instruction": (
                "Assess why the method works, limitations and risks, reproducibility, takeaways, and open questions. "
                "Ground judgments in the provided context."
            ),
        },
    ]


LENS_SYSTEM_PROMPT_EN = """You are an expert research-paper analyst. Produce a "Logic Lens": a deep, single-paper read-through that makes a researcher truly understand HOW the work operates and WHY it works — not a surface summary. Explain mechanisms, interpret results, and think critically.

Organize the analysis into the four parts below. Keep the four top-level headings, but ADAPT the sub-points to THIS paper: expand what is central, condense what is auxiliary, and drop sub-points that do not apply rather than forcing them. A theory paper, an empirical study, and a systems paper should not read identically.

## 1. Overview & Motivation
- **Problem & why it matters**: the concrete problem, why it is important, and the specific gap or limitation in prior work that this paper targets.
- **Core contributions**: the main contributions / key findings, and the specific problem each one addresses.
- If the context provides venue, year, or ranking metadata, state it briefly here.

## 2. Method Deep-Dive
This is the heart of the analysis — be thorough and concrete here.
- **Core idea & intuition**: state the central insight in plain language first — *why* the approach should work — before the formalism.
- **Pipeline & modules**: the end-to-end data flow and what each major component is responsible for.
- **Key formulas**: for the important equations only, give the formula in LaTeX, the meaning of its variables (add a short symbol table if notation is heavy), the derivation logic / intuition, and how it differs from prior approaches. Skip trivial or boilerplate equations.
- **Key algorithm / procedure**: a step-by-step walkthrough with per-step annotation; discuss complexity when it is relevant.
- **Architecture / framework diagram**: embed the paper's main architecture or framework figure inline, right where you explain the pipeline, by copying its ready-made Markdown image (the `embed:` line) from the `## Key Architecture Figures` context block verbatim. Immediately after the image, walk the reader through the diagram — name each component and trace how data flows through it. This lets the reader see the approach, not just read about it.
- **Other figures**: when you first refer to any other figure, briefly explain in prose what it depicts (from its caption) so the reader grasps it without seeing it.

## 3. Experiments & Results
- **Datasets & metrics**: which datasets and evaluation metrics are used, what each metric actually measures, and why they are appropriate for the task.
- **Setup**: the training / experimental details that ARE reported (optimizer, schedule, key hyperparameters, hardware). Report what is present — do not enumerate every missing field.
- **Results interpretation**: do NOT merely restate numbers. Interpret them in light of the datasets' characteristics, explain what they demonstrate, and draw out the takeaways and what they imply.

## 4. Critical Assessment
- **Why it works**: the likely sources of the method's effectiveness.
- **Limitations & risks**: assumptions, potential confounds, and generalization concerns.
- **Reproducibility**: whether the paper gives enough to reproduce the core results; flag only the genuinely important missing details.
- **Takeaways & open questions**: what this work enables and the promising directions it suggests.

RULES:
1. Every factual claim MUST carry a page citation in the form [p.X].
2. Use LaTeX for ALL mathematical content: `$...$` inline and `$$...$$` for display formulas. A display `$$` must start at the left margin (no indentation), with the LaTeX directly inside the delimiters and no extra blank lines.
3. Prioritize substance and depth on the core method and key results — capture the main points fully; auxiliary details may be condensed. Do not omit valuable content merely to keep the report short.
4. Do NOT fabricate; state only what the provided context supports. When an important detail is genuinely absent, note it briefly in prose — but do NOT pad the report with "not reported" bullets for every missing field. Information density matters more than checklist completeness.
5. Prefer the dedicated `## Paper Framing`, `## Method Section`, `## Experiment Section`, and figure excerpts over `## Full Paper Text`; the targeted excerpts are the most relevant.
6. To display a figure, embed it with the exact Markdown image given in the `## Key Architecture Figures` block — copy the `embed:` line verbatim (both alt text and URL). NEVER invent, guess, or alter an image URL, and do not embed a figure that has no provided URL. Embedding the framework diagram is expected in Part 2; do not embed result/plot figures.
"""


LENS_SYSTEM_PROMPT_ZH = """你是一名资深的科研论文分析专家。请生成一份"逻辑透镜"(Logic Lens):对单篇论文的深度通读式解析,让研究者真正理解这项工作"如何运作"以及"为什么有效"——而不是停留在表面摘要。要讲清机制、解读结果、并进行批判性思考。

请将分析组织为下面四个部分。保留这四个顶层标题,但要根据本篇论文调整各级要点:核心之处展开、辅助之处精简、不适用的要点直接删去而非硬凑。理论型论文、实证研究、系统型论文不应读起来千篇一律。

## 1. 概览与动机
- **问题及其重要性**:具体要解决的问题、它为何重要,以及本文针对的先前工作中的具体空白或局限。
- **核心贡献**:主要贡献 / 关键发现,以及每一项分别解决了什么具体问题。
- 若上下文提供了期刊/会议、年份或分级等元数据,在此简要说明。

## 2. 方法深读
这是分析的核心——此处要详尽而具体。
- **核心思想与直觉**:先用通俗语言说明中心洞见——*为什么*这个方法应当奏效——再进入形式化表述。
- **流程与模块**:端到端的数据流,以及每个主要组件各自负责什么。
- **关键公式**:仅针对重要公式,给出 LaTeX 形式、变量含义(若记号繁多,补一个简短的符号表)、推导逻辑 / 直觉,以及它与先前方法的不同之处。跳过平凡或样板化的公式。
- **关键算法 / 流程**:逐步讲解并对每一步加以注释;在相关时讨论复杂度。
- **架构 / 框架图**:在你讲解流程的位置就地嵌入论文的主架构或框架图——直接从 `## Key Architecture Figures` 上下文块中逐字复制其现成的 Markdown 图片(那行 `embed:`)。在图片紧随其后,带读者走读该图:点出每个组件,并追踪数据如何在其中流动。这样读者能"看见"方法,而不仅是读到它。
- **其他图**:当你首次提到任何其他图时,基于其图注用文字简要说明它描绘了什么,使读者无需看到原图也能理解。

## 3. 实验与结果
- **数据集与指标**:使用了哪些数据集与评测指标、每个指标实际衡量什么、以及它们为何适合该任务。
- **实验设置**:论文中确有报告的训练 / 实验细节(优化器、调度、关键超参数、硬件)。报告确有的内容即可——不要逐一罗列缺失字段。
- **结果解读**:不要只复述数字。结合数据集特性来解读它们、说明它们证明了什么、并提炼出结论与其蕴含的意义。

## 4. 批判性评估
- **为何有效**:该方法有效性的可能来源。
- **局限与风险**:假设、潜在混杂因素,以及泛化方面的隐忧。
- **可复现性**:论文是否给出了足以复现核心结果的信息;仅标注真正重要的缺失细节。
- **要点与开放问题**:这项工作使什么成为可能,以及它指向的有前景的方向。

规则:
1. 每一条事实性陈述都必须带形如 [p.X] 的页码引用。
2. 所有数学内容一律使用 LaTeX:行内用 `$...$`,独立公式用 `$$...$$`。独立的 `$$` 必须从左边距开始(不缩进),LaTeX 直接写在分隔符内,且不要有多余空行。
3. 在核心方法与关键结果上优先保证实质与深度——把要点讲全面;辅助细节可压缩。不要仅为缩短篇幅而省略有价值的内容。
4. 不得编造;只陈述所给上下文支持的内容。当某个重要细节确实缺失时,用文字简短指出即可——但不要为每个缺失字段都堆砌"未报告"的条目。信息密度比清单式的完整更重要。
5. 优先使用专门的 `## Paper Framing`、`## Method Section`、`## Experiment Section` 与图片摘录,而非 `## Full Paper Text`;有针对性的摘录才是最相关的。
6. 要展示某张图,用 `## Key Architecture Figures` 块中给出的确切 Markdown 图片来嵌入——逐字复制那行 `embed:`(alt 文本与 URL 都要)。绝不要臆造、猜测或改动图片 URL,也不要嵌入没有提供 URL 的图。第 2 部分中预期会嵌入框架图;不要嵌入结果/曲线类的图。
7. 输出语言:整篇分析必须用简体中文撰写(包括上面四个部分的标题,请使用中文标题)。但请保留以下内容的英文原样、不得翻译:LaTeX 公式、页码引用 [p.X]、图片嵌入 ![alt](url) 中的 URL、论文标题、作者姓名、期刊/会议名称;专有技术术语首次出现时保留英文并在括号内给出中文解释(如 "self-attention(自注意力)")。
"""


async def run_logic_lens(state: MainGraphState) -> dict[str, Any]:
    """Run Logic Lens deep analysis."""
    paper_id = state["paper_id"]
    t0 = time.perf_counter()

    paper_ir = PaperIR.model_validate_json(state["paper_ir_json"])
    settings = get_settings()
    partitions = _load_partitions(state, paper_ir) if settings.document_partition_enabled else []
    supplementary_index = (
        _load_supplementary_index(state, paper_ir, partitions)
        if settings.supplementary_index_enabled and partitions
        else SupplementaryIndex(paper_id=paper_id)
    )
    min_confidence = min((p.confidence for p in partitions), default=0.0)
    main_paper_ir = (
        filter_paper_ir_by_parts(paper_ir, partitions, ["main_body"])
        if settings.lens_main_body_only
        and partitions
        and min_confidence >= settings.supplementary_detection_min_confidence
        else paper_ir
    )
    logger.info(
        f"[{paper_id}] lens: Parsed PaperIR — {len(paper_ir.sections)} sections, {len(paper_ir.blocks)} blocks; "
        f"main_context={len(main_paper_ir.sections)} sections/{len(main_paper_ir.blocks)} blocks "
        f"supp_index={len(supplementary_index.sections)}"
    )

    framing_text = _extract_framing_section(main_paper_ir)
    equations = _extract_equations(main_paper_ir)
    algorithms = _extract_algorithms(main_paper_ir)
    tables = _extract_tables(main_paper_ir)
    figures = _extract_figures(main_paper_ir)
    method_text = _extract_method_section(main_paper_ir)
    experiment_text = _extract_experiment_section(main_paper_ir)
    logger.info(
        f"[{paper_id}] lens: Extracted — framing={len(framing_text)} chars "
        f"equations={len(equations)} algorithms={len(algorithms)} tables={len(tables)} "
        f"figures={len(figures)} method={len(method_text)} chars experiment={len(experiment_text)} chars"
    )

    pub_rank = _format_pub_rank(state.get("pub_rank_json", ""))
    title_context = f"# Paper: {paper_ir.title}" if paper_ir.title else ""
    partition_summary = _format_partition_summary(partitions, state.get("language", "en"))
    supplementary_index_text = format_supplementary_index(supplementary_index)
    supplementary_context_note = (
        "Use this Supplementary / Appendix index only as auxiliary evidence. "
        "Main contributions must be grounded in the main-body context."
        if state.get("language", "en") != "zh"
        else "该 Supplementary / Appendix 索引仅作为辅助证据；主贡献必须依据正文上下文。"
    )
    key_figures_text, other_figures_text = _format_key_figures(paper_id, figures)
    equations_text = _format_equations(equations)
    algorithms_text = _format_algorithms(algorithms)
    tables_text = _format_tables(tables)
    full_text = _full_text_excerpt(
        paper_ir,
        3000 if framing_text.strip() or method_text.strip() or experiment_text.strip() else 8000,
    )

    context_by_section = {
        "overview": _join_context([
            title_context,
            pub_rank,
            partition_summary,
            "## Paper Framing (abstract / intro / related work / conclusion)\n"
            + _cap_text(framing_text, 4200),
            "## Full Paper Text\n" + _cap_text(full_text, 900),
        ]),
        "method_pipeline": _join_context([
            title_context,
            "## Paper Framing excerpt\n" + _cap_text(framing_text, 1000),
            "## Method Section\n" + _cap_text(method_text, 3000),
            key_figures_text,
        ]),
        "method_formulas": _join_context([
            title_context,
            "## Method Section excerpt\n" + _cap_text(method_text, 2500),
            equations_text,
            algorithms_text,
        ]),
        "experiments": _join_context([
            title_context,
            "## Paper Framing excerpt\n" + _cap_text(framing_text, 900),
            "## Experiment Section\n" + _cap_text(experiment_text, 4200),
            tables_text,
            other_figures_text,
            supplementary_context_note,
            supplementary_index_text,
        ]),
        "assessment": _join_context([
            title_context,
            pub_rank,
            partition_summary,
            "## Paper Framing excerpt\n" + _cap_text(framing_text, 2200),
            "## Method excerpt\n" + _cap_text(method_text, 1800),
            "## Experiment excerpt\n" + _cap_text(experiment_text, 1800),
            "## Full Paper Text excerpt\n" + _cap_text(full_text, 900),
            supplementary_context_note,
            supplementary_index_text,
        ]),
    }
    context = _join_context(list(context_by_section.values()))
    logger.info(
        f"[{paper_id}] lens: Built segmented LLM contexts — combined={len(context)} chars "
        f"overview={len(context_by_section['overview'])} "
        f"method_pipeline={len(context_by_section['method_pipeline'])} "
        f"method_formulas={len(context_by_section['method_formulas'])} "
        f"experiments={len(context_by_section['experiments'])} assessment={len(context_by_section['assessment'])} "
        f"(framing={len(framing_text)} method={len(method_text)} experiment={len(experiment_text)} "
        f"figures={len(figures)})"
    )

    language = state.get("language", "en")
    llm = get_llm_service()
    model = state.get("llm_model", "")
    run_id = state.get("run_id", "")
    progress_entries: list[dict[str, Any]] = []
    sections: list[str] = []

    for spec in _lens_section_specs(language):
        section_context = context_by_section[spec["key"]]
        await _emit_progress(run_id, spec["step"], "running")

        if language == "zh":
            user_content = (
                f"任务: {spec['instruction']}\n\n"
                f"论文上下文:\n{section_context}"
            )
        else:
            user_content = (
                f"Task: {spec['instruction']}\n\n"
                f"Paper context:\n{section_context}"
            )

        messages = [
            {"role": "system", "content": _lens_section_system_prompt(language, spec["title"])},
            {"role": "user", "content": user_content},
        ]

        logger.info(
            f"[{paper_id}] lens: Calling segmented LLM section={spec['key']} "
            f"model={model or '(default)'} prompt={sum(len(m['content']) for m in messages)}"
        )
        t_section = time.perf_counter()
        try:
            section_markdown = await llm.chat(
                messages,
                model=model,
                temperature=0.3,
            )
        except Exception as e:
            await _emit_progress(run_id, spec["step"], "failed", error=str(e))
            raise

        if not section_markdown.strip():
            error = f"LLM returned empty content for Lens section: {spec['key']}"
            await _emit_progress(run_id, spec["step"], "failed", error=error)
            raise RuntimeError(error)

        if spec["key"] == "method_formulas":
            section_markdown = _strip_repeated_heading(section_markdown, spec["title"])
        sections.append(section_markdown.strip())
        progress_entries.append({"step": spec["step"], "status": "done"})
        await _emit_progress(
            run_id,
            spec["step"],
            "done",
            chars=len(section_markdown),
            seconds=round(time.perf_counter() - t_section, 1),
        )
        logger.info(
            f"[{paper_id}] lens: Section {spec['key']} returned in "
            f"{time.perf_counter()-t_section:.1f}s — {len(section_markdown)} chars"
        )

    supplementary_used = _format_supplementary_used(supplementary_index, language)
    markdown = "\n\n".join(s for s in [*sections, supplementary_used] if s)
    logger.info(f"[{paper_id}] lens: Segmented LLM returned {len(markdown)} chars total")

    audit = validate_citation_coverage(markdown)
    logger.info(f"[{paper_id}] lens: {format_coverage_summary(audit)}")
    if audit["claims_uncited"] > 0 and audit["uncited_samples"]:
        logger.warning(
            f"[{paper_id}] lens: {audit['claims_uncited']} uncited claims — samples: {audit['uncited_samples'][:3]}"
        )

    evidence_pool: list[dict[str, Any]] = []
    logger.info(f"[{paper_id}] lens: evidence extraction skipped for segmented Lens")
    evidence_anchors = build_evidence_anchors(
        markdown=markdown,
        paper_ir=paper_ir,
        run_id=str(state.get("run_id") or ""),
        mode="lens",
    )

    logger.info(f"[{paper_id}] lens: TOTAL {time.perf_counter()-t0:.1f}s")
    return {
        "final_markdown": markdown,
        "analysis_language": language,
        "final_json": json.dumps({
            "mode": "lens",
            "paper_id": state["paper_id"],
            "title": paper_ir.title,
            "num_equations": len(equations),
            "num_algorithms": len(algorithms),
            "num_tables": len(tables),
            "num_figures": len(figures),
            "document_partitions": [partition.model_dump() for partition in partitions],
            "supplementary_index": supplementary_index.model_dump(),
            "supplementary_needs": infer_supplementary_needs(supplementary_index),
            "citation_audit": audit,
            "evidence_pool": evidence_pool,
            "evidence_anchors": evidence_anchors,
        }, ensure_ascii=False),
        "progress": state.get("progress", []) + progress_entries + [{"step": "run_lens", "status": "done"}],
    }
