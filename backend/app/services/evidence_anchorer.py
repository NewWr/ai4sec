from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.models.paper_ir import Block, PaperIR

_CITATION_RE = re.compile(r"\[p\.(\d+)\]", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*|[\u4e00-\u9fff]")
_LATIN_OR_DIGIT_RE = re.compile(r"[a-z0-9]")
_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?(?:e[+-]?\d+)?%?(?![A-Za-z])", re.IGNORECASE)
_MARKDOWN_RE = re.compile(r"[*_`>#\-\[\]()]")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "our", "that", "the", "their", "this",
    "to", "via", "we", "with", "without", "where", "which",
}

ZH_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("开放词汇", ("open", "vocabulary")),
    ("语义分割", ("semantic", "segmentation")),
    ("空间偏置", ("spatial", "bias")),
    ("空间感知", ("spatial", "awareness")),
    ("跨模态", ("cross", "modal")),
    ("文本查询", ("text", "queries")),
    ("语义锚点", ("semantic", "anchors")),
    ("别名", ("alias", "aliases")),
    ("视觉引导", ("visual", "guided")),
    ("显著性", ("saliency",)),
    ("聚合", ("aggregation",)),
    ("注意力", ("attention",)),
    ("自校正", ("self", "correction")),
    ("冻结", ("frozen",)),
    ("微调", ("fine", "tuning")),
    ("训练", ("training",)),
    ("人工标注", ("annotations",)),
    ("推理", ("inference",)),
    ("类别", ("categories", "class")),
    ("基准", ("benchmarks",)),
    ("遥感", ("remote", "sensing")),
    ("自然图像", ("natural", "images")),
    ("城市场景", ("urban", "street", "scenes")),
)

TRAINING_KEYWORDS = {
    "train", "training", "trained", "pretrain", "pretrained", "pre-training",
    "fine-tune", "finetune", "fine-tuning", "optimizer", "optimiser", "adam",
    "adamw", "sgd", "learning", "lr", "batch", "epoch", "epochs", "schedule",
    "scheduler", "warmup", "loss", "gpu", "gpus", "a100", "v100", "tpu",
    "hardware", "implementation", "hyperparameter", "hyperparameters",
    "训练", "预训练", "微调", "优化器", "学习率", "批大小", "轮次", "损失函数", "硬件",
}

TOPIC_KEYWORDS: dict[str, set[str]] = {
    "training": TRAINING_KEYWORDS,
    "method": {"method", "model", "architecture", "algorithm", "framework", "approach", "方法", "模型", "架构", "算法"},
    "dataset": {"dataset", "benchmark", "corpus", "imagenet", "coco", "数据集", "基准"},
    "metric": {"metric", "accuracy", "precision", "recall", "f1", "auc", "bleu", "rouge", "指标", "准确率"},
    "result": {"result", "outperform", "improve", "gain", "performance", "结果", "提升", "性能"},
    "limitation": {"limitation", "fail", "risk", "assumption", "局限", "限制", "风险", "假设"},
    "motivation": {"problem", "challenge", "motivation", "gap", "问题", "挑战", "动机", "空白"},
}

ANCHOR_SCHEMA_VERSION = 3
MIN_HIGHLIGHT_SCORE = 0.70
MIN_HIGHLIGHT_OVERLAP = 4


@dataclass
class Candidate:
    block: Block
    quote: str
    score: float
    reason: str
    token_overlap: int


def _parse_bbox(value: object) -> list[float]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return []
    try:
        x0, y0, x1, y1 = [float(v) for v in value]
    except Exception:
        return []
    if x1 <= x0 or y1 <= y0:
        return []
    return [x0, y0, x1, y1]


def _stable_id(seed: str) -> str:
    return "ev_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _strip_markdown(value: str) -> str:
    return _MARKDOWN_RE.sub(" ", value or "")


def _normalize(value: str) -> str:
    text = str(value or "").replace("-\n", "").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(_normalize(value)):
        token = raw.lower()
        tokens.append(token)
        if any(sep in token for sep in ("-", "_", "/", "+")):
            tokens.extend(part for part in re.split(r"[-_/+]+", token) if len(part) > 1)
    return tokens


def _signal_tokens(value: str) -> list[str]:
    normalized = _normalize(value)
    tokens = [
        token
        for token in _tokens(value)
        if _LATIN_OR_DIGIT_RE.search(token) and token not in STOPWORDS and (len(token) > 1 or token.isdigit())
    ]
    for zh, hints in ZH_HINTS:
        if zh in normalized:
            tokens.extend(hints)
    return tokens


def _numbers(value: str) -> set[str]:
    return set(_NUMBER_RE.findall(_normalize(value)))


def _split_sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "").strip())
    if not clean:
        return []
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(clean) if part.strip()]
    if len(parts) <= 1 and len(clean) > 360:
        return [clean[i:i + 360].strip() for i in range(0, len(clean), 360) if clean[i:i + 360].strip()]
    return parts


def _is_sentence_boundary(text: str, idx: int) -> bool:
    char = text[idx]
    if char == ".":
        prev_char = text[idx - 1] if idx > 0 else ""
        next_char = text[idx + 1] if idx + 1 < len(text) else ""
        return not (prev_char.isdigit() and next_char.isdigit())
    return char in "。;；!?！？"


def _previous_sentence_boundary(text: str, end: int) -> int:
    for idx in range(min(end, len(text) - 1), -1, -1):
        if _is_sentence_boundary(text, idx):
            return idx
    return -1


def _next_sentence_boundary(text: str, start: int) -> int:
    for idx in range(max(0, start), len(text)):
        if _is_sentence_boundary(text, idx):
            return idx
    return -1


