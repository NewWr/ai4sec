from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.db import database as db
from app.models.schemas import (
    DiscoveryEdgeResponse,
    DiscoveryEvidenceResponse,
    DiscoveryGapResponse,
    DiscoveryNodeResponse,
    DiscoveryReadingPathResponse,
    DiscoveryScoreResponse,
    DiscoveryStatsResponse,
    DiscoveryThemeResponse,
    PapersDiscoveryResponse,
)
from app.services.translation_cache import translate_text
from app.services import evidence_store
from app.services import knowledge_synthesis
from app.services.llm_runtime_config import get_llm_runtime_config
from app.services.llm_service import get_llm_service


DISCOVERY_VERSION = 2
EXTRACTOR = "rule_v1"
VERIFIER_VERSION = "rule_verifier_v1"
LLM_VERIFIER_VERSION = "llm_relation_verifier_v1"
PROMPT_VERSION = "none"
MODEL_VERSION = "none"
logger = logging.getLogger("scholar.research_discovery")

_DISPLAY_LABELS = {
    "uses_same_dataset": "使用相同数据集",
    "uses the same dataset": "使用相同数据集",
    "same_problem": "相同研究问题",
    "same research problem": "相同研究问题",
    "method_variant": "方法变体",
    "method variant": "方法变体",
    "transferable_method": "可迁移方法",
    "transferable method": "可迁移方法",
    "conflicting_claim": "冲突结论",
    "conflicting claim": "冲突结论",
    "same normalized dataset": "相同标准化数据集",
    "no dataset match": "没有数据集匹配",
    "same problem domain/task/setting": "相同问题领域、任务或设定",
    "different top-level task": "顶层任务不同",
    "same method family": "相同方法族",
    "different paper context": "论文上下文不同",
    "exact same paper only": "仅限同一篇论文",
    "source method exists": "存在源方法",
    "target problem exists": "存在目标问题",
    "requires manual feasibility review": "需要人工可行性复核",
    "no same-task performance claim required": "不要求相同任务的性能声明",
    "not generated without source method and target problem": "缺少源方法或目标问题时不生成",
    "same task/problem": "相同任务或问题",
    "same metric": "相同指标",
    "opposite result direction": "结果方向相反",
    "not emitted without shared task and metric": "没有共享任务和指标时不生成",
    "uncovered": "未覆盖",
    "partially_covered": "部分覆盖",
    "partially covered": "部分覆盖",
    "covered": "已覆盖",
    "insufficient_corpus": "语料不足",
    "insufficient corpus": "语料不足",
    "unknown": "未知",
    "candidate": "候选",
    "confirmed": "已保留",
    "rejected": "已忽略",
    "needs_more_evidence": "需要更多证据",
    "needs more evidence": "需要更多证据",
    "promoted_to_idea": "已提升为想法",
    "promoted to idea": "已提升为想法",
    "same metric/problem with negative result": "相同指标或问题下存在负向结果",
    "verifier: source and target evidence are present": "验证：源证据与目标证据均存在",
    "verifier: source and target are distinct papers": "验证：源论文与目标论文不同",
    "verifier: exact dataset label match": "验证：数据集标签精确匹配",
    "verifier: shared problem taxonomy": "验证：研究问题分类一致",
    "verifier: shared method family": "验证：方法族一致",
    "verifier: relation is a transfer hypothesis, not direct evidence of feasibility": "验证：该关系是迁移假设，不直接证明可行性",
    "verifier: same task/problem and metric evidence found": "验证：存在相同任务/问题与指标证据",
    "verifier: result and claim evidence have opposing polarity": "验证：结果与主张存在方向差异",
    "verifier: shared dataset evidence found": "验证：存在共享数据集证据",
    "verifier: missing source or target evidence": "验证：缺少源证据或目标证据",
    "verifier: dataset labels diverge": "验证：数据集标签不一致",
    "verifier: problem evidence not aligned": "验证：研究问题证据未对齐",
    "verifier: method family not aligned": "验证：方法族未对齐",
    "verifier: transfer feasibility is not established": "验证：迁移可行性尚未成立",
    "verifier: conflict lacks same dataset support": "验证：冲突缺少相同数据集支撑",
    "verifier: dataset setting not matched": "验证：数据集设定未匹配",
    "verifier: method setting not matched": "验证：方法设定未匹配",
    "llm: relation accepted": "LLM：关系成立",
    "llm: relation needs more evidence": "LLM：需要更多证据",
    "llm: relation rejected": "LLM：关系不成立",
    "llm: verifier failed; kept rule verifier result": "LLM：验证失败，保留规则验证结果",
    "Review evidence objects first, then compare relation checks and gap counter-evidence.": "先查看证据对象，再对比关系检查和反向证据。",
    "Evaluate method transfer across tasks": "评估方法跨任务迁移",
    "Resolve limitation": "解决局限",
    "Corpus evidence audit": "语料证据审查",
    "A focused method or evaluation change can address an explicit limitation in the local corpus.": "有针对性的方法或评估调整可能解决本地语料中的明确局限。",
    "A method used in one local paper may transfer to another local task if assumptions and failure modes hold.": "如果假设和失效模式成立，一篇本地论文中的方法可能迁移到另一项任务。",
    "The current local corpus may be too small for reliable innovation claims.": "当前本地语料可能不足以支撑可靠的创新判断。",
    "Transferable-method relation generated only when source method evidence and target problem evidence both exist.": "仅在同时存在源方法证据和目标问题证据时生成可迁移方法关系。",
    "Collect more papers or verify extracted evidence before promoting a gap to an idea.": "在将缺口提升为研究想法前，需要补充论文或核验抽取证据。",
    "Compare the proposed change against the closest local baseline on the same task, dataset, and metric.": "在相同任务、数据集和指标上，将 proposed 变更与最接近的本地基线比较。",
    "Run a small transfer pilot and record which source-task assumptions break on the target task.": "先运行小规模迁移验证，并记录哪些源任务假设在目标任务上不成立。",
    "Add or verify at least three papers for the target theme, then regenerate relations and gaps.": "为目标主题补充或核验至少三篇论文后，再重新生成关系和缺口。",
    "retinal biomarker prediction": "视网膜生物标志物预测",
    "dense vision-language prediction": "密集视觉语言预测",
    "multimodal representation alignment": "多模态表征对齐",
    "efficient vision-language inference": "高效视觉语言推理",
    "visual-guided prompt evolution": "视觉引导的提示词演化",
    "clip-style contrastive learning": "CLIP 风格对比学习",
    "multimodal structural cue fusion": "多模态结构线索融合",
    "supervised medical image prediction": "监督式医学图像预测",
    "problem/medical_ai/biomarker_prediction": "医学 AI 生物标志物预测",
    "problem/vision_language/dense_prediction": "密集视觉语言预测",
    "problem/multimodal_learning/representation_alignment": "多模态表征对齐",
    "problem/efficient_ai/inference": "高效视觉语言推理",
    "method/prompt_optimization": "提示词优化",
    "method/representation_learning": "表征学习",
    "method/multimodal_fusion": "多模态融合",
    "method/prediction_model": "预测模型",
}

_STOPWORDS = {
    "a",
    "about",
    "across",
    "additional",
    "additionally",
    "after",
    "all",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "based",
    "be",
    "by",
    "can",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "model",
    "models",
    "of",
    "on",
    "or",
    "paper",
    "papers",
    "proposed",
    "the",
    "this",
    "to",
    "using",
    "with",
}

_PROBLEM_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("problem/medical_ai/biomarker_prediction/retinal_fundus", "Retinal biomarker prediction", ("retinal", "fundus", "biomarker", "cardiometabolic")),
    ("problem/vision_language/dense_prediction/open_vocabulary", "Dense vision-language prediction", ("vision-language", "dense", "segmentation", "detection", "open-vocabulary")),
    ("problem/multimodal_learning/representation_alignment/structural_cues", "Multimodal representation alignment", ("multimodal", "structural", "clip", "alignment", "image-text")),
    ("problem/efficient_ai/inference/vision_language", "Efficient vision-language inference", ("efficient", "inference", "latency", "token", "prompt")),
)

_METHOD_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("method/prompt_optimization/evolution/visual_guided", "visual-guided prompt evolution", ("prompt", "evolution", "visual-guided")),
    ("method/representation_learning/contrastive/clip_style", "CLIP-style contrastive learning", ("clip", "contrastive", "image-text")),
    ("method/multimodal_fusion/structural_cues/auxiliary_signal", "multimodal structural cue fusion", ("structural", "cue", "fusion", "multimodal")),
    ("method/prediction_model/supervised/medical_image", "supervised medical image prediction", ("prediction", "classification", "regression", "medical")),
)

_DATASET_PATTERNS = (
    re.compile(r"\b([A-Z][A-Za-z0-9_-]*(?:-[A-Za-z0-9]+)*)(?:\s+dataset|\s+benchmark)\b"),
    re.compile(r"\b(dataset|benchmark)\s+([A-Z][A-Za-z0-9_-]*(?:-[A-Za-z0-9]+)*)\b"),
)

_METRIC_TERMS = {
    "accuracy",
    "auc",
    "auroc",
    "f1",
    "precision",
    "recall",
    "miou",
    "dice",
    "latency",
    "throughput",
    "mae",
    "rmse",
}

_LIMITATION_HINTS = (
    "limitation",
    "limited",
    "future work",
    "does not",
    "not address",
    "fails",
    "challenge",
    "constraint",
    "requires",
)

_CLAIM_HINTS = (
    "achieve",
    "achieves",
    "outperform",
    "outperforms",
    "improve",
    "improves",
    "reduce",
    "reduces",
    "show",
    "shows",
    "demonstrate",
    "demonstrates",
)

