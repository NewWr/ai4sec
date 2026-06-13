"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Locale = "en" | "zh";

const translations: Record<Locale, Record<string, string>> = {
  en: {
    // Nav
    "nav.brand": "Scholar",
    "nav.upload": "Upload & Analyze",
    "nav.papers": "Papers",
    "nav.library": "Knowledge Base",
    "nav.translate": "Translate",

    // Landing page
    "home.title": "Scholar Platform",
    "home.subtitle":
      "A local research workspace for paper analysis, daily discovery, corpus search, knowledge cards, translation, and system maintenance.",
    "home.mode.snap.title": "Insight Snap",
    "home.mode.snap.desc":
      "30-second triage. Core contributions, key findings, and whether it\u2019s worth reading.",
    "home.mode.lens.title": "Logic Lens",
    "home.mode.lens.desc":
      "Deep analysis of formulas, algorithms, and experiments with reproduction checklists.",
    "home.mode.sphere.title": "Research Sphere",
    "home.mode.sphere.desc":
      "Reference network analysis with multi-paper comparison and research gap identification.",
    "home.mode.qa.title": "Smart Q&A",
    "home.mode.qa.desc":
      "Ask a question; the system routes to the right analysis path or answers from the paper.",
    "home.cta": "Upload Paper",
    "home.secondary_cta": "Open Library",
    "home.eyebrow": "AI research workspace",
    "home.features_heading": "Workspace modules",
    "home.features_sub": "Jump directly into discovery, reading, corpus management, writing assets, translation, and operations.",
    "home.modes_heading": "Paper analysis modes",
    "home.modes_sub": "Use a fixed reading mode, or let Smart Q&A choose the route from your question.",
    "home.feature.upload.title": "Upload & analyze",
    "home.feature.upload.desc": "Upload PDFs, parse them with MinerU, choose a model and reading mode, then generate cited reports.",
    "home.feature.daily.title": "Daily recommendations",
    "home.feature.daily.desc": "Review daily candidate papers and decide which ones should enter the local library.",
    "home.feature.papers.title": "Local papers",
    "home.feature.papers.desc": "Manage PDFs, collections, reading status, metadata, analysis history, and Dify sync state.",
    "home.feature.library.title": "Corpus search & Q&A",
    "home.feature.library.desc": "Search the paper corpus with keyword, semantic, or hybrid retrieval and ask cross-paper questions.",
    "home.feature.knowledge.title": "Knowledge cards",
    "home.feature.knowledge.desc": "Extract claims, methods, datasets, results, limitations, writing snippets, and references.",
    "home.feature.spaces.title": "Knowledge spaces",
    "home.feature.spaces.desc": "Organize local spaces, bind Dify datasets, and preview synchronized source Markdown.",
    "home.feature.translate.title": "Translation",
    "home.feature.translate.desc": "Translate research text with the configured DeepLX service and copy the result.",
    "home.feature.health.title": "Maintenance",
    "home.feature.health.desc": "Inspect parsing, synchronization, metadata, and note-completion issues across the library.",
    "home.feature.settings.title": "Settings",
    "home.feature.settings.desc": "Configure LLM base URL, model list, reasoning effort, and API key from the web UI.",

    // Upload page
    "upload.title": "Upload & Analyze Paper",
    "upload.drop": "Drop PDF here or click to browse",
    "upload.supports": "Supports .pdf files",
    "upload.drop_error": "Please drop a PDF file",
    "upload.mode_label": "Reading Mode",
    "upload.mode.snap.label": "Insight Snap",
    "upload.mode.snap.desc": "30-second triage: contributions, findings, worth-reading assessment",
    "upload.mode.lens.label": "Logic Lens",
    "upload.mode.lens.desc": "Deep analysis: formulas, algorithms, experiment reproduction checklist",
    "upload.mode.sphere.label": "Research Sphere",
    "upload.mode.sphere.desc": "Reference network: multi-paper comparison, research gaps",
    "upload.mode.auto.label": "Smart Q&A",
    "upload.mode.auto.desc": "Ask a question; AI picks the best analysis mode (or answers directly)",
    "upload.question_label": "Your question",
    "upload.question_placeholder": "e.g., What datasets did they use? How does the loss function work?",
    "upload.question_required": "Please enter a question for Smart Q&A mode",
    "upload.question_hint": "AI will detect intent and route to the best analysis path",
    "upload.model_label": "LLM Model",
    "upload.model_loading": "Loading models…",
    "upload.model_empty": "No models configured (set THINKING_MODELNAME)",
    "upload.language_label": "Output Language",
    "upload.language_note": "Research workflow uses English internally; only the final output is translated.",
    "upload.submit": "Start Analysis",
    "upload.submitting": "Uploading & starting analysis...",
    "upload.fail": "Upload failed",

    // Recent runs panel
    "recent.active_header": "{count} run(s) still in progress — click to resume",
    "recent.history_header": "Recent runs ({count})",
    "recent.starting": "Starting...",
    "recent.resumed_toast": "Reconnected — showing latest progress",
    "recent.dismiss": "Dismiss",

    // Run page
    "run.mode": "Mode",
    "run.status.running": "Running...",
    "run.status.pending": "Pending",
    "run.status.done": "Done",
    "run.status.failed": "Failed",
    "run.status.complete": "Complete",
    "run.status.failed_label": "Analysis Failed",
    "run.status.unknown": "An unknown error occurred",
    "run.starting": "Starting analysis...",
    "run.export_md": "Export .md",
    "run.your_question": "Your question:",
    "run.detected_intent": "Detected intent:",
    "run.pdf_ready_hint": "The PDF is ready on the right — feel free to start reading while the analysis runs.",

    // Intent labels (mirrors mode labels but used for detected_intent display)
    "intent.snap": "Insight Snap",
    "intent.lens": "Logic Lens",
    "intent.sphere": "Research Sphere",
    "intent.qa": "Direct Q&A",

    // Steps
    "step.ingest_pdf": "Verifying PDF",
    "step.mineru_parse": "Parsing with MinerU",
    "step.build_paper_ir": "Building document structure",
    "step.detect_document_parts": "Detecting document parts",
    "step.dify_sync": "Syncing to knowledge base",
    "step.analysis_dify_sync": "Syncing analysis report",
    "step.enrich_metadata": "Looking up publication rank",
    "step.classify_intent": "Detecting question intent",
    "step.run_snap": "Generating Insight Snap",
    "step.run_lens": "Generating Logic Lens",
    "step.lens_overview": "Writing overview",
    "step.lens_method": "Writing method analysis",
    "step.lens_experiments": "Writing experiment analysis",
    "step.lens_assessment": "Writing critical assessment",
    "step.run_sphere": "Generating Research Sphere",
    "step.run_qa": "Answering your question",
    "step.translate_output": "Translating output",
    "step.persist_output": "Saving results",
    "step.sphere_init_from_pdf": "Extracting references from PDF",
    "step.extract_core_metadata": "Extracting core metadata",
    "step.resolve_canonical_ids": "Resolving paper identifiers",
    "step.expand_graph_candidates": "Expanding citation graph",
    "step.dedup_and_score": "Scoring and selecting candidates",
    "step.layer0_summarize_metadata": "Summarizing metadata",
    "step.layer1_abstract_snap": "Analyzing abstracts",
    "step.download_and_mineru_parse": "Downloading and parsing papers",
    "step.synthesize_landscape": "Synthesizing research landscape",
    "step.render_output": "Rendering final output",

    // PDF viewer
    "pdf.prev": "Prev",
    "pdf.next": "Next",
    "pdf.loading": "Loading PDF...",
    "pdf.jump_to_page": "Jump to page",

    // Local papers
    "papers.title": "Papers",
    "papers.subtitle": "Manage local PDFs, analysis history, and knowledge-base sync status.",
    "papers.upload": "Upload",
    "papers.search_placeholder": "Search title, DOI, venue, or paper id…",
    "papers.refresh": "Refresh",
    "papers.loading": "Loading papers…",
    "papers.empty": "No local papers yet.",
    "papers.parse": "Parse",
    "papers.latest_run": "Latest run",
    "papers.no_runs": "No analysis yet",
    "papers.dify_doc": "Dify document",
    "papers.no_doc": "No document id",
    "papers.start_run": "Analyze",
    "papers.starting": "Starting…",
    "papers.retry_sync": "Sync",
    "papers.syncing": "Syncing…",
    "papers.discovery.title": "Research Discovery Map",
    "papers.discovery.subtitle": "Theme grouping, local paper relationships, gap signals, and reading paths from your corpus.",
    "papers.discovery.total": "Papers",
    "papers.discovery.parsed": "Parsed",
    "papers.discovery.analyzed": "Analyzed",
    "papers.discovery.synced": "Synced",
    "papers.discovery.evidence": "Evidence",
    "papers.discovery.relations": "Relations",
    "papers.discovery.gaps_count": "Gaps",
    "papers.discovery.all_themes": "All themes",
    "papers.discovery.network": "Paper relationship network",
    "papers.discovery.no_edges": "No strong relationship detected yet.",
    "papers.discovery.gaps": "Innovation candidates",
    "papers.discovery.no_gaps": "No gap signal yet.",
    "papers.discovery.paths": "Reading paths",

    // Dify sync status
    "sync.not_synced": "Not synced",
    "sync.pending": "Pending",
    "sync.running": "Syncing",
    "sync.synced": "Synced",
    "sync.skipped": "Skipped",
    "sync.failed": "Failed",

    // Knowledge base (library)
    "library.title": "Knowledge Base",
    "library.subtitle": "Search and ask across your research-paper corpus.",
    "library.tab.search": "Search",
    "library.tab.ask": "Ask",
    "library.method_label": "Retrieval",
    "library.method.keyword_search": "Keyword",
    "library.method.full_text_search": "Fast",
    "library.method.semantic_search": "Semantic",
    "library.method.hybrid_search": "Hybrid",
    "library.method_slow_hint": "Semantic / hybrid search is higher quality but slow (may take 30s+).",
    "library.ask_scope_label": "Scope",
    "library.ask_scope.hybrid": "Local graph + Dify",
    "library.ask_scope.graph_only": "Local graph only",
    "library.search_placeholder": "Search the corpus…",
    "library.ask_placeholder": "Ask a question across all your papers…",
    "library.run_search": "Search",
    "library.run_ask": "Ask",
    "library.searching": "Searching…",
    "library.thinking": "Thinking…",
    "library.results_count": "{count} result(s)",
    "library.no_results": "No results.",
    "library.documents": "Documents",
    "library.dataset_label": "Corpus",
    "library.load_more": "Load more",
    "library.sources": "Sources",
    "library.open_doc": "Open source document",
    "library.doc_loading": "Loading document…",
    "library.select_hint": "Select a result or document to preview it here.",
    "library.empty_query": "Enter a search query first.",
    "library.empty_question": "Enter a question first.",
    "library.disabled": "Knowledge base is not configured (set DIFY_API_BASE).",
    "library.error": "Request failed",
  },
  zh: {
    // Nav
    "nav.brand": "Scholar",
    "nav.upload": "上传与分析",
    "nav.papers": "本地论文",
    "nav.library": "知识库",
    "nav.translate": "翻译",

    // Landing page
    "home.title": "Scholar 学术平台",
    "home.subtitle":
      "面向本地文献工作的研究工作台，覆盖论文分析、每日发现、语料检索、知识卡片、翻译和系统维护。",
    "home.mode.snap.title": "快速洞察 (Insight Snap)",
    "home.mode.snap.desc":
      "30秒速览：核心贡献、关键发现、是否值得深读。",
    "home.mode.lens.title": "逻辑透镜 (Logic Lens)",
    "home.mode.lens.desc":
      "深度分析公式、算法与实验，附复现检查清单。",
    "home.mode.sphere.title": "研究全景 (Research Sphere)",
    "home.mode.sphere.desc":
      "参考文献网络分析，多论文对比与研究空白识别。",
    "home.mode.qa.title": "智能问答 (Smart Q&A)",
    "home.mode.qa.desc":
      "输入问题后自动选择分析路径，也可直接基于论文作答。",
    "home.cta": "上传论文",
    "home.secondary_cta": "打开文献库",
    "home.eyebrow": "AI 研究工作台",
    "home.features_heading": "工作台模块",
    "home.features_sub": "直接进入论文发现、阅读分析、语料管理、写作素材、翻译和运维页面。",
    "home.modes_heading": "论文分析模式",
    "home.modes_sub": "可固定选择阅读模式，也可让智能问答根据问题自动选择路径。",
    "home.feature.upload.title": "上传与分析",
    "home.feature.upload.desc": "上传 PDF，经 MinerU 解析后选择模型和阅读模式，生成带证据引用的报告。",
    "home.feature.daily.title": "每日推荐",
    "home.feature.daily.desc": "查看每日候选论文，手动决定是否解析并纳入本地文献库。",
    "home.feature.papers.title": "本地论文",
    "home.feature.papers.desc": "管理 PDF、分类、阅读状态、元数据、分析历史和 Dify 同步状态。",
    "home.feature.library.title": "语料检索与问答",
    "home.feature.library.desc": "用关键词、语义或混合检索查询论文语料库，并进行跨论文问答。",
    "home.feature.knowledge.title": "知识卡片",
    "home.feature.knowledge.desc": "沉淀观点、方法、数据集、结果、局限、写作片段和参考文献。",
    "home.feature.spaces.title": "知识空间",
    "home.feature.spaces.desc": "统一管理本地知识空间、绑定 Dify 数据集并预览同步后的 Markdown。",
    "home.feature.translate.title": "在线翻译",
    "home.feature.translate.desc": "使用当前配置的 DeepLX 服务翻译研究文本，并复制译文。",
    "home.feature.health.title": "维护检查",
    "home.feature.health.desc": "检查文献库中的解析、同步、元数据和笔记完整性问题。",
    "home.feature.settings.title": "系统设置",
    "home.feature.settings.desc": "在网页中配置 LLM Base URL、模型列表、思考等级和 API Key。",

    // Upload page
    "upload.title": "上传与分析论文",
    "upload.drop": "将PDF拖放到此处或点击浏览",
    "upload.supports": "支持 .pdf 文件",
    "upload.drop_error": "请拖放PDF文件",
    "upload.mode_label": "阅读模式",
    "upload.mode.snap.label": "快速洞察 (Insight Snap)",
    "upload.mode.snap.desc": "30秒速览：核心贡献、关键发现、是否值得深读",
    "upload.mode.lens.label": "逻辑透镜 (Logic Lens)",
    "upload.mode.lens.desc": "深度分析：公式、算法、实验复现检查清单",
    "upload.mode.sphere.label": "研究全景 (Research Sphere)",
    "upload.mode.sphere.desc": "参考文献网络：多论文对比、研究空白",
    "upload.mode.auto.label": "智能问答 (Smart Q&A)",
    "upload.mode.auto.desc": "提出问题，AI 自动选择最合适的分析路径（也可直接作答）",
    "upload.question_label": "您的问题",
    "upload.question_placeholder": "如：他们用了什么数据集？损失函数是如何工作的？",
    "upload.question_required": "智能问答模式需要输入问题",
    "upload.question_hint": "AI 将识别问题意图，并选择最合适的分析路径",
    "upload.model_label": "LLM 模型",
    "upload.model_loading": "正在加载模型…",
    "upload.model_empty": "未配置可选模型（请设置 THINKING_MODELNAME）",
    "upload.language_label": "输出语言",
    "upload.language_note": "研究流程内部使用英文；仅最终输出会被翻译。",
    "upload.submit": "开始分析",
    "upload.submitting": "正在上传并启动分析...",
    "upload.fail": "上传失败",

    // 最近运行面板
    "recent.active_header": "{count} 个任务仍在进行中 — 点击恢复查看",
    "recent.history_header": "最近运行（{count}）",
    "recent.starting": "启动中...",
    "recent.resumed_toast": "已重新连接 — 已显示最新进度",
    "recent.dismiss": "清除",

    // Run page
    "run.mode": "模式",
    "run.status.running": "运行中...",
    "run.status.pending": "等待中",
    "run.status.done": "已完成",
    "run.status.failed": "失败",
    "run.status.complete": "已完成",
    "run.status.failed_label": "分析失败",
    "run.status.unknown": "发生未知错误",
    "run.starting": "正在启动分析...",
    "run.export_md": "导出 .md",
    "run.your_question": "您的问题：",
    "run.detected_intent": "识别意图：",
    "run.pdf_ready_hint": "右侧已加载论文原文，AI 分析期间可先行阅读。",

    // 意图标签（对应模式名称，仅用于展示分类器识别结果）
    "intent.snap": "快速洞察",
    "intent.lens": "逻辑透镜",
    "intent.sphere": "研究全景",
    "intent.qa": "直接问答",

    // Steps
    "step.ingest_pdf": "验证PDF文件",
    "step.mineru_parse": "MinerU解析中",
    "step.build_paper_ir": "构建文档结构",
    "step.detect_document_parts": "识别正文与补充材料",
    "step.dify_sync": "同步到知识库",
    "step.analysis_dify_sync": "同步分析文档",
    "step.enrich_metadata": "查询期刊等级",
    "step.classify_intent": "识别问题意图",
    "step.run_snap": "生成快速洞察",
    "step.run_lens": "生成逻辑透镜",
    "step.lens_overview": "生成概览与动机",
    "step.lens_method": "生成方法深读",
    "step.lens_experiments": "生成实验与结果",
    "step.lens_assessment": "生成批判性评估",
    "step.run_sphere": "生成研究全景",
    "step.run_qa": "解答您的问题",
    "step.translate_output": "翻译输出内容",
    "step.persist_output": "保存结果",
    "step.sphere_init_from_pdf": "从PDF提取参考文献",
    "step.extract_core_metadata": "提取核心元数据",
    "step.resolve_canonical_ids": "解析论文标识符",
    "step.expand_graph_candidates": "扩展引用图谱",
    "step.dedup_and_score": "评分与筛选候选论文",
    "step.layer0_summarize_metadata": "汇总元数据",
    "step.layer1_abstract_snap": "分析摘要",
    "step.download_and_mineru_parse": "下载并解析论文",
    "step.synthesize_landscape": "综合研究全景",
    "step.render_output": "渲染最终输出",

    // PDF viewer
    "pdf.prev": "上一页",
    "pdf.next": "下一页",
    "pdf.loading": "加载PDF中...",
    "pdf.jump_to_page": "跳转到第{page}页",

    // 本地论文
    "papers.title": "本地论文",
    "papers.subtitle": "管理本地 PDF、分析历史和知识库同步状态。",
    "papers.upload": "上传",
    "papers.search_placeholder": "按标题、DOI、期刊/会议或论文 ID 检索…",
    "papers.refresh": "刷新",
    "papers.loading": "正在加载论文…",
    "papers.empty": "暂无本地论文。",
    "papers.parse": "解析",
    "papers.latest_run": "最近分析",
    "papers.no_runs": "尚未分析",
    "papers.dify_doc": "Dify 文档",
    "papers.no_doc": "无文档 ID",
    "papers.start_run": "分析",
    "papers.starting": "启动中…",
    "papers.retry_sync": "同步",
    "papers.syncing": "同步中…",
    "papers.discovery.title": "研究发现地图",
    "papers.discovery.subtitle": "基于本地论文生成主题归纳、论文关系、缺口信号和阅读路径。",
    "papers.discovery.total": "论文",
    "papers.discovery.parsed": "已解析",
    "papers.discovery.analyzed": "已分析",
    "papers.discovery.synced": "已同步",
    "papers.discovery.evidence": "证据",
    "papers.discovery.relations": "关系",
    "papers.discovery.gaps_count": "缺口",
    "papers.discovery.all_themes": "全部主题",
    "papers.discovery.network": "论文关系网",
    "papers.discovery.no_edges": "暂未检测到强关系。",
    "papers.discovery.gaps": "创新点候选",
    "papers.discovery.no_gaps": "暂未发现缺口信号。",
    "papers.discovery.paths": "阅读路径",

    // Dify 同步状态
    "sync.not_synced": "未同步",
    "sync.pending": "等待中",
    "sync.running": "同步中",
    "sync.synced": "已同步",
    "sync.skipped": "已跳过",
    "sync.failed": "失败",

    // 知识库
    "library.title": "我的文献库",
    "library.subtitle": "在你的论文语料库中检索与问答。",
    "library.tab.search": "检索",
    "library.tab.ask": "问答",
    "library.method_label": "检索方式",
    "library.method.keyword_search": "关键词",
    "library.method.full_text_search": "快速",
    "library.method.semantic_search": "语义",
    "library.method.hybrid_search": "混合",
    "library.method_slow_hint": "语义/混合检索质量更高但较慢（可能 30 秒以上）。",
    "library.ask_scope_label": "范围",
    "library.ask_scope.hybrid": "本地图谱 + Dify",
    "library.ask_scope.graph_only": "仅本地图谱",
    "library.search_placeholder": "检索语料库…",
    "library.ask_placeholder": "向你的全部论文提问…",
    "library.run_search": "检索",
    "library.run_ask": "提问",
    "library.searching": "检索中…",
    "library.thinking": "生成中…",
    "library.results_count": "{count} 条结果",
    "library.no_results": "无结果。",
    "library.documents": "文献列表",
    "library.dataset_label": "语料库",
    "library.load_more": "加载更多",
    "library.sources": "来源",
    "library.open_doc": "打开来源文档",
    "library.doc_loading": "加载文档中…",
    "library.select_hint": "在此预览所选结果或文档。",
    "library.empty_query": "请先输入检索词。",
    "library.empty_question": "请先输入问题。",
    "library.disabled": "尚未配置知识库（请设置 DIFY_API_BASE）。",
    "library.error": "请求失败",
  },
};

interface LanguageContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextValue>({
  locale: "en",
  setLocale: () => {},
  t: (key) => key,
});

const STORAGE_KEY = "scholar-locale";

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  // Load from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "zh" || saved === "en") {
      setLocaleState(saved);
    }
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    localStorage.setItem(STORAGE_KEY, l);
  }, []);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      let text = translations[locale][key] ?? translations.en[key] ?? key;
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          text = text.replace(`{${k}}`, String(v));
        }
      }
      return text;
    },
    [locale],
  );
  const value = useMemo(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t],
  );

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useTranslation() {
  return useContext(LanguageContext);
}

export function LanguageToggle() {
  const { locale, setLocale } = useTranslation();

  return (
    <button
      onClick={() => setLocale(locale === "en" ? "zh" : "en")}
      className="rounded-full border border-border px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:border-foreground/25 hover:text-foreground"
      title={locale === "en" ? "切换到中文" : "Switch to English"}
    >
      {locale === "en" ? "中文" : "EN"}
    </button>
  );
}