def _claim_context(markdown: str, start: int, end: int) -> str:
    line_left = markdown.rfind("\n", 0, start)
    line_right = markdown.find("\n", end)
    if line_right < 0:
        line_right = len(markdown)
    line = markdown[line_left + 1:line_right].strip()
    local_start = start - line_left - 1
    masked = _CITATION_RE.sub(lambda m: " " * (m.end() - m.start()), line)
    pivot = max(0, min(len(masked) - 1, local_start - 1))
    while pivot > 0 and masked[pivot].isspace():
        pivot -= 1
    if pivot > 0 and _is_sentence_boundary(masked, pivot):
        pivot -= 1
    left = _previous_sentence_boundary(masked, pivot)
    right_idx = _next_sentence_boundary(masked, pivot + 1)
    right = right_idx if right_idx >= 0 else len(line)
    context = line[left + 1:right + 1].strip()
    context = _CITATION_RE.sub("", context)
    return _strip_markdown(context).strip()


def _score(claim: str, quote: str) -> tuple[float, str, int]:
    claim_tokens = set(_tokens(claim))
    quote_tokens = set(_tokens(quote))
    if not claim_tokens or not quote_tokens:
        return 0.0, "empty_tokens", 0

    claim_signal = set(_signal_tokens(claim))
    quote_signal = set(_signal_tokens(quote))
    if claim_signal and quote_signal:
        overlap = claim_signal & quote_signal
        precision = len(overlap) / max(1, len(claim_signal))
        focus = len(overlap) / max(1, min(len(quote_signal), len(claim_signal) * 3))
        score = (precision * 0.78) + (focus * 0.22)
    else:
        overlap = claim_tokens & quote_tokens
        precision = len(overlap) / max(1, len(claim_tokens))
        recall = len(overlap) / max(1, len(quote_tokens))
        score = (precision * 0.65) + (recall * 0.35)

    claim_nums = _numbers(claim)
    quote_nums = _numbers(quote)
    if claim_nums:
        matched = len(claim_nums & quote_nums) / max(1, len(claim_nums))
        score = (score * 0.75) + (matched * 0.25)
        if matched == 1.0 and len(overlap) >= 5:
            score = max(score, 0.74)
    normalized_claim = _normalize(claim)
    normalized_quote = _normalize(quote)
    if len(normalized_claim) > 24 and normalized_claim in normalized_quote:
        score = max(score, 0.86)
    if len(normalized_quote) > 24 and normalized_quote in normalized_claim:
        score = max(score, 0.80)

    overlap_count = len(overlap)
    return min(1.0, score), f"token_overlap={overlap_count}", overlap_count


def _highlightable(score: float, token_overlap: int, quote: str) -> bool:
    return bool(quote) and token_overlap >= MIN_HIGHLIGHT_OVERLAP and (
        score >= MIN_HIGHLIGHT_SCORE
        or (score >= 0.62 and token_overlap >= 5)
        or (score >= 0.55 and token_overlap >= 8)
    )


def _status(score: float, has_quote: bool, token_overlap: int) -> str:
    if _highlightable(score, token_overlap, "quote" if has_quote else ""):
        return "resolved"
    if score >= 0.45 and has_quote:
        return "candidate"
    return "page_only"


def _topics(text: str) -> list[str]:
    tokens = set(_tokens(text))
    found = [topic for topic, keywords in TOPIC_KEYWORDS.items() if tokens & keywords]
    return found or ["other"]


def _best_candidate(claim: str, page: int, blocks: list[Block]) -> Candidate | None:
    same_page = [block for block in blocks if block.page_idx + 1 == page and block.text.strip()]
    best: Candidate | None = None
    for block in same_page:
        quotes = _split_sentences(block.text) or [block.text.strip()]
        for quote in quotes:
            score, reason, token_overlap = _score(claim, quote)
            candidate = Candidate(
                block=block,
                quote=quote[:1000],
                score=score,
                reason=reason,
                token_overlap=token_overlap,
            )
            if best is None or candidate.score > best.score:
                best = candidate
    return best


def build_evidence_anchors(
    *,
    markdown: str,
    paper_ir: PaperIR,
    run_id: str,
    mode: str,
    max_anchors: int = 200,
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    blocks = sorted(paper_ir.blocks, key=lambda block: (block.page_idx, block.order_idx))
    for idx, match in enumerate(_CITATION_RE.finditer(markdown or "")):
        if len(anchors) >= max_anchors:
            break
        page = int(match.group(1))
        claim = _claim_context(markdown, match.start(), match.end())
        if not claim:
            claim = f"[p.{page}]"
        best = _best_candidate(claim, page, blocks)
        raw_quote = best.quote if best else ""
        score = best.score if best else 0.0
        token_overlap = best.token_overlap if best else 0
        highlightable = _highlightable(score, token_overlap, raw_quote)
        status = _status(score, bool(raw_quote), token_overlap)
        quote = raw_quote if highlightable else ""
        bbox = _parse_bbox(best.block.bbox if best else [])
        seed = f"{paper_ir.paper_id}:{run_id}:{idx}:{page}:{claim[:160]}"
        anchors.append({
            "schema_version": ANCHOR_SCHEMA_VERSION,
            "anchor_id": _stable_id(seed),
            "paper_id": paper_ir.paper_id,
            "run_id": run_id,
            "mode": mode,
            "citation_index": idx,
            "claim_text": claim[:1000],
            "source_page": page,
            "source_quote": quote,
            "source_block_id": int(best.block.order_idx) if best else 0,
            "source_bbox": bbox if highlightable else [],
            "section_path": best.block.section_path if best else "",
            "topics": _topics(f"{claim} {quote}"),
            "confidence": round(score, 3),
            "status": status,
            "highlightable": highlightable,
            "match_reason": best.reason if best else "no_same_page_text_block",
        })
    return anchors