_NEGATIVE_RESULT_HINTS = (
    "does not improve",
    "fails to",
    "worse than",
    "underperforms",
    "no significant",
    "negative result",
)


@dataclass(frozen=True)
class EvidenceDraft:
    evidence_type: str
    paper_id: str
    block_id: int
    page: int
    quote: str
    normalized_label: str
    taxonomy_path: str
    confidence: float


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _loads_any_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _loads_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _hash(parts: list[str]) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _fingerprint(draft: EvidenceDraft) -> str:
    return _hash([
        draft.paper_id,
        str(draft.block_id),
        draft.evidence_type,
        draft.normalized_label,
        draft.quote[:180],
    ])


def _evidence_id(draft: EvidenceDraft) -> str:
    return _hash(["evidence", _fingerprint(draft)])[:24]


def _relation_id(relation_type: str, source_paper_id: str, target_paper_id: str, source_ids: list[str], target_ids: list[str]) -> str:
    left, right = sorted([source_paper_id, target_paper_id])
    return _hash(["relation", relation_type, left, right, ",".join(sorted(source_ids)), ",".join(sorted(target_ids))])[:24]


def _gap_id(title: str, evidence_ids: list[str]) -> str:
    return _hash(["gap", title, ",".join(sorted(evidence_ids))])[:24]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _append_history(raw: Any, entry: dict[str, Any], *, limit: int = 80) -> str:
    try:
        history = json.loads(raw) if isinstance(raw, str) else (raw or [])
        if not isinstance(history, list):
            history = []
    except Exception:
        history = []
    history.append(entry)
    return _json(history[-limit:])


def _quote(text: str, max_len: int = 420) -> str:
    text = _normalize(text)
    return text[: max_len - 1] + "…" if len(text) > max_len else text


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+-]{2,}", text.lower())
    return {word for word in words if word not in _STOPWORDS and not word.isdigit()}


def _title_case_label(label: str) -> str:
    known = {"clip": "CLIP", "vlm": "VLM", "ai": "AI"}
    return " ".join(known.get(part, part.capitalize()) for part in re.split(r"[\s_-]+", label) if part)


def _match_rules(text_l: str, rules: tuple[tuple[str, str, tuple[str, ...]], ...]) -> list[tuple[str, str, list[str]]]:
    out: list[tuple[str, str, list[str]]] = []
    compact = text_l.replace("-", " ")
    for taxonomy, label, terms in rules:
        hits = [term for term in terms if term in text_l or term.replace("-", " ") in compact]
        if hits:
            out.append((taxonomy, label, hits))
    return out


async def _load_rows(limit: int) -> list[dict[str, Any]]:
    return await db.fetch_all(
        """
        SELECT
            p.paper_id,
            COALESCE(p.title, '') AS title,
            COALESCE(p.venue, '') AS venue,
            COALESCE(p.year, 0) AS year,
            COALESCE(mp.status, '') AS parse_status,
            COALESCE(ds.status, '') AS dify_status,
            COALESCE(lr.status, '') AS latest_run_status
          FROM papers p
          LEFT JOIN (
            SELECT
                paper_id,
                CASE
                    WHEN SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) > 0 THEN 'done'
                    ELSE MAX(status)
                END AS status
              FROM mineru_parses
             GROUP BY paper_id
          ) mp ON mp.paper_id = p.paper_id
          LEFT JOIN (
            SELECT
                paper_id,
                CASE
                    WHEN SUM(CASE WHEN status = 'synced' THEN 1 ELSE 0 END) > 0 THEN 'synced'
                    ELSE MAX(status)
                END AS status
              FROM dify_syncs
             GROUP BY paper_id
          ) ds ON ds.paper_id = p.paper_id
          LEFT JOIN (
            SELECT r1.paper_id, r1.status
              FROM runs r1
              JOIN (
                SELECT paper_id, MAX(started_at) AS max_started_at
                  FROM runs
                 GROUP BY paper_id
              ) rx ON rx.paper_id = r1.paper_id AND rx.max_started_at = r1.started_at
          ) lr ON lr.paper_id = p.paper_id
         ORDER BY p.created_at DESC
         LIMIT ?
        """,
        (limit,),
    )


async def _load_rows_for_papers(paper_ids: list[str]) -> list[dict[str, Any]]:
    paper_ids = [paper_id for paper_id in dict.fromkeys(str(pid) for pid in paper_ids if pid)]
    if not paper_ids:
        return []
    placeholders = ",".join("?" for _ in paper_ids)
    rows = await db.fetch_all(
        f"""
        SELECT
            p.paper_id,
            COALESCE(p.title, '') AS title,
            COALESCE(p.venue, '') AS venue,
            COALESCE(p.year, 0) AS year,
            COALESCE(mp.status, '') AS parse_status,
            COALESCE(ds.status, '') AS dify_status,
            COALESCE(lr.status, '') AS latest_run_status
          FROM papers p
          LEFT JOIN (
            SELECT
                paper_id,
                CASE
                    WHEN SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) > 0 THEN 'done'
                    ELSE MAX(status)
                END AS status
              FROM mineru_parses
             GROUP BY paper_id
          ) mp ON mp.paper_id = p.paper_id
          LEFT JOIN (
            SELECT
                paper_id,
                CASE
                    WHEN SUM(CASE WHEN status = 'synced' THEN 1 ELSE 0 END) > 0 THEN 'synced'
                    ELSE MAX(status)
                END AS status
              FROM dify_syncs
             GROUP BY paper_id
          ) ds ON ds.paper_id = p.paper_id
          LEFT JOIN (
            SELECT r1.paper_id, r1.status
              FROM runs r1
              JOIN (
                SELECT paper_id, MAX(started_at) AS max_started_at
                  FROM runs
                 GROUP BY paper_id
              ) rx ON rx.paper_id = r1.paper_id AND rx.max_started_at = r1.started_at
          ) lr ON lr.paper_id = p.paper_id
         WHERE p.paper_id IN ({placeholders})
         ORDER BY p.created_at DESC
        """,
        tuple(paper_ids),
    )
    row_by_id = {str(row.get("paper_id") or ""): row for row in rows}
    return [row_by_id[paper_id] for paper_id in paper_ids if paper_id in row_by_id]


async def _load_blocks(paper_ids: list[str]) -> list[dict[str, Any]]:
    if not paper_ids:
        return []
    placeholders = ",".join("?" for _ in paper_ids)
    return await db.fetch_all(
        f"""
        SELECT block_id, paper_id, page_idx, text, section_path, order_idx, type
          FROM blocks
         WHERE paper_id IN ({placeholders})
           AND length(trim(text)) > 0
         ORDER BY paper_id, order_idx ASC
        """,
        tuple(paper_ids),
    )


def _drafts_from_block(block: dict[str, Any], title: str) -> list[EvidenceDraft]:
    paper_id = str(block.get("paper_id") or "")
    block_id = int(block.get("block_id") or 0)
    page = int(block.get("page_idx") or 0) + 1
    text = _normalize(str(block.get("text") or ""))
    if not text:
        return []
    section = str(block.get("section_path") or "").lower()
    text_l = text.lower()
    context = f"{title} {section} {text}"
    context_l = context.lower()
    quote = _quote(text)
    drafts: list[EvidenceDraft] = []

    for taxonomy, label, hits in _match_rules(context_l, _PROBLEM_RULES):
        drafts.append(EvidenceDraft("problem", paper_id, block_id, page, quote, label, taxonomy, min(0.92, 0.62 + len(hits) * 0.08)))
    for taxonomy, label, hits in _match_rules(context_l, _METHOD_RULES):
        drafts.append(EvidenceDraft("method", paper_id, block_id, page, quote, label, taxonomy, min(0.9, 0.58 + len(hits) * 0.08)))

    for pattern in _DATASET_PATTERNS:
        for match in pattern.finditer(text):
            label = match.group(1 if match.group(1).lower() not in {"dataset", "benchmark"} else 2)
            if len(label) > 2 and label.lower() not in {"the", "this", "our"}:
                drafts.append(EvidenceDraft("dataset", paper_id, block_id, page, quote, label, f"evaluation/dataset/{label.lower()}", 0.66))

    metric_hits = sorted(term for term in _METRIC_TERMS if re.search(rf"\b{re.escape(term)}\b", text_l))
    for metric in metric_hits[:4]:
        drafts.append(EvidenceDraft("metric", paper_id, block_id, page, quote, metric.upper() if len(metric) <= 5 else metric, f"evaluation/metric/{metric}", 0.7))

    if any(hint in text_l for hint in _LIMITATION_HINTS) or "limitation" in section or "future" in section:
        label = " / ".join(sorted(_tokens(text))[:3]) or "limitation"
        drafts.append(EvidenceDraft("limitation", paper_id, block_id, page, quote, label, "limitation/explicit_or_inferred", 0.72 if "limitation" in text_l or "future" in text_l else 0.58))

    if any(hint in text_l for hint in _CLAIM_HINTS) or "result" in section or "conclusion" in section:
        label = " / ".join(sorted(_tokens(text))[:3]) or "claim"
        drafts.append(EvidenceDraft("claim", paper_id, block_id, page, quote, label, "claim/performance_or_contribution", 0.64))

    if any(hint in text_l for hint in _NEGATIVE_RESULT_HINTS):
        label = " / ".join(sorted(_tokens(text))[:3]) or "negative result"
        drafts.append(EvidenceDraft("result", paper_id, block_id, page, quote, label, "result/negative_or_null", 0.8))

    return drafts


