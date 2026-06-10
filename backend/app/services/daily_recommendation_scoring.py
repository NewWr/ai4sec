from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


DEFAULT_TOPICS: list[dict[str, Any]] = [
    {
        "id": "medical_image_deep_learning",
        "name": "Deep Learning for Medical Imaging",
        "name_zh": "医学图像深度学习",
        "arxiv_categories": ["cs.CV", "cs.LG", "cs.AI", "eess.IV"],
        "must": {
            "any": [
                ["medical", "image"],
                ["medical", "imaging"],
                ["radiology"],
                ["pathology", "image"],
                ["histopathology"],
                ["microscopy", "image"],
                ["retinal", "image"],
                ["fundus"],
                ["ct", "image"],
                ["mri"],
                ["ultrasound", "image"],
                ["x-ray"],
                ["biomedical", "image"],
                ["clinical", "image"],
            ]
        },
        "should": [
            "deep learning",
            "foundation model",
            "vision-language",
            "multimodal",
            "clip",
            "segment anything",
            "sam",
            "dino",
            "dinov2",
            "transformer",
            "segmentation",
            "classification",
            "detection",
            "diagnosis",
            "representation learning",
            "self-supervised",
            "weakly supervised",
            "domain generalization",
            "benchmark",
            "report",
        ],
        "exclude": [
            "quantum",
            "black hole",
            "lattice",
            "astrophysics",
            "stellar",
            "galaxy",
            "cosmology",
            "maple leaf",
        ],
        "min_score": 0.64,
        "sort_order": 10,
    },
    {
        "id": "clip_prompt_learning",
        "name": "CLIP Prompt Learning",
        "name_zh": "CLIP 提示学习",
        "arxiv_categories": ["cs.CV", "cs.LG", "cs.AI", "cs.CL", "eess.IV"],
        "must": {
            "any": [
                ["clip", "prompt"],
                ["vision-language", "prompt"],
                ["vision language", "prompt"],
                ["visual", "prompt", "learning"],
                ["prompt", "tuning", "vision"],
                ["prompt", "learning", "vision"],
                ["context optimization"],
                ["test-time", "prompt"],
                ["test time", "prompt"],
                ["prompt", "adapter", "clip"],
            ]
        },
        "should": [
            "prompt learning",
            "prompt tuning",
            "context optimization",
            "test-time adaptation",
            "test-time prompt tuning",
            "domain adaptation",
            "domain generalization",
            "few-shot",
            "zero-shot",
            "open-vocabulary",
            "text prompt",
            "visual prompt",
            "class prompt",
            "calibration",
            "contrastive learning",
            "medical",
            "remote sensing",
            "segmentation",
            "detection",
        ],
        "exclude": [
            "quantum",
            "black hole",
            "lattice",
            "astrophysics",
            "stellar",
            "galaxy",
            "cosmology",
            "maple leaf",
        ],
        "min_score": 0.68,
        "sort_order": 20,
    },
    {
        "id": "sam_segmentation",
        "name": "SAM and Segmentation Foundation Models",
        "name_zh": "SAM 分割与分割基础模型",
        "arxiv_categories": ["cs.CV", "cs.LG", "cs.AI", "eess.IV"],
        "must": {
            "any": [
                ["segment anything"],
                ["sam", "segmentation"],
                ["sam2", "segmentation"],
                ["segmentation", "foundation", "model"],
                ["foundation model", "segmentation"],
                ["promptable", "segmentation"],
                ["interactive", "segmentation"],
                ["universal", "segmentation"],
                ["open-vocabulary", "segmentation"],
                ["open vocabulary", "segmentation"],
            ]
        },
        "should": [
            "segment anything model",
            "medsam",
            "sam2",
            "mobile sam",
            "efficient sam",
            "adapter",
            "prompt",
            "mask",
            "interactive segmentation",
            "semantic segmentation",
            "instance segmentation",
            "panoptic segmentation",
            "zero-shot",
            "few-shot",
            "domain generalization",
            "medical",
            "remote sensing",
            "video",
            "lesion",
            "organ",
        ],
        "exclude": [
            "quantum",
            "black hole",
            "lattice",
            "astrophysics",
            "stellar",
            "galaxy",
            "cosmology",
            "maple leaf",
        ],
        "min_score": 0.68,
        "sort_order": 30,
    },
    {
        "id": "dino_self_supervised",
        "name": "DINO-style Self-supervised Vision",
        "name_zh": "DINO 自监督视觉表示学习",
        "arxiv_categories": ["cs.CV", "cs.LG", "cs.AI", "eess.IV"],
        "must": {
            "any": [
                ["dino", "self-supervised"],
                ["dino", "self supervised"],
                ["dinov2"],
                ["self-supervised", "vision", "transformer"],
                ["self supervised", "vision", "transformer"],
                ["self-supervised", "visual", "representation"],
                ["self supervised", "visual", "representation"],
                ["masked", "image", "modeling"],
                ["visual", "foundation", "model"],
            ]
        },
        "should": [
            "dino",
            "dinov2",
            "dinov3",
            "self-supervised learning",
            "self supervised learning",
            "representation learning",
            "vision transformer",
            "foundation model",
            "pretraining",
            "masked image modeling",
            "distillation",
            "contrastive learning",
            "dense prediction",
            "domain adaptation",
            "medical",
            "remote sensing",
            "detection",
            "segmentation",
        ],
        "exclude": [
            "dinosaur",
            "quantum",
            "black hole",
            "lattice",
            "astrophysics",
            "stellar",
            "galaxy",
            "cosmology",
        ],
        "min_score": 0.68,
        "sort_order": 40,
    },
    {
        "id": "clip_model_design_transfer",
        "name": "CLIP Model Design and Transfer",
        "name_zh": "CLIP 模型设计与跨方向迁移",
        "arxiv_categories": ["cs.CV", "cs.LG", "cs.AI", "cs.CL", "eess.IV"],
        "must": {
            "any": [
                ["clip", "architecture"],
                ["clip", "model", "design"],
                ["clip", "adapter"],
                ["clip", "alignment"],
                ["clip", "contrastive"],
                ["clip", "fine-tuning"],
                ["clip", "transfer"],
                ["clip", "domain"],
                ["clip", "open-vocabulary"],
                ["clip", "open vocabulary"],
                ["vision-language", "architecture"],
                ["vision-language", "adapter"],
                ["image-text", "alignment"],
                ["image text", "alignment"],
                ["vision-language", "transfer"],
                ["vision language", "transfer"],
            ]
        },
        "should": [
            "prompt learning",
            "adapter",
            "lora",
            "parameter-efficient",
            "fine-tuning",
            "transfer learning",
            "domain adaptation",
            "domain generalization",
            "open-vocabulary",
            "compositional",
            "zero-shot",
            "few-shot",
            "retrieval",
            "classification",
            "detection",
            "segmentation",
            "medical",
            "remote sensing",
            "video",
            "3d",
        ],
        "exclude": [
            "quantum",
            "black hole",
            "lattice",
            "astrophysics",
            "stellar",
            "galaxy",
            "cosmology",
            "maple leaf",
        ],
        "min_score": 0.68,
        "sort_order": 50,
    },
]

