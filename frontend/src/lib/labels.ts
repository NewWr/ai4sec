export type LabelLocale = "zh" | "en";

export type LabelGroup =
  | "cardType"
  | "cardStatus"
  | "assetLevel"
  | "createdBy"
  | "sectionHint"
  | "traceMode"
  | "syncStatus"
  | "runStatus"
  | "paperParseStatus"
  | "paperReadingStatus"
  | "paperPriority"
  | "readingDecision"
  | "annotationType"
  | "reviewStatus"
  | "documentPart"
  | "discoveryRelation"
  | "discoveryRelationStatus"
  | "gapStatus"
  | "coverageStatus"
  | "scoreName"
  | "sourceType"
  | "itemKind"
  | "difyDocumentStatus"
  | "readingMode";

type LabelEntry = Record<LabelLocale, string>;

const LABELS: Record<LabelGroup, Record<string, LabelEntry>> = {
  cardType: {
    claim: { zh: "论点", en: "Claim" },
    method: { zh: "方法", en: "Method" },
    dataset: { zh: "数据集", en: "Dataset" },
    metric: { zh: "指标", en: "Metric" },
    result: { zh: "结果", en: "Result" },
    limitation: { zh: "局限", en: "Limitation" },
    question: { zh: "问题", en: "Question" },
    idea: { zh: "想法", en: "Idea" },
  },
  cardStatus: {
    draft: { zh: "草稿", en: "Draft" },
    verified: { zh: "已确认", en: "Verified" },
    rejected: { zh: "已废弃", en: "Rejected" },
    merged: { zh: "已合并", en: "Merged" },
  },
  assetLevel: {
    action: { zh: "行动卡", en: "Action" },
    synthesis: { zh: "综合卡", en: "Synthesis" },
    evidence: { zh: "证据卡", en: "Evidence" },
  },
  createdBy: {
    ai: { zh: "AI 生成", en: "AI" },
    user: { zh: "用户创建", en: "User" },
  },
  sectionHint: {
    related_work: { zh: "相关工作", en: "Related work" },
    method: { zh: "方法", en: "Method" },
    experiment: { zh: "实验", en: "Experiment" },
    limitation: { zh: "局限", en: "Limitation" },
  },
  traceMode: {
    traceable: { zh: "带证据追踪", en: "Traceable" },
    clean: { zh: "纯净文本", en: "Clean" },
  },
  syncStatus: {
    not_synced: { zh: "未同步", en: "Not synced" },
    pending: { zh: "等待同步", en: "Pending" },
    running: { zh: "同步中", en: "Syncing" },
    synced: { zh: "已同步", en: "Synced" },
    skipped: { zh: "已跳过", en: "Skipped" },
    failed: { zh: "同步失败", en: "Failed" },
  },
  runStatus: {
    started: { zh: "已开始", en: "Started" },
    pending: { zh: "等待中", en: "Pending" },
    running: { zh: "分析中", en: "Running" },
    done: { zh: "已完成", en: "Done" },
    completed: { zh: "已完成", en: "Completed" },
    complete: { zh: "已完成", en: "Complete" },
    failed: { zh: "失败", en: "Failed" },
    canceled: { zh: "已取消", en: "Canceled" },
    cancelled: { zh: "已取消", en: "Cancelled" },
  },
  paperParseStatus: {
    unparsed: { zh: "未解析", en: "Unparsed" },
    pending: { zh: "等待解析", en: "Pending" },
    running: { zh: "解析中", en: "Parsing" },
    parsed: { zh: "已解析", en: "Parsed" },
    done: { zh: "已完成", en: "Done" },
    failed: { zh: "解析失败", en: "Failed" },
  },
  paperReadingStatus: {
    unread: { zh: "未读", en: "Unread" },
    skimmed: { zh: "已略读", en: "Skimmed" },
    reading: { zh: "阅读中", en: "Reading" },
    read: { zh: "已读", en: "Read" },
    archived: { zh: "已归档", en: "Archived" },
  },
  paperPriority: {
    high: { zh: "高优先级", en: "High" },
    medium: { zh: "中优先级", en: "Medium" },
    low: { zh: "低优先级", en: "Low" },
  },
  readingDecision: {
    must_read: { zh: "必须精读", en: "Must read" },
    useful: { zh: "有用", en: "Useful" },
    background: { zh: "背景材料", en: "Background" },
    discard: { zh: "忽略", en: "Discard" },
  },
  annotationType: {
    highlight: { zh: "高亮", en: "Highlight" },
    note: { zh: "笔记", en: "Note" },
    question: { zh: "问题", en: "Question" },
    correction: { zh: "纠错", en: "Correction" },
  },
  reviewStatus: {
    trusted: { zh: "可信", en: "Trusted" },
    pending: { zh: "待核验", en: "Pending" },
    error: { zh: "错误", en: "Error" },
    valuable: { zh: "有价值", en: "Valuable" },
  },
  documentPart: {
    main: { zh: "正文", en: "Main" },
    references: { zh: "参考文献", en: "References" },
    appendix: { zh: "附录", en: "Appendix" },
    supplementary: { zh: "补充材料", en: "Supplementary" },
    References: { zh: "参考文献", en: "References" },
    Appendix: { zh: "附录", en: "Appendix" },
    Supplementary: { zh: "补充材料", en: "Supplementary" },
  },
  discoveryRelation: {
    related: { zh: "相关", en: "Related" },
    same_problem: { zh: "同一问题", en: "Same problem" },
    same_dataset: { zh: "同一数据集", en: "Same dataset" },
    same_method: { zh: "同一方法", en: "Same method" },
    extends: { zh: "扩展", en: "Extends" },
    improves: { zh: "改进", en: "Improves" },
    uses: { zh: "使用", en: "Uses" },
    contrasts: { zh: "对比", en: "Contrasts" },
    conflicting_claim: { zh: "论点冲突", en: "Conflicting claim" },
  },
  discoveryRelationStatus: {
    confirmed: { zh: "已确认", en: "Confirmed" },
    verified: { zh: "已验证", en: "Verified" },
    needs_more_evidence: { zh: "需要更多证据", en: "Needs more evidence" },
    rejected: { zh: "已忽略", en: "Rejected" },
    unverified: { zh: "未验证", en: "Unverified" },
  },
  gapStatus: {
    kept: { zh: "保留", en: "Kept" },
    candidate: { zh: "候选", en: "Candidate" },
    reviewing: { zh: "复核中", en: "Reviewing" },
    pursue: { zh: "追踪", en: "Pursue" },
    experiment_planned: { zh: "已规划实验", en: "Experiment planned" },
    needs_more_evidence: { zh: "需要更多证据", en: "Needs more evidence" },
    promoted_to_idea: { zh: "已推进为想法", en: "Promoted to idea" },
    covered: { zh: "已覆盖", en: "Covered" },
    rejected: { zh: "已忽略", en: "Rejected" },
  },
  coverageStatus: {
    uncovered: { zh: "未覆盖", en: "Uncovered" },
    partially_covered: { zh: "部分覆盖", en: "Partially covered" },
    covered: { zh: "已覆盖", en: "Covered" },
    unknown: { zh: "未知", en: "Unknown" },
  },
  scoreName: {
    novelty: { zh: "新颖性", en: "Novelty" },
    feasibility: { zh: "可行性", en: "Feasibility" },
    evidence_strength: { zh: "证据强度", en: "Evidence strength" },
    evidence: { zh: "证据强度", en: "Evidence" },
    risk: { zh: "风险", en: "Risk" },
    experiment_cost: { zh: "实验成本", en: "Experiment cost" },
    domain_value: { zh: "领域价值", en: "Domain value" },
  },
  sourceType: {
    dify: { zh: "Dify 文档", en: "Dify" },
    knowledge_graph: { zh: "知识图谱", en: "Knowledge graph" },
    paper: { zh: "论文原文", en: "Paper" },
    papers: { zh: "论文", en: "Papers" },
    fragment: { zh: "原文片段", en: "Fragment" },
    run: { zh: "解读报告", en: "Analysis report" },
    card: { zh: "知识卡片", en: "Knowledge card" },
    cards: { zh: "知识卡片", en: "Knowledge cards" },
    relation: { zh: "关系", en: "Relation" },
    relations: { zh: "关系", en: "Relations" },
    snippet: { zh: "写作片段", en: "Writing snippet" },
    writing: { zh: "写作素材", en: "Writing" },
    dify_document: { zh: "Dify 文档", en: "Dify document" },
    local_graph: { zh: "本地图谱", en: "Local graph" },
    unknown: { zh: "未知", en: "Unknown" },
  },
  itemKind: {
    paper: { zh: "论文原文", en: "Paper" },
    run: { zh: "解读报告", en: "Analysis report" },
    card: { zh: "知识卡片", en: "Knowledge card" },
    snippet: { zh: "写作片段", en: "Writing snippet" },
    dify_document: { zh: "Dify 文档", en: "Dify document" },
  },
  difyDocumentStatus: {
    indexing: { zh: "索引中", en: "Indexing" },
    waiting: { zh: "等待索引", en: "Waiting" },
    paused: { zh: "已暂停", en: "Paused" },
    completed: { zh: "已完成", en: "Completed" },
    available: { zh: "可用", en: "Available" },
    enabled: { zh: "已启用", en: "Enabled" },
    disabled: { zh: "已停用", en: "Disabled" },
    error: { zh: "错误", en: "Error" },
    failed: { zh: "失败", en: "Failed" },
    unknown: { zh: "未知", en: "Unknown" },
  },
  readingMode: {
    snap: { zh: "快速洞察", en: "Insight Snap" },
    lens: { zh: "逻辑透镜", en: "Logic Lens" },
    sphere: { zh: "研究全景", en: "Research Sphere" },
    auto: { zh: "智能问答", en: "Smart Q&A" },
  },
};

const warned = new Set<string>();

export function labelFor(group: LabelGroup, value: string | null | undefined, locale: LabelLocale = "zh"): string {
  if (value == null || value === "") return "";
  const label = LABELS[group]?.[value]?.[locale];
  if (label) return label;
  if (process.env.NODE_ENV === "development") {
    const key = `${group}:${value}`;
    if (!warned.has(key)) {
      warned.add(key);
      console.warn("[labels] missing label", group, value);
    }
  }
  return value;
}

export const cardTypeLabel = (value: string, locale?: LabelLocale) => labelFor("cardType", value, locale);
export const cardStatusLabel = (value: string, locale?: LabelLocale) => labelFor("cardStatus", value, locale);
export const assetLevelLabel = (value: string, locale?: LabelLocale) => labelFor("assetLevel", value, locale);
export const createdByLabel = (value: string, locale?: LabelLocale) => labelFor("createdBy", value, locale);
export const sectionHintLabel = (value: string, locale?: LabelLocale) => labelFor("sectionHint", value, locale);
export const traceModeLabel = (value: string, locale?: LabelLocale) => labelFor("traceMode", value, locale);