def _fallback_title_drafts(row: dict[str, Any]) -> list[EvidenceDraft]:
    title = str(row.get("title") or "")
    paper_id = str(row.get("paper_id") or "")
    if not title or not paper_id:
        return []
    fake_block = {"paper_id": paper_id, "block_id": 0, "page_idx": 1, "text": title, "section_path": "title"}
    return _drafts_from_block(fake_block, title)


def _compact_drafts(drafts: list[EvidenceDraft]) -> list[EvidenceDraft]:
    per_label: dict[tuple[str, str, str], EvidenceDraft] = {}
    for draft in drafts:
        key = (draft.paper_id, draft.evidence_type, draft.normalized_label.lower())
        current = per_label.get(key)
        if current is None or (draft.confidence, len(draft.quote)) > (current.confidence, len(current.quote)):
            per_label[key] = draft

    limits = {
        "problem": 8,
        "method": 8,
        "dataset": 8,
        "metric": 10,
        "limitation": 8,
        "claim": 10,
        "result": 6,
    }
    by_paper_type: dict[tuple[str, str], list[EvidenceDraft]] = defaultdict(list)
    for draft in per_label.values():
        by_paper_type[(draft.paper_id, draft.evidence_type)].append(draft)

    compacted: list[EvidenceDraft] = []
    for (_, evidence_type), items in by_paper_type.items():
        items.sort(key=lambda item: (-item.confidence, item.page, item.normalized_label))
        compacted.extend(items[: limits.get(evidence_type, 6)])
    return compacted


async def _upsert_evidence(drafts: list[EvidenceDraft]) -> None:
    if not drafts:
        return
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for draft in drafts:
        eid = _evidence_id(draft)
        if eid in seen:
            continue
        seen.add(eid)
        rows.append(
            {
                "evidence_id": eid,
                "evidence_type": draft.evidence_type,
                "paper_id": draft.paper_id,
                "block_id": draft.block_id,
                "page": draft.page,
                "quote": draft.quote,
                "normalized_label": draft.normalized_label,
                "taxonomy_path": draft.taxonomy_path,
                "confidence": draft.confidence,
                "extractor": EXTRACTOR,
                "model_version": MODEL_VERSION,
                "prompt_version": PROMPT_VERSION,
                "source_hash": _fingerprint(draft),
            }
        )
    await evidence_store.upsert_evidence_many(rows)


async def _load_evidence(paper_ids: list[str]) -> list[dict[str, Any]]:
    if not paper_ids:
        return []
    placeholders = ",".join("?" for _ in paper_ids)
    return await db.fetch_all(
        f"""
        SELECT
            rei.*,
            COALESCE(b.text, '') AS full_block_text
          FROM research_evidence_items rei
          LEFT JOIN blocks b ON b.block_id = rei.block_id AND b.paper_id = rei.paper_id
         WHERE rei.paper_id IN ({placeholders})
           AND rei.status != 'rejected'
         ORDER BY rei.paper_id, rei.evidence_type, rei.confidence DESC, rei.page ASC
        """,
        tuple(paper_ids),
    )


async def _clear_auto_discovery(paper_ids: list[str]) -> None:
    if not paper_ids:
        return
    placeholders = ",".join("?" for _ in paper_ids)
    await db.execute(
        f"""
        DELETE FROM research_evidence_items
         WHERE paper_id IN ({placeholders})
           AND extractor = ?
           AND status = 'unverified'
        """,
        tuple(paper_ids + [EXTRACTOR]),
    )
    await db.execute(
        f"""
        DELETE FROM research_relation_edges
         WHERE (source_paper_id IN ({placeholders}) OR target_paper_id IN ({placeholders}))
           AND status = 'unverified'
        """,
        tuple(paper_ids + paper_ids),
    )
    await db.execute(
        """
        DELETE FROM research_gaps
         WHERE status = 'candidate'
        """
    )


async def _clear_auto_relations_for_scope(paper_ids: list[str]) -> None:
    if not paper_ids:
        return
    placeholders = ",".join("?" for _ in paper_ids)
    await db.execute(
        f"""
        DELETE FROM research_relation_edges
         WHERE (source_paper_id IN ({placeholders}) OR target_paper_id IN ({placeholders}))
           AND status IN ('unverified', 'needs_more_evidence')
           AND rule_id LIKE 'rule_%'
        """,
        tuple(paper_ids + paper_ids),
    )