_WORD_RE_CACHE: dict[str, re.Pattern[str]] = {}


@dataclass(frozen=True)
class ScoreResult:
    keep: bool
    score: float
    detail: dict[str, Any]
    reason: str


def normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _term_pattern(term: str) -> re.Pattern[str]:
    key = term.lower().strip()
    pat = _WORD_RE_CACHE.get(key)
    if pat is not None:
        return pat
    escaped = re.escape(key)
    if re.fullmatch(r"[a-z0-9]+", key):
        pat = re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)
    else:
        pat = re.compile(escaped, re.IGNORECASE)
    _WORD_RE_CACHE[key] = pat
    return pat


def contains_term(haystack: str, term: str) -> bool:
    term = (term or "").strip()
    if not term:
        return False
    return bool(_term_pattern(term).search(haystack))


def _group_matches(haystack: str, group: list[str]) -> bool:
    return all(contains_term(haystack, term) for term in group)


def _category_matches(categories: list[str], allowed: list[str]) -> bool:
    allowed_set = {c.strip() for c in allowed if c.strip()}
    return any(c in allowed_set for c in categories)


def score_paper(
    *,
    title: str,
    abstract: str,
    categories: list[str],
    primary_category: str,
    topic: dict[str, Any],
    feedback_penalty: float = 0.0,
    default_min_score: float = 0.68,
) -> ScoreResult:
    haystack = normalize_text(f"{title} {abstract}")
    title_norm = normalize_text(title)
    allowed_categories = [str(c) for c in topic.get("arxiv_categories") or []]
    all_categories = [primary_category, *categories]
    category_ok = _category_matches(all_categories, allowed_categories)
    if allowed_categories and not category_ok:
        return ScoreResult(
            keep=False,
            score=0.0,
            detail={"category_ok": False, "categories": categories, "allowed": allowed_categories},
            reason="类别不匹配",
        )

    exclude_terms = [str(t) for t in topic.get("exclude") or []]
    excluded = [term for term in exclude_terms if contains_term(haystack, term)]
    if excluded:
        return ScoreResult(
            keep=False,
            score=0.0,
            detail={"excluded": excluded, "category_ok": category_ok},
            reason=f"命中排除词：{', '.join(excluded[:4])}",
        )

    must_groups = ((topic.get("must") or {}).get("any") or [])
    matched_groups = [
        [str(term) for term in group]
        for group in must_groups
        if isinstance(group, list) and _group_matches(haystack, [str(term) for term in group])
    ]
    if must_groups and not matched_groups:
        return ScoreResult(
            keep=False,
            score=0.0,
            detail={"must_ok": False, "category_ok": category_ok},
            reason="未满足强相关条件",
        )

    should_terms = [str(t) for t in topic.get("should") or []]
    matched_should = [term for term in should_terms if contains_term(haystack, term)]
    title_hits = [term for term in should_terms if contains_term(title_norm, term)]

    category_score = 1.0 if category_ok or not allowed_categories else 0.0
    # `must.any` is a hard gate: satisfying one group is already strong evidence.
    # Additional groups should help ranking, but not be required.
    must_score = 1.0 if matched_groups or not must_groups else 0.0
    should_score = min(1.0, len(matched_should) / 3.0)
    abstract_focus_score = min(1.0, (len(title_hits) * 0.30) + (len(matched_should) * 0.12))
    feedback_score = max(-1.0, min(0.2, feedback_penalty))

    score = (
        category_score * 0.25
        + must_score * 0.30
        + should_score * 0.25
        + abstract_focus_score * 0.15
        + 0.05
        + feedback_score
    )
    score = max(0.0, min(1.0, score))
    min_score = float(topic.get("min_score") or default_min_score)
    reason_parts = []
    if category_ok and primary_category:
        reason_parts.append(f"类别 {primary_category}")
    if matched_groups:
        reason_parts.append("强条件 " + " / ".join("+".join(g) for g in matched_groups[:2]))
    if matched_should:
        reason_parts.append("相关词 " + ", ".join(matched_should[:5]))
    if feedback_penalty < 0:
        reason_parts.append("历史反馈降权")

    return ScoreResult(
        keep=score >= min_score,
        score=round(score, 4),
        detail={
            "category_ok": category_ok,
            "matched_must": matched_groups,
            "matched_should": matched_should,
            "excluded": [],
            "category_score": category_score,
            "must_score": must_score,
            "should_score": should_score,
            "abstract_focus_score": abstract_focus_score,
            "feedback_score": feedback_score,
            "min_score": min_score,
        },
        reason="；".join(reason_parts) or "规则匹配",
    )