def _group_evidence(evidence: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for item in evidence:
        grouped[str(item.get("paper_id") or "")][str(item.get("evidence_type") or "")].append(item)
    return grouped


def _taxonomy_prefix(path: str, depth: int) -> str:
    parts = [part for part in path.split("/") if part]
    return "/".join(parts[:depth])


def _shared_by_type(left: dict[str, list[dict[str, Any]]], right: dict[str, list[dict[str, Any]]], evidence_type: str, depth: int = 2) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    out: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for a in left.get(evidence_type, []):
        a_key = _taxonomy_prefix(str(a.get("taxonomy_path") or ""), depth) or str(a.get("normalized_label") or "").lower()
        for b in right.get(evidence_type, []):
            b_key = _taxonomy_prefix(str(b.get("taxonomy_path") or ""), depth) or str(b.get("normalized_label") or "").lower()
            if a_key and a_key == b_key:
                out.append((a, b, a_key))
    return out


def _same_label_pairs(left: dict[str, list[dict[str, Any]]], right: dict[str, list[dict[str, Any]]], evidence_type: str) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    out: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for a in left.get(evidence_type, []):
        a_label = str(a.get("normalized_label") or "").lower()
        for b in right.get(evidence_type, []):
            b_label = str(b.get("normalized_label") or "").lower()
            if a_label and a_label == b_label:
                out.append((a, b, a_label))
    return out


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _evidence_for_ids(evidence_by_id: dict[str, dict[str, Any]], ids: list[str], evidence_type: str = "") -> list[dict[str, Any]]:
    items = [evidence_by_id[eid] for eid in ids if eid in evidence_by_id]
    if evidence_type:
        items = [item for item in items if str(item.get("evidence_type") or "") == evidence_type]
    return items


def _evidence_id_list(items: list[dict[str, Any]]) -> list[str]:
    return _unique([str(item.get("evidence_id") or "") for item in items])


def _selected_evidence_types(evidence_by_id: dict[str, dict[str, Any]], ids: list[str]) -> set[str]:
    return {
        str(item.get("evidence_type") or "")
        for item in _evidence_for_ids(evidence_by_id, ids)
        if item.get("evidence_type")
    }


def _comparability_schema(
    *,
    relation_type: str,
    shared_task: bool = False,
    shared_dataset: bool = False,
    shared_metric: bool = False,
    shared_setting: bool = False,
    claim_direction: str = "unknown",
    verdict: str = "needs_more_evidence",
) -> dict[str, Any]:
    missing: list[str] = []
    if relation_type in {"same_problem", "conflicting_claim"} and not shared_task:
        missing.append("task")
    if relation_type in {"uses_same_dataset", "conflicting_claim"} and not shared_dataset:
        missing.append("dataset")
    if relation_type == "conflicting_claim" and not shared_metric:
        missing.append("metric")
    if relation_type in {"conflicting_claim", "method_variant"} and not shared_setting:
        missing.append("setting")
    return {
        "task": "matched" if shared_task else "missing",
        "dataset": "matched" if shared_dataset else "missing",
        "metric": "matched" if shared_metric else "missing",
        "setting": "matched" if shared_setting else "missing",
        "claim_direction": claim_direction,
        "missing": missing,
        "verdict": verdict if not missing else "needs_more_evidence",
    }


def _setting_counter_ids(
    left: dict[str, list[dict[str, Any]]],
    right: dict[str, list[dict[str, Any]]],
    evidence_type: str,
    *,
    shared: bool,
) -> list[str]:
    if shared:
        return []
    return _evidence_id_list((left.get(evidence_type, [])[:2] + right.get(evidence_type, [])[:2])[:4])


def _evidence_excerpt(evidence_by_id: dict[str, dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": eid,
            "type": str(item.get("evidence_type") or ""),
            "paper_id": str(item.get("paper_id") or ""),
            "label": str(item.get("normalized_label") or ""),
            "page": int(item.get("page") or 0),
            "quote": str(item.get("quote") or "")[:500],
        }
        for eid in ids
        if (item := evidence_by_id.get(eid))
    ]


def _verify_relation_candidate(
    row: dict[str, Any],
    grouped: dict[str, dict[str, list[dict[str, Any]]]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    next_row = dict(row)
    relation_type = str(row.get("relation_type") or "")
    source_paper_id = str(row.get("source_paper_id") or "")
    target_paper_id = str(row.get("target_paper_id") or "")
    source_ids = [str(eid) for eid in row.get("source_evidence_ids", []) if eid]
    target_ids = [str(eid) for eid in row.get("target_evidence_ids", []) if eid]
    positive = list(row.get("positive_checks") or [])
    negative = list(row.get("negative_checks") or [])
    counter_ids = list(row.get("counter_evidence_ids") or [])
    confidence = float(row.get("confidence") or 0.0)
    status = "unverified"
    comparability = _comparability_schema(relation_type=relation_type)

    if not source_ids or not target_ids:
        comparability = _comparability_schema(relation_type=relation_type, verdict="unverified")
        negative.append("verifier: missing source or target evidence")
        next_row.update(
            {
                "positive_checks": _unique(positive),
                "negative_checks": _unique(negative),
                "counter_evidence_ids": _unique(counter_ids),
                "comparability_json": comparability,
                "confidence": min(confidence, 0.45),
                "status": status,
                "verifier_version": VERIFIER_VERSION,
            }
        )
        return next_row

    positive.extend(
        [
            "verifier: source and target evidence are present",
            "verifier: source and target are distinct papers",
        ]
    )
    left = grouped[source_paper_id]
    right = grouped[target_paper_id]

    if relation_type == "uses_same_dataset":
        source_labels = {str(item.get("normalized_label") or "").lower() for item in _evidence_for_ids(evidence_by_id, source_ids, "dataset")}
        target_labels = {str(item.get("normalized_label") or "").lower() for item in _evidence_for_ids(evidence_by_id, target_ids, "dataset")}
        shared_dataset = bool(source_labels & target_labels)
        comparability = _comparability_schema(
            relation_type=relation_type,
            shared_dataset=shared_dataset,
            shared_setting=shared_dataset,
            verdict="verified" if shared_dataset else "needs_more_evidence",
        )
        if shared_dataset:
            positive.append("verifier: exact dataset label match")
            status = "verified"
            confidence = max(confidence, 0.88)
        else:
            negative.append("verifier: dataset labels diverge")
            counter_ids.extend(source_ids + target_ids)
            status = "needs_more_evidence"

    elif relation_type == "same_problem":
        shared_problem = bool(_shared_by_type(left, right, "problem", depth=3))
        comparability = _comparability_schema(
            relation_type=relation_type,
            shared_task=shared_problem,
            verdict="verified" if shared_problem else "needs_more_evidence",
        )
        if shared_problem:
            positive.append("verifier: shared problem taxonomy")
            status = "verified"
            confidence = max(confidence, 0.79)
        else:
            negative.append("verifier: problem evidence not aligned")
            counter_ids.extend(_setting_counter_ids(left, right, "problem", shared=False))
            status = "needs_more_evidence"

    elif relation_type == "method_variant":
        shared_method = bool(_shared_by_type(left, right, "method", depth=2))
        comparability = _comparability_schema(
            relation_type=relation_type,
            shared_setting=shared_method,
            verdict="verified" if shared_method else "needs_more_evidence",
        )
        if shared_method:
            positive.append("verifier: shared method family")
            status = "verified"
            confidence = max(confidence, 0.75)
        else:
            negative.append("verifier: method family not aligned")
            counter_ids.extend(_setting_counter_ids(left, right, "method", shared=False))
            status = "needs_more_evidence"

    elif relation_type == "transferable_method":
        comparability = _comparability_schema(
            relation_type=relation_type,
            shared_task=False,
            shared_setting=False,
            verdict="needs_more_evidence",
        )
        positive.append("verifier: relation is a transfer hypothesis, not direct evidence of feasibility")
        negative.append("verifier: transfer feasibility is not established")
        status = "needs_more_evidence"
        confidence = min(confidence, 0.68)

    elif relation_type == "conflicting_claim":
        shared_metric = bool(_same_label_pairs(left, right, "metric"))
        shared_problem = bool(_shared_by_type(left, right, "problem", depth=3))
        shared_dataset = bool(_same_label_pairs(left, right, "dataset"))
        shared_method = bool(_shared_by_type(left, right, "method", depth=2))
        selected_types = _selected_evidence_types(evidence_by_id, source_ids + target_ids)
        has_result_and_claim = "result" in selected_types and "claim" in selected_types
        claim_direction = "opposing" if has_result_and_claim else "unknown"
        comparability = _comparability_schema(
            relation_type=relation_type,
            shared_task=shared_problem,
            shared_dataset=shared_dataset,
            shared_metric=shared_metric,
            shared_setting=shared_method,
            claim_direction=claim_direction,
            verdict="verified" if shared_metric and shared_problem and shared_dataset and has_result_and_claim else "needs_more_evidence",
        )
        if shared_metric and shared_problem and has_result_and_claim:
            positive.extend(
                [
                    "verifier: same task/problem and metric evidence found",
                    "verifier: result and claim evidence have opposing polarity",
                ]
            )
            if shared_dataset:
                positive.append("verifier: shared dataset evidence found")
                negative.append("verifier: conflict requires LLM or manual confirmation")
                status = "needs_more_evidence"
                confidence = min(max(confidence, 0.84), 0.86)
            else:
                negative.append("verifier: conflict lacks same dataset support")
                counter_ids.extend(_setting_counter_ids(left, right, "dataset", shared=False))
                status = "needs_more_evidence"
            counter_ids.extend(_setting_counter_ids(left, right, "method", shared=shared_method))
            if not shared_method:
                negative.append("verifier: method setting not matched")
        else:
            negative.append("verifier: dataset setting not matched")
            counter_ids.extend(_setting_counter_ids(left, right, "dataset", shared=shared_dataset))
            status = "needs_more_evidence"

    else:
        status = _auto_relation_status(next_row)

    next_row.update(
        {
            "positive_checks": _unique(positive),
            "negative_checks": _unique(negative),
            "counter_evidence_ids": _unique(counter_ids),
            "comparability_json": comparability,
            "confidence": round(confidence, 3),
            "status": status,
            "verifier_version": VERIFIER_VERSION,
        }
    )
    return next_row


def _paper_title_by_id(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {str(row.get("paper_id") or ""): str(row.get("title") or row.get("paper_id") or "") for row in rows}


def _relation_llm_payload(relations: list[dict[str, Any]], rows: list[dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    title_by_id = _paper_title_by_id(rows)
    candidates: list[dict[str, Any]] = []
    priority = {"conflicting_claim": 0, "transferable_method": 1, "method_variant": 2, "same_problem": 3, "uses_same_dataset": 4}
    for row in sorted(relations, key=lambda item: (priority.get(str(item.get("relation_type") or ""), 9), -float(item.get("confidence") or 0)))[:limit]:
        source_ids = [str(eid) for eid in row.get("source_evidence_ids", []) if eid]
        target_ids = [str(eid) for eid in row.get("target_evidence_ids", []) if eid]
        candidates.append(
            {
                "relation_id": str(row.get("relation_id") or ""),
                "relation_type": str(row.get("relation_type") or ""),
                "source_paper": {
                    "paper_id": str(row.get("source_paper_id") or ""),
                    "title": title_by_id.get(str(row.get("source_paper_id") or ""), ""),
                },
                "target_paper": {
                    "paper_id": str(row.get("target_paper_id") or ""),
                    "title": title_by_id.get(str(row.get("target_paper_id") or ""), ""),
                },
                "source_evidence": _evidence_excerpt(evidence_by_id, source_ids),
                "target_evidence": _evidence_excerpt(evidence_by_id, target_ids),
                "rule_positive_checks": row.get("positive_checks") or [],
                "rule_negative_checks": row.get("negative_checks") or [],
            }
        )
    return candidates


def _json_object_from_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _llm_decision_by_relation(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    decisions = raw.get("relations")
    if not isinstance(decisions, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in decisions:
        if not isinstance(item, dict):
            continue
        relation_id = str(item.get("relation_id") or "")
        if not relation_id:
            continue
        status = str(item.get("status") or "").strip()
        if status not in {"verified", "needs_more_evidence", "rejected", "unverified"}:
            status = "needs_more_evidence"
        out[relation_id] = {
            "status": status,
            "confidence": float(item.get("confidence") or 0.0),
            "positive_checks": [str(value) for value in item.get("positive_checks", []) if isinstance(value, str)][:5],
            "negative_checks": [str(value) for value in item.get("negative_checks", []) if isinstance(value, str)][:5],
            "counter_evidence_ids": [str(value) for value in item.get("counter_evidence_ids", []) if isinstance(value, str)][:6],
        }
    return out


def _apply_llm_relation_decisions(relations: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not decisions:
        return relations
    out: list[dict[str, Any]] = []
    for row in relations:
        next_row = dict(row)
        decision = decisions.get(str(row.get("relation_id") or ""))
        if decision:
            status = str(decision.get("status") or row.get("status") or "needs_more_evidence")
            next_row["status"] = status
            next_row["confidence"] = round(max(float(row.get("confidence") or 0.0), min(1.0, float(decision.get("confidence") or 0.0))), 3)
            next_row["positive_checks"] = _unique(list(row.get("positive_checks") or []) + ["llm: relation accepted"] + list(decision.get("positive_checks") or []))
            llm_marker = ""
            if status == "needs_more_evidence":
                llm_marker = "llm: relation needs more evidence"
            elif status == "rejected":
                llm_marker = "llm: relation rejected"
            next_row["negative_checks"] = _unique(list(row.get("negative_checks") or []) + ([llm_marker] if llm_marker else []) + list(decision.get("negative_checks") or []))
            next_row["counter_evidence_ids"] = _unique(list(row.get("counter_evidence_ids") or []) + list(decision.get("counter_evidence_ids") or []))
            next_row["verifier_version"] = LLM_VERIFIER_VERSION
        out.append(next_row)
    return out


async def _maybe_llm_verify_relations(relations: list[dict[str, Any]], rows: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settings = get_settings()
    runtime = get_llm_runtime_config()
    if not relations or not settings.research_discovery_llm_verify_enabled or not runtime.base_url or not runtime.default_thinking_model:
        return relations
    evidence_by_id = {str(item.get("evidence_id") or ""): item for item in evidence}
    payload = _relation_llm_payload(
        relations,
        rows,
        evidence_by_id,
        max(1, int(settings.research_discovery_llm_verify_limit or 1)),
    )
    if not payload:
        return relations
    messages = [
        {
            "role": "system",
            "content": (
                "You verify cross-paper research relation candidates. "
                "Use only the provided evidence quotes. Return strict JSON: "
                "{\"relations\":[{\"relation_id\":\"...\",\"status\":\"verified|needs_more_evidence|rejected\","
                "\"confidence\":0.0,\"positive_checks\":[\"...\"],\"negative_checks\":[\"...\"],"
                "\"counter_evidence_ids\":[\"...\"]}]}. "
                "For conflicting_claim, mark verified only if task, metric, dataset/setting, and claim polarity are comparable."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"candidates": payload}, ensure_ascii=False),
        },
    ]
    try:
        raw = await get_llm_service().chat(
            messages,
            model=settings.research_discovery_llm_verify_model.strip(),
            temperature=0.0,
        )
        return _apply_llm_relation_decisions(relations, _llm_decision_by_relation(_json_object_from_text(raw)))
    except Exception as exc:
        logger.warning("LLM relation verification failed; using rule verifier results: %s", exc)
        return [
            {
                **row,
                "negative_checks": _unique(list(row.get("negative_checks") or []) + ["llm: verifier failed; kept rule verifier result"]),
            }
            for row in relations
        ]


def _relation_rows(rows: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _group_evidence(evidence)
    evidence_by_id = {str(item.get("evidence_id") or ""): item for item in evidence}
    relations: list[dict[str, Any]] = []
    for idx, left_row in enumerate(rows):
        left_id = str(left_row.get("paper_id") or "")
        for right_row in rows[idx + 1:]:
            right_id = str(right_row.get("paper_id") or "")
            left = grouped[left_id]
            right = grouped[right_id]
            candidates: list[tuple[str, str, list[tuple[dict[str, Any], dict[str, Any], str]], list[str], list[str], float]] = [
                ("uses_same_dataset", "rule_same_dataset_v1", _same_label_pairs(left, right, "dataset"), ["same normalized dataset"], ["no dataset match"], 0.88),
                ("same_problem", "rule_same_problem_v1", _shared_by_type(left, right, "problem", depth=3), ["same problem domain/task/setting"], ["different top-level task"], 0.76),
                ("method_variant", "rule_method_variant_v1", _shared_by_type(left, right, "method", depth=2), ["same method family", "different paper context"], ["exact same paper only"], 0.72),
            ]
            for relation_type, rule_id, pairs, positive, negative, base_conf in candidates:
                if not pairs:
                    continue
                source_evidence = [str(pair[0].get("evidence_id") or "") for pair in pairs[:3]]
                target_evidence = [str(pair[1].get("evidence_id") or "") for pair in pairs[:3]]
                relations.append(
                    {
                        "relation_id": _relation_id(relation_type, left_id, right_id, source_evidence, target_evidence),
                        "relation_type": relation_type,
                        "source_paper_id": left_id,
                        "target_paper_id": right_id,
                        "source_evidence_ids": source_evidence,
                        "target_evidence_ids": target_evidence,
                        "rule_id": rule_id,
                        "positive_checks": positive + [f"matched {pairs[0][2]}"],
                        "negative_checks": negative,
                        "counter_evidence_ids": [],
                        "confidence": min(0.96, base_conf + 0.03 * min(3, len(pairs))),
                    }
                )

            transferable_pairs: list[tuple[dict[str, Any], dict[str, Any], str]] = []
            for method in left.get("method", []):
                for problem in right.get("problem", []):
                    if method.get("paper_id") != problem.get("paper_id"):
                        transferable_pairs.append((method, problem, str(method.get("normalized_label") or "")))
            for method in right.get("method", []):
                for problem in left.get("problem", []):
                    if method.get("paper_id") != problem.get("paper_id"):
                        transferable_pairs.append((method, problem, str(method.get("normalized_label") or "")))
            if transferable_pairs:
                source_evidence = [str(pair[0].get("evidence_id") or "") for pair in transferable_pairs[:2]]
                target_evidence = [str(pair[1].get("evidence_id") or "") for pair in transferable_pairs[:2]]
                relations.append(
                    {
                        "relation_id": _relation_id("transferable_method", left_id, right_id, source_evidence, target_evidence),
                        "relation_type": "transferable_method",
                        "source_paper_id": left_id,
                        "target_paper_id": right_id,
                        "source_evidence_ids": source_evidence,
                        "target_evidence_ids": target_evidence,
                        "rule_id": "rule_transferable_method_v1",
                        "positive_checks": ["source method exists", "target problem exists", "requires manual feasibility review"],
                        "negative_checks": ["no same-task performance claim required", "not generated without source method and target problem"],
                        "counter_evidence_ids": [],
                        "confidence": 0.58,
                    }
                )

            conflict_pairs: list[tuple[dict[str, Any], dict[str, Any], str]] = []
            shared_metrics = _same_label_pairs(left, right, "metric")
            shared_problem = _shared_by_type(left, right, "problem", depth=3)
            if shared_metrics and shared_problem:
                left_negative = left.get("result", [])
                right_negative = right.get("result", [])
                if left_negative and right.get("claim"):
                    conflict_pairs.append((left_negative[0], right["claim"][0], "same metric/problem with negative result"))
                if right_negative and left.get("claim"):
                    conflict_pairs.append((right_negative[0], left["claim"][0], "same metric/problem with negative result"))
            if conflict_pairs:
                source_evidence = [str(pair[0].get("evidence_id") or "") for pair in conflict_pairs[:2]]
                target_evidence = [str(pair[1].get("evidence_id") or "") for pair in conflict_pairs[:2]]
                relations.append(
                    {
                        "relation_id": _relation_id("conflicting_claim", left_id, right_id, source_evidence, target_evidence),
                        "relation_type": "conflicting_claim",
                        "source_paper_id": left_id,
                        "target_paper_id": right_id,
                        "source_evidence_ids": source_evidence,
                        "target_evidence_ids": target_evidence,
                        "rule_id": "rule_conflicting_claim_v1",
                        "positive_checks": ["same task/problem", "same metric", "opposite result direction"],
                        "negative_checks": ["not emitted without shared task and metric"],
                        "counter_evidence_ids": [],
                        "confidence": 0.82,
                    }
                )
    return [_verify_relation_candidate(row, grouped, evidence_by_id) for row in relations]


async def _verified_card_paper_scope(card_id: str) -> list[str]:
    rows = await db.fetch_all(
        """
        SELECT DISTINCT kc.paper_id
          FROM knowledge_cards kc
          JOIN knowledge_cards source
            ON source.card_id = ?
         WHERE kc.status = 'verified'
           AND kc.asset_level = 'action'
           AND source.status = 'verified'
           AND source.asset_level = 'action'
           AND kc.paper_id != ''
           AND (
                (source.normalized_key != '' AND lower(kc.normalized_key) = lower(source.normalized_key))
             OR (source.card_type != '' AND lower(kc.card_type) = lower(source.card_type))
             OR (source.tags != '' AND lower(kc.tags) LIKE '%' || lower(source.tags) || '%')
             OR (kc.tags != '' AND lower(source.tags) LIKE '%' || lower(kc.tags) || '%')
           )
         LIMIT 80
        """,
        (card_id,),
    )
    return [str(row.get("paper_id") or "") for row in rows if row.get("paper_id")]


async def _upsert_relations(relations: list[dict[str, Any]]) -> None:
    if not relations:
        return
    params = [
        (
            row["relation_id"],
            row["relation_type"],
            row["source_paper_id"],
            row["target_paper_id"],
            _json(row["source_evidence_ids"]),
            _json(row["target_evidence_ids"]),
            row["rule_id"],
            _json(row["positive_checks"]),
            _json(row["negative_checks"]),
            _json(row["counter_evidence_ids"]),
            _json(row.get("comparability_json") or {}),
            row["confidence"],
            row.get("status") or _auto_relation_status(row),
            row.get("verifier_version") or VERIFIER_VERSION,
            DISCOVERY_VERSION,
        )
        for row in relations
    ]
    await db.execute_many(
        """
        INSERT INTO research_relation_edges (
            relation_id, relation_type, source_paper_id, target_paper_id,
            source_evidence_ids, target_evidence_ids, rule_id, positive_checks,
            negative_checks, counter_evidence_ids, comparability_json, confidence, status, verifier_version,
            relation_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(relation_id) DO UPDATE SET
            positive_checks = excluded.positive_checks,
            negative_checks = excluded.negative_checks,
            counter_evidence_ids = excluded.counter_evidence_ids,
            comparability_json = excluded.comparability_json,
            confidence = excluded.confidence,
            status = CASE
                WHEN research_relation_edges.status IN ('confirmed', 'rejected') THEN research_relation_edges.status
                ELSE excluded.status
            END,
            verifier_version = excluded.verifier_version,
            relation_version = excluded.relation_version,
            updated_at = datetime('now')
        WHERE research_relation_edges.status != 'rejected'
        """,
        params,
    )


def _auto_relation_status(row: dict[str, Any]) -> str:
    confidence = float(row.get("confidence") or 0.0)
    relation_type = str(row.get("relation_type") or "")
    positive = _loads_list(_json(row.get("positive_checks") or []))
    source_ids = row.get("source_evidence_ids") or []
    target_ids = row.get("target_evidence_ids") or []
    if relation_type == "conflicting_claim":
        return "needs_more_evidence"
    if confidence >= 0.82 and positive and source_ids and target_ids:
        return "verified"
    if confidence >= 0.6:
        return "needs_more_evidence"
    return "unverified"


async def _load_relations(paper_ids: list[str]) -> list[dict[str, Any]]:
    if not paper_ids:
        return []
    placeholders = ",".join("?" for _ in paper_ids)
    return await db.fetch_all(
        f"""
        SELECT *
         FROM research_relation_edges
         WHERE (source_paper_id IN ({placeholders})
            OR target_paper_id IN ({placeholders}))
           AND status != 'rejected'
         ORDER BY confidence DESC, updated_at DESC
        """,
        tuple(paper_ids + paper_ids),
    )


def _build_gap_rows(evidence: list[dict[str, Any]], relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    label_to_evidence: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in evidence:
        evidence_type = str(item.get("evidence_type") or "")
        label = str(item.get("normalized_label") or "")
        by_type[evidence_type].append(item)
        label_to_evidence[(evidence_type, label.lower())].append(item)

    counter_ids: set[str] = set()
    for item in by_type.get("result", []):
        counter_ids.add(str(item.get("evidence_id") or ""))
    gaps: list[dict[str, Any]] = []
    relation_counter = Counter(str(row.get("relation_type") or "") for row in relations)

    for limitation in by_type.get("limitation", [])[:20]:
        support_ids = [str(limitation.get("evidence_id") or "")]
        paper_id = str(limitation.get("paper_id") or "")
        related_problem = next((item for item in by_type.get("problem", []) if str(item.get("paper_id") or "") == paper_id), None)
        if related_problem:
            support_ids.append(str(related_problem.get("evidence_id") or ""))
        local_counter: list[str] = []
        if related_problem:
            problem_prefix = _taxonomy_prefix(str(related_problem.get("taxonomy_path") or ""), 3)
            related_paper_ids = {
                str(item.get("paper_id") or "")
                for item in by_type.get("problem", [])
                if _taxonomy_prefix(str(item.get("taxonomy_path") or ""), 3) == problem_prefix
            }
            local_counter = [
                str(item.get("evidence_id") or "")
                for item in by_type.get("claim", [])
                if str(item.get("paper_id") or "") in related_paper_ids
                and str(item.get("paper_id") or "") != paper_id
            ][:4]
        coverage_status = "partially_covered" if local_counter else "uncovered"
        title = f"Resolve limitation: {str(limitation.get('normalized_label') or 'open limitation')[:80]}"
        limitation_label = str(limitation.get("normalized_label") or "open limitation")
        target_task = str((related_problem or {}).get("normalized_label") or limitation_label)
        gaps.append(
            {
                "gap_id": _gap_id(title, support_ids),
                "title": title,
                "hypothesis": "A focused method or evaluation change can address an explicit limitation in the local corpus.",
                "description": str(limitation.get("quote") or ""),
                "support_evidence_ids": support_ids,
                "counter_evidence_ids": local_counter,
                "related_synthesis_card_ids": [],
                "related_card_ids": [],
                "research_question": f"How can we address {limitation_label} under the local corpus assumptions?",
                "target_task": target_task,
                "constraints_json": [str(limitation.get("quote") or "")[:240]],
                "baseline_plan": "Use the closest verified method/result cards on the same task as local baselines.",
                "contribution": "A focused method or evaluation change that resolves a documented limitation.",
                "target_venue": "",
                "history_json": [{"event": "generated_from_limitation", "paper_id": paper_id, "evidence_ids": support_ids}],
                "coverage_status": coverage_status,
                "novelty_score": 0.78 if coverage_status == "uncovered" else 0.58,
                "feasibility_score": 0.62,
                "evidence_strength": min(0.9, 0.45 + 0.16 * len(support_ids) + 0.05 * relation_counter["same_problem"]),
                "risk_score": 0.42 + 0.12 * len(local_counter),
                "experiment_cost": 0.48,
                "domain_value": 0.7,
                "status": "candidate" if not local_counter else "needs_more_evidence",
                "rejection_reason": "",
                "minimum_experiment": "Compare the proposed change against the closest local baseline on the same task, dataset, and metric.",
            }
        )

    for relation in relations:
        if str(relation.get("relation_type") or "") != "transferable_method":
            continue
        support_ids = _loads_list(str(relation.get("source_evidence_ids") or "[]")) + _loads_list(str(relation.get("target_evidence_ids") or "[]"))
        if not support_ids:
            continue
        title = "Evaluate method transfer across tasks"
        gaps.append(
            {
                "gap_id": _gap_id(title + str(relation.get("relation_id") or ""), support_ids),
                "title": title,
                "hypothesis": "A method used in one local paper may transfer to another local task if assumptions and failure modes hold.",
                "description": "Transferable-method relation generated only when source method evidence and target problem evidence both exist.",
                "support_evidence_ids": support_ids[:5],
                "counter_evidence_ids": [],
                "related_synthesis_card_ids": [],
                "related_card_ids": [],
                "research_question": "Which assumptions must hold for this method transfer to work on the target task?",
                "target_task": "cross-task transfer",
                "constraints_json": _loads_list(str(relation.get("negative_checks") or "[]")),
                "baseline_plan": "Compare against the target-paper baseline and the source method without transfer-specific changes.",
                "contribution": "A verified transfer recipe with failure-mode analysis across local tasks.",
                "target_venue": "",
                "history_json": [{"event": "generated_from_relation", "relation_id": str(relation.get("relation_id") or "")}],
                "coverage_status": "uncovered",
                "novelty_score": 0.66,
                "feasibility_score": 0.52,
                "evidence_strength": min(0.84, 0.38 + float(relation.get("confidence") or 0) * 0.45),
                "risk_score": 0.64,
                "experiment_cost": 0.66,
                "domain_value": 0.62,
                "status": "needs_more_evidence",
                "rejection_reason": "",
                "minimum_experiment": "Run a small transfer pilot and record which source-task assumptions break on the target task.",
            }
        )

    if not gaps and evidence:
        support = evidence[: min(4, len(evidence))]
        evidence_ids = [str(item.get("evidence_id") or "") for item in support]
        coverage_status = "insufficient_corpus" if len({item.get("paper_id") for item in evidence}) < 3 else "unknown"
        gaps.append(
            {
                "gap_id": _gap_id("Corpus evidence audit", evidence_ids),
                "title": "Corpus evidence audit",
                "hypothesis": "The current local corpus may be too small for reliable innovation claims.",
                "description": "Collect more papers or verify extracted evidence before promoting a gap to an idea.",
                "support_evidence_ids": evidence_ids,
                "counter_evidence_ids": list(counter_ids)[:4],
                "related_synthesis_card_ids": [],
                "related_card_ids": [],
                "research_question": "What evidence is still missing before this corpus can support a research claim?",
                "target_task": "corpus audit",
                "constraints_json": ["insufficient verified local evidence"],
                "baseline_plan": "Add or verify at least three papers and rebuild discovery before planning experiments.",
                "contribution": "A cleaner evidence base before idea promotion.",
                "target_venue": "",
                "history_json": [{"event": "generated_from_corpus_audit", "evidence_ids": evidence_ids}],
                "coverage_status": coverage_status,
                "novelty_score": 0.35,
                "feasibility_score": 0.7,
                "evidence_strength": 0.32,
                "risk_score": 0.72,
                "experiment_cost": 0.2,
                "domain_value": 0.45,
                "status": "needs_more_evidence",
                "rejection_reason": "",
                "minimum_experiment": "Add or verify at least three papers for the target theme, then regenerate relations and gaps.",
            }
        )
    return gaps[:24]


async def _upsert_gaps(gaps: list[dict[str, Any]]) -> None:
    if not gaps:
        return
    params = [
        (
            row["gap_id"],
            row["title"],
            row["hypothesis"],
            row["description"],
            _json(row["support_evidence_ids"]),
            _json(row["counter_evidence_ids"]),
            _json(row.get("related_synthesis_card_ids") or []),
            _json(row.get("related_card_ids") or []),
            row.get("research_question") or row["hypothesis"],
            row.get("target_task") or "",
            _json(row.get("constraints_json") or []),
            row.get("baseline_plan") or "",
            row.get("contribution") or "",
            row.get("target_venue") or "",
            _json(row.get("history_json") or []),
            row["coverage_status"],
            row["novelty_score"],
            row["feasibility_score"],
            row["evidence_strength"],
            row["risk_score"],
            row["experiment_cost"],
            row["domain_value"],
            row["status"],
            row["rejection_reason"],
            row["minimum_experiment"],
            DISCOVERY_VERSION,
        )
        for row in gaps
    ]
    await db.execute_many(
        """
        INSERT INTO research_gaps (
            gap_id, title, hypothesis, description, support_evidence_ids,
            counter_evidence_ids, related_synthesis_card_ids, related_card_ids,
            research_question, target_task, constraints_json, baseline_plan,
            contribution, target_venue, history_json, coverage_status,
            novelty_score, feasibility_score, evidence_strength, risk_score,
            experiment_cost, domain_value, status, rejection_reason,
            minimum_experiment, gap_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(gap_id) DO UPDATE SET
            hypothesis = excluded.hypothesis,
            description = excluded.description,
            support_evidence_ids = excluded.support_evidence_ids,
            counter_evidence_ids = excluded.counter_evidence_ids,
            related_synthesis_card_ids = excluded.related_synthesis_card_ids,
            related_card_ids = excluded.related_card_ids,
            research_question = CASE
                WHEN research_gaps.research_question != '' THEN research_gaps.research_question
                ELSE excluded.research_question
            END,
            target_task = CASE
                WHEN research_gaps.target_task != '' THEN research_gaps.target_task
                ELSE excluded.target_task
            END,
            constraints_json = excluded.constraints_json,
            baseline_plan = CASE
                WHEN research_gaps.baseline_plan != '' THEN research_gaps.baseline_plan
                ELSE excluded.baseline_plan
            END,
            contribution = CASE
                WHEN research_gaps.contribution != '' THEN research_gaps.contribution
                ELSE excluded.contribution
            END,
            target_venue = CASE
                WHEN research_gaps.target_venue != '' THEN research_gaps.target_venue
                ELSE excluded.target_venue
            END,
            history_json = CASE
                WHEN research_gaps.history_json != '[]' THEN research_gaps.history_json
                ELSE excluded.history_json
            END,
            coverage_status = excluded.coverage_status,
            novelty_score = excluded.novelty_score,
            feasibility_score = excluded.feasibility_score,
            evidence_strength = excluded.evidence_strength,
            risk_score = excluded.risk_score,
            experiment_cost = excluded.experiment_cost,
            domain_value = excluded.domain_value,
            gap_version = excluded.gap_version,
            updated_at = datetime('now')
        WHERE research_gaps.status NOT IN ('rejected', 'covered', 'pursue', 'experiment_planned', 'promoted_to_idea')
        """,
        params,
    )


async def _load_gaps() -> list[dict[str, Any]]:
    return await db.fetch_all(
        """
        SELECT *
          FROM research_gaps
         WHERE status != 'rejected'
         ORDER BY evidence_strength DESC, novelty_score DESC, updated_at DESC
         LIMIT 24
        """
    )


def _evidence_response(row: dict[str, Any]) -> DiscoveryEvidenceResponse:
    return DiscoveryEvidenceResponse(
        evidence_id=str(row.get("evidence_id") or ""),
        evidence_type=str(row.get("evidence_type") or ""),
        paper_id=str(row.get("paper_id") or ""),
        block_id=int(row.get("block_id") or 0),
        page=int(row.get("page") or 0),
        quote=str(row.get("quote") or ""),
        normalized_label=str(row.get("normalized_label") or ""),
        taxonomy_path=str(row.get("taxonomy_path") or ""),
        confidence=float(row.get("confidence") or 0.0),
        extractor=str(row.get("extractor") or ""),
        model_version=str(row.get("model_version") or ""),
        prompt_version=str(row.get("prompt_version") or ""),
        status=str(row.get("status") or ""),
        revision_history=_loads_any_list(str(row.get("revision_history") or "[]")),
        evidence_version=int(row.get("evidence_version") or 1),
    )


def _themes_from_evidence(evidence: list[dict[str, Any]]) -> list[DiscoveryThemeResponse]:
    themes: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if str(item.get("evidence_type") or "") not in {"problem", "method", "dataset", "metric"}:
            continue
        path = str(item.get("taxonomy_path") or "")
        if not path:
            path = f"{item.get('evidence_type')}/{str(item.get('normalized_label') or '').lower()}"
        theme_id = _hash(["theme", _taxonomy_prefix(path, 3) or path])[:10]
        entry = themes.setdefault(
            theme_id,
            {
                "name": str(item.get("normalized_label") or _title_case_label(path.split("/")[-1])),
                "paper_ids": set(),
                "keywords": Counter(),
                "taxonomy_path": _taxonomy_prefix(path, 4) or path,
            },
        )
        entry["paper_ids"].add(str(item.get("paper_id") or ""))
        for token in _tokens(f"{item.get('normalized_label') or ''} {item.get('taxonomy_path') or ''}"):
            entry["keywords"].update([token])
    out = [
        DiscoveryThemeResponse(
            theme_id=theme_id,
            name=entry["name"],
            paper_count=len(entry["paper_ids"]),
            keywords=[word for word, _ in entry["keywords"].most_common(6)],
            paper_ids=sorted(entry["paper_ids"]),
            taxonomy_path=entry["taxonomy_path"],
        )
        for theme_id, entry in themes.items()
    ]
    out.sort(key=lambda theme: (-theme.paper_count, theme.name))
    return out


def _nodes_from_rows(rows: list[dict[str, Any]], evidence: list[dict[str, Any]], themes: list[DiscoveryThemeResponse]) -> list[DiscoveryNodeResponse]:
    paper_to_themes: dict[str, list[str]] = defaultdict(list)
    for theme in themes:
        for paper_id in theme.paper_ids:
            paper_to_themes[paper_id].append(theme.theme_id)
    evidence_count = Counter(str(item.get("paper_id") or "") for item in evidence)
    return [
        DiscoveryNodeResponse(
            paper_id=str(row.get("paper_id") or ""),
            title=str(row.get("title") or row.get("paper_id") or ""),
            year=int(row.get("year") or 0),
            venue=str(row.get("venue") or ""),
            theme_ids=paper_to_themes.get(str(row.get("paper_id") or ""), []),
            status=str(row.get("latest_run_status") or row.get("parse_status") or ""),
            evidence_count=evidence_count[str(row.get("paper_id") or "")],
        )
        for row in rows
    ]


def _edges_response(relations: list[dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]]) -> list[DiscoveryEdgeResponse]:
    out: list[DiscoveryEdgeResponse] = []
    for row in relations[:60]:
        source_ids = _loads_list(str(row.get("source_evidence_ids") or "[]"))
        target_ids = _loads_list(str(row.get("target_evidence_ids") or "[]"))
        evidence_ids = source_ids + target_ids
        evidence_labels = [
            str(evidence_by_id[eid].get("normalized_label") or "")
            for eid in evidence_ids
            if eid in evidence_by_id
        ][:6]
        out.append(
            DiscoveryEdgeResponse(
                source=str(row.get("source_paper_id") or ""),
                target=str(row.get("target_paper_id") or ""),
                weight=round(float(row.get("confidence") or 0.0), 3),
                relation=str(row.get("relation_type") or ""),
                evidence=evidence_labels,
                relation_id=str(row.get("relation_id") or ""),
                source_evidence_ids=source_ids,
                target_evidence_ids=target_ids,
                rule_id=str(row.get("rule_id") or ""),
                positive_checks=_loads_list(str(row.get("positive_checks") or "[]")),
                negative_checks=_loads_list(str(row.get("negative_checks") or "[]")),
                counter_evidence_ids=_loads_list(str(row.get("counter_evidence_ids") or "[]")),
                comparability_json=_loads_dict(str(row.get("comparability_json") or "{}")),
                confidence=float(row.get("confidence") or 0.0),
                status=str(row.get("status") or ""),
                verifier_version=str(row.get("verifier_version") or ""),
                relation_version=int(row.get("relation_version") or 1),
            )
        )
    return out


def _gap_response(row: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> DiscoveryGapResponse:
    support_ids = _loads_list(str(row.get("support_evidence_ids") or "[]"))
    counter_ids = _loads_list(str(row.get("counter_evidence_ids") or "[]"))
    paper_ids = sorted({
        str(evidence_by_id[eid].get("paper_id") or "")
        for eid in support_ids + counter_ids
        if eid in evidence_by_id
    })
    signals = [
        str(evidence_by_id[eid].get("normalized_label") or "")
        for eid in support_ids
        if eid in evidence_by_id
    ][:5]
    scores = DiscoveryScoreResponse(
        novelty=float(row.get("novelty_score") or 0.0),
        feasibility=float(row.get("feasibility_score") or 0.0),
        evidence_strength=float(row.get("evidence_strength") or 0.0),
        risk=float(row.get("risk_score") or 0.0),
        experiment_cost=float(row.get("experiment_cost") or 0.0),
        domain_value=float(row.get("domain_value") or 0.0),
    )
    full_description = _full_gap_description(str(row.get("description") or ""), support_ids, evidence_by_id)
    return DiscoveryGapResponse(
        gap_id=str(row.get("gap_id") or ""),
        title=str(row.get("title") or ""),
        description=str(row.get("description") or ""),
        full_description=full_description,
        score=round((scores.novelty + scores.feasibility + scores.evidence_strength + scores.domain_value - scores.risk - scores.experiment_cost * 0.4) / 4, 3),
        paper_ids=paper_ids,
        signals=signals,
        question=str(row.get("hypothesis") or ""),
        hypothesis=str(row.get("hypothesis") or ""),
        support_evidence_ids=support_ids,
        counter_evidence_ids=counter_ids,
        related_synthesis_card_ids=_loads_list(str(row.get("related_synthesis_card_ids") or "[]")),
        related_card_ids=_loads_list(str(row.get("related_card_ids") or "[]")),
        research_question=str(row.get("research_question") or row.get("hypothesis") or ""),
        target_task=str(row.get("target_task") or ""),
        constraints_json=_loads_list(str(row.get("constraints_json") or "[]")),
        baseline_plan=str(row.get("baseline_plan") or ""),
        contribution=str(row.get("contribution") or ""),
        target_venue=str(row.get("target_venue") or ""),
        history_json=_loads_any_list(str(row.get("history_json") or "[]")),
        coverage_status=str(row.get("coverage_status") or ""),
        scores=scores,
        status=str(row.get("status") or ""),
        rejection_reason=str(row.get("rejection_reason") or ""),
        minimum_experiment=str(row.get("minimum_experiment") or ""),
        hit_by_paper_ids=_loads_list(str(row.get("hit_by_paper_ids") or "[]")),
        gap_version=int(row.get("gap_version") or 1),
    )


def _full_gap_description(description: str, support_ids: list[str], evidence_by_id: dict[str, dict[str, Any]]) -> str:
    candidates: list[str] = []
    ordered_ids = sorted(
        support_ids,
        key=lambda eid: 0 if str(evidence_by_id.get(eid, {}).get("evidence_type") or "") == "limitation" else 1,
    )
    for evidence_id in ordered_ids:
        evidence = evidence_by_id.get(evidence_id)
        if not evidence:
            continue
        full_text = _normalize(str(evidence.get("full_block_text") or ""))
        quote = _normalize(str(evidence.get("quote") or ""))
        text = full_text or quote
        if text and text not in candidates:
            candidates.append(text)
    if not candidates:
        return description
    return candidates[0]


def _reading_paths(themes: list[DiscoveryThemeResponse], rows: list[dict[str, Any]]) -> list[DiscoveryReadingPathResponse]:
    row_by_id = {str(row.get("paper_id") or ""): row for row in rows}
    paths: list[DiscoveryReadingPathResponse] = []
    for theme in themes[:4]:
        paper_ids = sorted(
            theme.paper_ids,
            key=lambda pid: (
                -int(row_by_id.get(pid, {}).get("year") or 0),
                str(row_by_id.get(pid, {}).get("title") or ""),
            ),
        )[:6]
        paths.append(
            DiscoveryReadingPathResponse(
                path_id=theme.theme_id,
                title=theme.name,
                description="Review evidence objects first, then compare relation checks and gap counter-evidence.",
                paper_ids=paper_ids,
            )
        )
    return paths


def _format_year_range(years: list[int]) -> str:
    clean = [year for year in years if year > 0]
    if not clean:
        return ""
    lo, hi = min(clean), max(clean)
    return str(lo) if lo == hi else f"{lo}-{hi}"


def _display_source(text: str) -> str:
    clean = str(text or "").strip()
    if not clean:
        return ""
    if clean.lower().startswith("resolve limitation:"):
        tail = _display_source(clean.split(":", 1)[1].strip())
        return f"解决局限：{tail}" if tail else "解决局限"
    mapped = _DISPLAY_LABELS.get(clean) or _DISPLAY_LABELS.get(clean.lower())
    if mapped:
        return mapped
    if clean.lower().startswith("matched "):
        matched = _display_source(clean[8:].strip())
        return f"匹配：{matched}" if matched else "存在匹配证据"
    if "/" in clean and not re.search(r"\s", clean):
        return _title_case_label(clean.split("/")[-1])
    return clean


def _should_translate_display(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in clean):
        return False
    if len(clean) <= 4 and clean.upper() == clean:
        return False
    return any(ch.isalpha() for ch in clean)


async def _translate_display(text: str) -> str:
    source = _display_source(text)
    if not _should_translate_display(source):
        return source
    return (await translate_text(source)).translated_text


async def _translate_display_list(values: list[str], *, limit: int | None = None) -> list[str]:
    out: list[str] = []
    for idx, value in enumerate(values):
        out.append(await _translate_display(value) if limit is None or idx < limit else value)
    return out


async def _localize_discovery_response(response: PapersDiscoveryResponse) -> PapersDiscoveryResponse:
    for theme in response.themes[:8]:
        theme.name = await _translate_display(theme.name)
    for edge in response.edges[:10]:
        edge.relation = await _translate_display(edge.relation)
        edge.evidence = await _translate_display_list(edge.evidence)
        edge.positive_checks = await _translate_display_list(edge.positive_checks)
        edge.negative_checks = await _translate_display_list(edge.negative_checks, limit=3)
    for gap in response.gaps[:6]:
        gap.title = await _translate_display(gap.title)
        gap.description = await _translate_display(gap.description)
        if gap.full_description == gap.description:
            gap.full_description = gap.description
        gap.question = await _translate_display(gap.question)
        gap.hypothesis = await _translate_display(gap.hypothesis)
        gap.research_question = await _translate_display(gap.research_question)
        gap.target_task = await _translate_display(gap.target_task)
        gap.baseline_plan = await _translate_display(gap.baseline_plan)
        gap.contribution = await _translate_display(gap.contribution)
        gap.rejection_reason = await _translate_display(gap.rejection_reason)
        gap.minimum_experiment = await _translate_display(gap.minimum_experiment)
        gap.signals = await _translate_display_list(gap.signals)
    for path in response.reading_paths[:4]:
        path.title = await _translate_display(path.title)
        path.description = await _translate_display(path.description)
    return response


async def _build_discovery_for_rows(rows: list[dict[str, Any]], *, clear_auto: bool) -> PapersDiscoveryResponse:
    paper_ids = [str(row.get("paper_id") or "") for row in rows if row.get("paper_id")]
    blocks = await _load_blocks(paper_ids)
    title_by_id = {str(row.get("paper_id") or ""): str(row.get("title") or "") for row in rows}
    drafts: list[EvidenceDraft] = []
    for row in rows:
        drafts.extend(_fallback_title_drafts(row))
    for block in blocks:
        drafts.extend(_drafts_from_block(block, title_by_id.get(str(block.get("paper_id") or ""), "")))
    drafts = _compact_drafts(drafts)
    if clear_auto:
        await _clear_auto_discovery(paper_ids)
    else:
        await _clear_auto_relations_for_scope(paper_ids)
    await _upsert_evidence(drafts)

    evidence = await _load_evidence(paper_ids)
    relations = _relation_rows(rows, evidence)
    relations = await _maybe_llm_verify_relations(relations, rows, evidence)
    await _upsert_relations(relations)
    stored_relations = await _load_relations(paper_ids)
    gaps = _build_gap_rows(evidence, stored_relations)
    await _upsert_gaps(gaps)
    await knowledge_synthesis.rebuild_synthesis_cards(limit=500)
    stored_gaps = await _load_gaps()

    evidence_by_id = {str(item.get("evidence_id") or ""): item for item in evidence}
    themes = _themes_from_evidence(evidence)
    years = [int(row.get("year") or 0) for row in rows]
    stats = DiscoveryStatsResponse(
        total_papers=len(rows),
        parsed_papers=sum(1 for row in rows if str(row.get("parse_status") or "") == "done"),
        analyzed_papers=sum(1 for row in rows if str(row.get("latest_run_status") or "") == "done"),
        synced_papers=sum(1 for row in rows if str(row.get("dify_status") or "") == "synced"),
        year_range=_format_year_range(years),
        evidence_items=len(evidence),
        relation_edges=len(stored_relations),
        gap_candidates=len(stored_gaps),
        discovery_version=DISCOVERY_VERSION,
    )
    response = PapersDiscoveryResponse(
        stats=stats,
        themes=themes,
        nodes=_nodes_from_rows(rows, evidence, themes),
        edges=_edges_response(stored_relations, evidence_by_id),
        gaps=[_gap_response(row, evidence_by_id) for row in stored_gaps],
        reading_paths=_reading_paths(themes, rows),
        evidence=[_evidence_response(item) for item in evidence[:200]],
    )
    return await _localize_discovery_response(response)


async def build_research_discovery(limit: int = 200) -> PapersDiscoveryResponse:
    return await _build_discovery_for_rows(await _load_rows(limit), clear_auto=True)


async def update_gap_status(gap_id: str, data: dict[str, Any]) -> None:
    row = await db.fetch_one("SELECT * FROM research_gaps WHERE gap_id = ?", (gap_id,))
    if not row:
        raise ValueError("Gap not found")
    status = str(data.get("status") or row.get("status") or "candidate").strip()
    allowed = {
        "candidate",
        "reviewing",
        "pursue",
        "experiment_planned",
        "rejected",
        "covered",
        "needs_more_evidence",
        "promoted_to_idea",
        "kept",
    }
    if status not in allowed:
        raise ValueError(f"Invalid gap status: {status}")
    if status == "kept":
        status = "reviewing"
    history = _append_history(
        row.get("history_json"),
        {
            "event": "status_changed",
            "from": str(row.get("status") or ""),
            "to": status,
            "reason": str(data.get("rejection_reason") or data.get("reason") or ""),
        },
    )
    await db.execute(
        """
        UPDATE research_gaps
           SET status = ?,
               rejection_reason = ?,
               research_question = COALESCE(NULLIF(?, ''), research_question),
               target_task = COALESCE(NULLIF(?, ''), target_task),
               constraints_json = COALESCE(NULLIF(?, '[]'), constraints_json),
               baseline_plan = COALESCE(NULLIF(?, ''), baseline_plan),
               contribution = COALESCE(NULLIF(?, ''), contribution),
               target_venue = COALESCE(NULLIF(?, ''), target_venue),
               minimum_experiment = COALESCE(NULLIF(?, ''), minimum_experiment),
               history_json = ?,
               updated_at = datetime('now')
         WHERE gap_id = ?
        """,
        (
            status,
            str(data.get("rejection_reason") or ""),
            str(data.get("research_question") or ""),
            str(data.get("target_task") or ""),
            _json(data.get("constraints_json") or []),
            str(data.get("baseline_plan") or ""),
            str(data.get("contribution") or ""),
            str(data.get("target_venue") or ""),
            str(data.get("minimum_experiment") or ""),
            history,
            gap_id,
        ),
    )
    try:
        from app.services import knowledge_assets

        await knowledge_assets.record_asset_event(
            "gap_status_changed",
            "gap",
            gap_id,
            source="synthesis",
            detail={"from": str(row.get("status") or ""), "to": status},
        )
    except Exception as exc:
        logger.warning("Failed to record gap status event for %s: %s", gap_id, exc)


async def rebuild_discovery_for_card(card_id: str) -> dict[str, int]:
    card = await db.fetch_one(
        """
        SELECT card_id, paper_id, status, asset_level
          FROM knowledge_cards
         WHERE card_id = ?
        """,
        (card_id,),
    )
    if not card or str(card.get("status") or "") != "verified" or str(card.get("asset_level") or "") != "action":
        return {"papers": 0, "relations": 0, "gaps": 0}
    source_paper_id = str(card.get("paper_id") or "")
    paper_ids = _unique([source_paper_id] + await _verified_card_paper_scope(card_id))
    if len(paper_ids) < 2:
        return {"papers": len(paper_ids), "relations": 0, "gaps": 0}
    response = await _build_discovery_for_rows(await _load_rows_for_papers(paper_ids), clear_auto=False)
    return {
        "papers": response.stats.total_papers,
        "relations": response.stats.relation_edges,
        "gaps": response.stats.gap_candidates,
    }
