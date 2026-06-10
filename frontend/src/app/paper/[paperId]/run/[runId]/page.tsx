"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  createKnowledgeCard,
  createPaperAnnotation,
  createReviewMark,
  deletePaperAnnotation,
  generateKnowledgeCards,
  getRun,
  getRunOutput,
  getPaperPdfUrl,
  getPaper,
  getPaperNote,
  getPaperSyncStatus,
  listKnowledgeCards,
  listPaperAnnotations,
  listReviewMarks,
  updatePaperAnnotation,
  updatePaperNote,
} from "@/lib/api";
import { useRunStream } from "@/hooks/useRunStream";
import { useTranslation } from "@/lib/i18n";
import MarkdownRenderer from "@/components/MarkdownRenderer";
import PdfViewer from "@/components/PdfViewer";
import SplitPane from "@/components/SplitPane";
import RankBadges from "@/components/RankBadges";
import { IconDownload, IconCheck } from "@/components/icons";
import type {
  AnalysisDifySyncStatus,
  AiReviewStatus,
  AiReviewMark,
  AnnotationType,
  PaperAnnotation,
  PaperNote,
  RunResponse,
  PaperResponse,
  SSEEvent,
  ProgressEntry,
  RunOutputJson,
  DocumentPartition,
  EvidenceAnchor,
  PdfHighlight,
  PdfSelectionAction,
  PdfSelectionRange,
  PdfTextSelection,
} from "@/lib/types";

type SelectionDraft = {
  draft_id: string;
  source: "pdf" | "ai";
  page: number;
  quote: string;
  ranges: PdfSelectionRange[];
  note: string;
  annotation_type: AnnotationType;
  linked_annotation_id?: string;
  dirty: boolean;
};

function newDraftId() {
  return `draft_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function draftFromSelection(selection: PdfTextSelection, type: AnnotationType = "highlight"): SelectionDraft {
  return {
    draft_id: selection.selection_id || newDraftId(),
    source: selection.source,
    page: selection.page,
    quote: selection.quote,
    ranges: selection.ranges,
    note: "",
    annotation_type: type,
    dirty: false,
  };
}

function parseAnnotationRanges(annotation: PaperAnnotation): PdfSelectionRange[] {
  try {
    const parsed = annotation.bbox_json ? JSON.parse(annotation.bbox_json) : null;
    if (parsed && Array.isArray(parsed.ranges)) return parsed.ranges as PdfSelectionRange[];
  } catch {
    return [];
  }
  return [];
}

function annotationToDraft(annotation: PaperAnnotation): SelectionDraft {
  return {
    draft_id: `ann_${annotation.annotation_id}`,
    source: "pdf",
    page: annotation.page,
    quote: annotation.quote,
    ranges: parseAnnotationRanges(annotation),
    note: annotation.note,
    annotation_type: annotation.annotation_type,
    linked_annotation_id: annotation.annotation_id,
    dirty: false,
  };
}

function draftBboxJson(draft: SelectionDraft) {
  return JSON.stringify({
    version: 1,
    source: draft.source,
    ranges: draft.ranges,
  });
}

function mergeDraftSelection(draft: SelectionDraft, selection: PdfTextSelection): SelectionDraft {
  return {
    ...draft,
    page: Math.min(draft.page || selection.page, selection.page),
    quote: `${draft.quote.trim()}\n\n${selection.quote.trim()}`.trim(),
    ranges: [...draft.ranges, ...selection.ranges],
    dirty: true,
  };
}

function clearBrowserTextSelection() {
  if (typeof window === "undefined") return;
  window.getSelection()?.removeAllRanges();
}

export default function RunPage() {
  const params = useParams();
  const paperId = params.paperId as string;
  const runId = params.runId as string;
  const { t } = useTranslation();

  const [run, setRun] = useState<RunResponse | null>(null);
  const [paper, setPaper] = useState<PaperResponse | null>(null);
  const [markdown, setMarkdown] = useState<string>("");
  const [outputJson, setOutputJson] = useState<RunOutputJson | null>(null);
  const [analysisSync, setAnalysisSync] = useState<AnalysisDifySyncStatus | null>(null);
  const [note, setNote] = useState<PaperNote | null>(null);
  const [annotations, setAnnotations] = useState<PaperAnnotation[]>([]);
  const [reviewMarks, setReviewMarks] = useState<AiReviewMark[]>([]);
  const [aiDraftCardCount, setAiDraftCardCount] = useState(0);
  const [activeDraft, setActiveDraft] = useState<SelectionDraft | null>(null);
  const [pendingSelection, setPendingSelection] = useState<PdfTextSelection | null>(null);
  const [noteSaving, setNoteSaving] = useState(false);
  const [assetMessage, setAssetMessage] = useState("");
  const [assetPanelOpen, setAssetPanelOpen] = useState(false);
  const [targetPage, setTargetPage] = useState<number | undefined>(undefined);
  const [activeEvidenceAnchorId, setActiveEvidenceAnchorId] = useState("");
  const [pageLoadTime] = useState(() => performance.now());

  const { events, isConnected, isDone, error, connect } = useRunStream();

  useEffect(() => {
    const html = document.documentElement;
    const body = document.body;
    const prevHtmlOverscroll = html.style.overscrollBehavior;
    const prevBodyOverscroll = body.style.overscrollBehavior;

    window.scrollTo(0, 0);
    html.style.overscrollBehavior = "none";
    body.style.overscrollBehavior = "none";

    return () => {
      html.style.overscrollBehavior = prevHtmlOverscroll;
      body.style.overscrollBehavior = prevBodyOverscroll;
    };
  }, []);

  const applyRunOutput = useCallback((output: { markdown: string; json_data: string }) => {
    setMarkdown(output.markdown);
    try {
      setOutputJson(output.json_data ? JSON.parse(output.json_data) as RunOutputJson : null);
    } catch {
      setOutputJson(null);
    }
  }, []);

  const stepLabel = useCallback(
    (step: string) => t(`step.${step}`) || step,
    [t],
  );

  // Load paper info
  useEffect(() => {
    const t0 = performance.now();
    getPaper(paperId).then((p) => {
      console.log(`[RunPage] getPaper: ${(performance.now() - t0).toFixed(0)}ms`);
      setPaper(p);
    }).catch(() => {});
  }, [paperId]);

  const refreshSyncStatus = useCallback(() => {
    getPaperSyncStatus(paperId)
      .then((res) => {
        setAnalysisSync(res.analysis.find((row) => row.run_id === runId) || null);
      })
      .catch(() => {});
  }, [paperId, runId]);

  useEffect(() => {
    refreshSyncStatus();
  }, [refreshSyncStatus]);

  const refreshAssets = useCallback(() => {
    Promise.all([
      getPaperNote(paperId),
      listPaperAnnotations(paperId),
      listReviewMarks(paperId, runId),
      listKnowledgeCards({ runId, createdBy: "ai", status: "draft", limit: 200 }),
    ])
      .then(([noteRow, annotationRows, markRows, cardRows]) => {
        setNote(noteRow);
        setAnnotations(annotationRows);
        setReviewMarks(markRows);
        setAiDraftCardCount(cardRows.length);
      })
      .catch(() => {});
  }, [paperId, runId]);

  useEffect(() => {
    refreshAssets();
  }, [refreshAssets]);

  // Immediate check: if run is already completed (e.g. page refresh)
  useEffect(() => {
    const t0 = performance.now();
    getRun(runId).then((r) => {
      console.log(`[RunPage] Initial getRun: ${(performance.now() - t0).toFixed(0)}ms status=${r.status}`);
      setRun(r);
      if (r.status === "done") {
        getRunOutput(runId).then((o) => {
          console.log(`[RunPage] Initial getRunOutput: ${o.markdown.length} chars`);
          applyRunOutput(o);
          refreshSyncStatus();
        }).catch(() => {});
      }
    }).catch(() => {});
  }, [runId, refreshSyncStatus, applyRunOutput]);

  // Connect to SSE stream (direct to backend, bypasses Next.js proxy)
  useEffect(() => {
    if (run?.status !== "pending" && run?.status !== "running") return;
    console.log(`[RunPage] Mounting, connecting SSE for run=${runId} (page loaded ${(performance.now() - pageLoadTime).toFixed(0)}ms ago)`);
    connect(runId);
  }, [run?.status, runId, connect, pageLoadTime]);

  // When SSE reports done, fetch output immediately
  useEffect(() => {
    if (!isDone) return;
    const t0 = performance.now();
    getRun(runId).then((r) => {
      console.log(`[RunPage] SSE done -> getRun: ${(performance.now() - t0).toFixed(0)}ms status=${r.status}`);
      setRun(r);
    });
    getRunOutput(runId).then((o) => {
      console.log(`[RunPage] SSE done -> getRunOutput: ${(performance.now() - t0).toFixed(0)}ms markdown=${o.markdown.length} chars`);
      console.log(`[RunPage] Total time from page load to output: ${((performance.now() - pageLoadTime) / 1000).toFixed(1)}s`);
      applyRunOutput(o);
      refreshSyncStatus();
    }).catch(() => {});
  }, [isDone, runId, pageLoadTime, refreshSyncStatus, applyRunOutput]);

  // Always-on backup polling — runs regardless of SSE state until we have results
  useEffect(() => {
    if (markdown) return; // Already got results, stop polling
    if (run?.status === "failed") return; // Run failed, stop polling

    const interval = setInterval(() => {
      getRun(runId).then((r) => {
        setRun(r);
        if (r.status === "done") {
          console.log(`[RunPage] Polling detected completion, fetching output...`);
          getRunOutput(runId).then((o) => {
            console.log(`[RunPage] Poll -> getRunOutput: markdown=${o.markdown.length} chars`);
            applyRunOutput(o);
            refreshSyncStatus();
          }).catch(() => {});
        }
      }).catch(() => {});
      // Re-fetch paper to pick up venue/rank data from enrich_metadata
      if (!paper?.venue || (!paper?.sci_rank && !paper?.ccf_rank)) {
        getPaper(paperId).then((p) => setPaper(p)).catch(() => {});
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [runId, paperId, markdown, run?.status, paper?.venue, refreshSyncStatus, applyRunOutput]);

  const evidenceAnchors = (outputJson?.evidence_anchors || []) as EvidenceAnchor[];

  const handleCitationClick = useCallback((page: number, anchorId?: string) => {
    setTargetPage(page);
    setActiveEvidenceAnchorId(anchorId || "");
  }, []);

  const handleExportMarkdown = useCallback(() => {
    if (!markdown) return;
    const title = paper?.title || paperId;
    const mode = run?.mode || "analysis";
    const filename = `${title.replace(/[^a-zA-Z0-9一-鿿]+/g, "_").slice(0, 60)}_${mode}.md`;
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }, [markdown, paper?.title, paperId, run?.mode]);

  const handleAiSelection = useCallback(() => {
    const quote = window.getSelection()?.toString().trim() || "";
    if (!quote) return;
    setActiveDraft({
      draft_id: newDraftId(),
      source: "ai",
      page: 0,
      quote,
      ranges: [],
      note: "",
      annotation_type: "note",
      dirty: false,
    });
    setPendingSelection(null);
    setAssetPanelOpen(true);
  }, []);

  const handleSaveNote = useCallback(async () => {
    if (!note) return;
    setNoteSaving(true);
    setAssetMessage("");
    try {
      setNote(await updatePaperNote(paperId, {
        summary_user: note.summary_user,
        key_takeaways: note.key_takeaways,
        open_questions: note.open_questions,
        reading_decision: note.reading_decision,
      }));
      setAssetMessage("笔记已保存。");
    } catch (err) {
      setAssetMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setNoteSaving(false);
    }
  }, [note, paperId]);

  const saveDraftAsAnnotation = useCallback(async (type?: AnnotationType, explicitDraft?: SelectionDraft) => {
    const draft = explicitDraft || activeDraft;
    if (!draft) return null;
    const annotationType = type || draft.annotation_type;
    try {
      const body = {
        page: draft.page,
        quote: draft.quote,
        note: draft.note,
        annotation_type: annotationType,
        bbox_json: draftBboxJson({ ...draft, annotation_type: annotationType }),
      };
      const saved = draft.linked_annotation_id
        ? await updatePaperAnnotation(draft.linked_annotation_id, body)
        : await createPaperAnnotation(paperId, body);
      setActiveDraft(draft.linked_annotation_id ? annotationToDraft(saved) : null);
      setPendingSelection(null);
      clearBrowserTextSelection();
      refreshAssets();
      setAssetMessage(draft.linked_annotation_id ? "摘录已更新。" : "摘录已保存。");
      return saved;
    } catch (err) {
      setAssetMessage(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, [activeDraft, paperId, refreshAssets]);

  const handleCreateAnnotation = useCallback(async () => {
    await saveDraftAsAnnotation(activeDraft?.source === "pdf" ? "highlight" : "note");
  }, [activeDraft?.source, saveDraftAsAnnotation]);

  const handleCreateQuestionAnnotation = useCallback(async () => {
    await saveDraftAsAnnotation("question");
  }, [saveDraftAsAnnotation]);

  const handleCreateCard = useCallback(async (explicitDraft?: SelectionDraft) => {
    const draft = explicitDraft || activeDraft;
    if (!draft) return;
    try {
      await createKnowledgeCard({
        card_type: "claim",
        title: draft.quote.slice(0, 80),
        content: draft.quote,
        paper_id: paperId,
        source_page: draft.page,
        source_quote: draft.quote,
        created_by: "user",
        status: "draft",
      });
      setActiveDraft(null);
      setPendingSelection(null);
      clearBrowserTextSelection();
      refreshAssets();
      setAssetMessage("知识卡片已创建。");
    } catch (err) {
      setAssetMessage(err instanceof Error ? err.message : String(err));
    }
  }, [activeDraft, paperId, refreshAssets]);

  const handleReviewMark = useCallback(async (status: AiReviewStatus) => {
    if (!activeDraft) return;
    try {
      await createReviewMark({
        paper_id: paperId,
        run_id: runId,
        quote: activeDraft.quote,
        source_ref: activeDraft.source,
        status,
      });
      setAssetMessage("复核标记已保存。");
      refreshAssets();
    } catch (err) {
      setAssetMessage(err instanceof Error ? err.message : String(err));
    }
  }, [activeDraft, paperId, refreshAssets, runId]);

  const handleGenerateAiCards = useCallback(async () => {
    setAssetMessage("正在生成 AI 草稿卡片。");
    try {
      const res = await generateKnowledgeCards({ run_id: runId, paper_id: paperId, force: false, max_cards: 12 });
      setAssetMessage(`AI 草稿卡片：新建 ${res.cards_created} 张，跳过 ${res.cards_skipped} 张。`);
      refreshAssets();
    } catch (err) {
      setAssetMessage(err instanceof Error ? err.message : String(err));
    }
  }, [paperId, refreshAssets, runId]);

  const handleUpdateAnnotation = useCallback(async (
    annotation: PaperAnnotation,
    patch: { note?: string; annotation_type?: AnnotationType },
  ) => {
    try {
      await updatePaperAnnotation(annotation.annotation_id, patch);
      refreshAssets();
      setAssetMessage("摘录已更新。");
    } catch (err) {
      setAssetMessage(err instanceof Error ? err.message : String(err));
    }
  }, [refreshAssets]);

  const handleDeleteAnnotation = useCallback(async (annotation: PaperAnnotation) => {
    try {
      await deletePaperAnnotation(annotation.annotation_id);
      refreshAssets();
      setAssetMessage("摘录已删除。");
    } catch (err) {
      setAssetMessage(err instanceof Error ? err.message : String(err));
    }
  }, [refreshAssets]);

  const handlePdfSelection = useCallback((selection: PdfTextSelection) => {
    setPendingSelection(selection);
    setActiveEvidenceAnchorId("");
    setActiveDraft((draft) => {
      if (draft?.dirty) return draft;
      return draftFromSelection(selection);
    });
    setAssetPanelOpen(true);
    setAssetMessage("");
  }, []);

  const handleSelectionAction = useCallback(async (action: PdfSelectionAction) => {
    if (!pendingSelection && action !== "cancel") return;
    if (action === "cancel") {
      setPendingSelection(null);
      clearBrowserTextSelection();
      return;
    }
    if (action === "replace" && pendingSelection) {
      setActiveDraft(draftFromSelection(pendingSelection));
      setPendingSelection(null);
      clearBrowserTextSelection();
      setAssetPanelOpen(true);
      return;
    }
    if (action === "append" && pendingSelection) {
      setActiveDraft((draft) => draft ? mergeDraftSelection(draft, pendingSelection) : draftFromSelection(pendingSelection));
      setPendingSelection(null);
      clearBrowserTextSelection();
      setAssetPanelOpen(true);
      return;
    }
    const actionDraft = pendingSelection ? draftFromSelection(pendingSelection) : activeDraft;
    if (action === "save") {
      await saveDraftAsAnnotation("highlight", actionDraft || undefined);
    } else if (action === "question") {
      await saveDraftAsAnnotation("question", actionDraft || undefined);
    } else if (action === "card") {
      await handleCreateCard(actionDraft || undefined);
    }
  }, [activeDraft, handleCreateCard, pendingSelection, saveDraftAsAnnotation]);

  const handleDraftChange = useCallback((patch: Partial<SelectionDraft>) => {
    setActiveDraft((draft) => draft ? { ...draft, ...patch, dirty: true } : draft);
  }, []);

  const handleEditAnnotation = useCallback((annotation: PaperAnnotation) => {
    setActiveDraft(annotationToDraft(annotation));
    setPendingSelection(null);
    setAssetPanelOpen(true);
    setTargetPage(annotation.page || undefined);
  }, []);

  const savedHighlights: PdfHighlight[] = annotations
    .map((annotation) => ({
      id: annotation.annotation_id,
      ranges: parseAnnotationRanges(annotation),
      color: annotation.color,
      active: activeDraft?.linked_annotation_id === annotation.annotation_id,
    }))
    .filter((highlight) => highlight.ranges.length > 0);
  const highlights: PdfHighlight[] = activeDraft && !activeDraft.linked_annotation_id && activeDraft.ranges.length > 0
    ? [
        ...savedHighlights,
        { id: activeDraft.draft_id, ranges: activeDraft.ranges, color: "draft", active: true },
      ]
    : savedHighlights;

  // Progress steps merged from two sources:
  //   1. persisted `run.progress_json` (full history, even if SSE wasn't connected)
  //   2. live SSE events received this session
  // Deduplicate by step name, keeping the latest status per step.
  const progressSteps = (() => {
    const persisted: ProgressEntry[] = (() => {
      if (!run?.progress_json) return [];
      try {
        const parsed = JSON.parse(run.progress_json);
        return Array.isArray(parsed) ? (parsed as ProgressEntry[]) : [];
      } catch {
        return [];
      }
    })();

    const live = events
      .filter((e: SSEEvent) => e.event === "progress")
      .map((e: SSEEvent) => e.data as ProgressEntry);

    const map = new Map<string, ProgressEntry>();
    for (const s of [...persisted, ...live]) {
      if (s && typeof s.step === "string") map.set(s.step, s);
    }
    return Array.from(map.values());
  })();

  const currentStep = progressSteps.length > 0
    ? progressSteps[progressSteps.length - 1]
    : null;

  const isComplete = run?.status === "done" || (isDone && markdown);
  const isFailed = (run?.status === "failed" || !!error) && !isComplete;
  const isRunning = (run?.status === "running" || isConnected) && !isComplete && !isFailed;

  return (
    <div data-run-root className="fixed inset-x-0 bottom-0 top-14 flex overflow-hidden flex-col">
      {/* Header bar */}
      <div className="flex shrink-0 items-center gap-4 border-b border-border bg-card/60 px-5 py-2.5">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            {paper?.title || paperId}
          </p>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
            <span className="truncate">
              {t("run.mode")}: <span className="font-medium text-foreground/80">{run?.mode || "..."}</span>
              <span className="mx-1.5 opacity-40">·</span>
              {runId}
            </span>
            {paper && <RankBadges venue={paper.venue} year={paper.year} sciRank={paper.sci_rank} ccfRank={paper.ccf_rank} />}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {markdown && (
            <button
              onClick={handleExportMarkdown}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm transition-colors hover:bg-muted"
              title={t("run.export_md")}
            >
              <IconDownload className="text-[15px]" />
              {t("run.export_md")}
            </button>
          )}
          {isComplete && (
            <a
              href={`/knowledge?run_id=${encodeURIComponent(runId)}&status=draft&created_by=ai`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm transition-colors hover:bg-muted"
            >
              AI 卡片 {aiDraftCardCount}
            </a>
          )}
          {isRunning && (
            <span className="inline-flex items-center gap-2 text-sm font-medium text-primary">
              <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
              {currentStep ? stepLabel(currentStep.step) : t("run.status.running")}
            </span>
          )}
          {isComplete && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 px-2.5 py-1 text-sm font-medium text-success">
              <IconCheck className="text-[15px]" />
              {t("run.status.complete")}
            </span>
          )}
          {isFailed && (
            <span className="text-sm text-destructive">
              {error || run?.error_msg || t("run.status.unknown")}
            </span>
          )}
        </div>
      </div>

      {/* Smart Q&A question + detected intent banner */}
      {(run?.user_question || analysisSync) && (
        <div className="shrink-0 border-b border-border bg-accent/40 px-5 py-2.5">
          {run?.user_question && (
            <p className="text-xs">
              <span className="text-muted-foreground">{t("run.your_question")}</span>{" "}
              <span className="font-medium">{run.user_question}</span>
            </p>
          )}
          {run?.detected_intent && (
            <p className="mt-0.5 text-xs">
              <span className="text-muted-foreground">{t("run.detected_intent")}</span>{" "}
              <span className="font-medium text-primary">{t(`intent.${run.detected_intent}`)}</span>
            </p>
          )}
          {analysisSync && (
            <p className="mt-0.5 text-xs">
              <span className="text-muted-foreground">{t("step.analysis_dify_sync")}</span>{" "}
              <span className="font-medium text-primary">{t(`sync.${analysisSync.status}`)}</span>
              {analysisSync.document_id && (
                <span className="ml-2 font-mono text-muted-foreground">{analysisSync.document_id}</span>
              )}
            </p>
          )}
        </div>
      )}

      {/* Main content — split pane is always mounted so PDF loads immediately,
          while the left side shows progress / failure / markdown as state evolves. */}
      <div data-run-main className="min-h-0 flex-1 overflow-hidden">
        <SplitPane
          rightPaneClassName="min-h-0 overflow-hidden"
          left={
            markdown ? (
              <div className="px-6 py-8 sm:px-10" onMouseUp={handleAiSelection}>
                <div className="mx-auto max-w-3xl">
                  <DocumentPartitionPanel partitions={outputJson?.document_partitions || []} />
                  <MarkdownRenderer
                    content={markdown}
                    evidenceAnchors={evidenceAnchors}
                    onCitationClick={handleCitationClick}
                  />
                </div>
              </div>
            ) : isFailed ? (
              <div className="flex h-full items-center justify-center px-6">
                <div className="max-w-md rounded-2xl border border-destructive/25 bg-destructive/5 p-8 text-center">
                  <p className="mb-2 font-semibold text-destructive">{t("run.status.failed_label")}</p>
                  <p className="text-sm text-muted-foreground">
                    {error || run?.error_msg || t("run.status.unknown")}
                  </p>
                </div>
              </div>
            ) : (
              <div className="flex h-full items-start justify-center overflow-auto px-6 py-10">
                <div className="w-full max-w-sm text-center">
                  <div className="mx-auto mb-5 h-10 w-10 animate-spin rounded-full border-[3px] border-primary border-t-transparent" />
                  <p className="font-medium text-foreground">
                    {currentStep ? stepLabel(currentStep.step) : t("run.starting")}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t("run.pdf_ready_hint")}
                  </p>
                  {progressSteps.length > 0 && (
                    <div className="mx-auto mt-7 max-w-xs space-y-0.5 text-left">
                      {progressSteps.map((step, i) => {
                        const done = step.status === "done" || step.status === "skipped";
                        return (
                          <div
                            key={i}
                            className={`flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm ${
                              done ? "text-muted-foreground" : "bg-accent/50 font-medium"
                            }`}
                          >
                            {done ? (
                              <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-success/20 text-[11px] text-success">
                                <IconCheck />
                              </span>
                            ) : (
                              <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                            )}
                            <span>{stepLabel(step.step)}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )
          }
          right={
            <div data-split-right className="flex h-full min-h-0 overflow-hidden">
              <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
                <PdfViewer
                  url={getPaperPdfUrl(paperId)}
                  targetPage={targetPage}
                  highlights={highlights}
                  activeHighlightId={activeDraft?.linked_annotation_id || activeDraft?.draft_id || ""}
                  evidenceAnchors={evidenceAnchors}
                  activeEvidenceAnchorId={activeEvidenceAnchorId}
                  pendingSelection={pendingSelection}
                  onTextSelection={handlePdfSelection}
                  onSelectionAction={handleSelectionAction}
                />
              </div>
              {assetPanelOpen ? (
                <div className="w-[23rem] shrink-0 border-l border-border">
                  <ReadingAssetPanel
                    note={note}
                    annotations={annotations}
                    reviewMarks={reviewMarks}
                    activeDraft={activeDraft}
                    message={assetMessage}
                    saving={noteSaving}
                    onClose={() => setAssetPanelOpen(false)}
                    onNoteChange={setNote}
                    onSaveNote={handleSaveNote}
                    onDraftChange={handleDraftChange}
                    onCreateAnnotation={handleCreateAnnotation}
                    onCreateQuestionAnnotation={handleCreateQuestionAnnotation}
                    onCreateCard={handleCreateCard}
                    onGenerateAiCards={handleGenerateAiCards}
                    aiDraftCardCount={aiDraftCardCount}
                    runId={runId}
                    onReviewMark={handleReviewMark}
                    onUpdateAnnotation={handleUpdateAnnotation}
                    onDeleteAnnotation={handleDeleteAnnotation}
                    onEditAnnotation={handleEditAnnotation}
                    onJumpPage={setTargetPage}
                  />
                </div>
              ) : (
                <button
                  onClick={() => setAssetPanelOpen(true)}
                  className="flex w-11 shrink-0 items-center justify-center border-l border-border bg-card text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  title="显示阅读资产"
                >
                  <span className="[writing-mode:vertical-rl]">阅读资产</span>
                </button>
              )}
            </div>
          }
        />
      </div>
    </div>
  );
}

function DocumentPartitionPanel({ partitions }: { partitions: DocumentPartition[] }) {
  if (!partitions.length) return null;
  const partLabel: Record<DocumentPartition["part"], string> = {
    main_body: "正文",
    references: "References",
    appendix: "Appendix",
    supplementary: "Supplementary",
    unknown_tail: "未知尾部",
  };
  return (
    <section className="mb-5 rounded-lg border border-border bg-card px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">文档结构</h2>
        <span className="text-xs text-muted-foreground">{partitions.length} 个分区</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {partitions.map((partition, index) => (
          <div key={`${partition.part}-${index}`} className="rounded-md border border-border bg-background px-3 py-2">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="font-medium">{partLabel[partition.part] || partition.part}</span>
              <span className="text-muted-foreground">p.{partition.page_start}-p.{partition.page_end}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
              confidence={partition.confidence.toFixed(2)} · {partition.reason || partition.title}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ReadingAssetPanel({
  note,
  annotations,
  reviewMarks,
  activeDraft,
  message,
  saving,
  onClose,
  onNoteChange,
  onSaveNote,
  onDraftChange,
  onCreateAnnotation,
  onCreateQuestionAnnotation,
  onCreateCard,
  onGenerateAiCards,
  aiDraftCardCount,
  runId,
  onReviewMark,
  onUpdateAnnotation,
  onDeleteAnnotation,
  onEditAnnotation,
  onJumpPage,
}: {
  note: PaperNote | null;
  annotations: PaperAnnotation[];
  reviewMarks: AiReviewMark[];
  activeDraft: SelectionDraft | null;
  message: string;
  saving: boolean;
  onClose: () => void;
  onNoteChange: (note: PaperNote) => void;
  onSaveNote: () => void;
  onDraftChange: (patch: Partial<SelectionDraft>) => void;
  onCreateAnnotation: () => void;
  onCreateQuestionAnnotation: () => void;
  onCreateCard: () => void;
  onGenerateAiCards: () => void;
  aiDraftCardCount: number;
  runId: string;
  onReviewMark: (status: AiReviewStatus) => void;
  onUpdateAnnotation: (annotation: PaperAnnotation, patch: { note?: string; annotation_type?: AnnotationType }) => void;
  onDeleteAnnotation: (annotation: PaperAnnotation) => void;
  onEditAnnotation: (annotation: PaperAnnotation) => void;
  onJumpPage: (page: number) => void;
}) {
  return (
    <aside className="flex h-full flex-col bg-card">
      <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">阅读资产</h2>
          {message && <p className="mt-1 text-xs text-primary">{message}</p>}
        </div>
        <button onClick={onClose} className="rounded-lg border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted">
          收起
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-auto p-4">
        {note && (
          <section className="space-y-2">
            <h3 className="text-xs font-medium text-muted-foreground">整篇论文笔记</h3>
            <textarea
              value={note.summary_user}
              onChange={(e) => onNoteChange({ ...note, summary_user: e.target.value })}
              placeholder="个人摘要"
              rows={3}
              className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
            />
            <textarea
              value={note.key_takeaways}
              onChange={(e) => onNoteChange({ ...note, key_takeaways: e.target.value })}
              placeholder="关键收获"
              rows={3}
              className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
            />
            <textarea
              value={note.open_questions}
              onChange={(e) => onNoteChange({ ...note, open_questions: e.target.value })}
              placeholder="未解决问题"
              rows={3}
              className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
            />
            <input
              value={note.reading_decision}
              onChange={(e) => onNoteChange({ ...note, reading_decision: e.target.value })}
              placeholder="阅读决策"
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
            />
            <button onClick={onSaveNote} disabled={saving} className="w-full rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
              {saving ? "保存中" : "保存笔记"}
            </button>
          </section>
        )}

        <section className="rounded-lg border border-border bg-background p-3">
          <div className="mb-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>AI 草稿卡片</span>
            <span>{aiDraftCardCount}</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button onClick={onGenerateAiCards} className="rounded-lg border border-border px-2 py-1.5 text-xs hover:bg-muted">生成卡片</button>
            <a href={`/knowledge?run_id=${encodeURIComponent(runId)}&status=draft&created_by=ai`} className="rounded-lg border border-border px-2 py-1.5 text-center text-xs hover:bg-muted">
              去审核
            </a>
          </div>
        </section>

        {activeDraft && (
          <section className="rounded-lg border border-border bg-background p-3">
            <div className="mb-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">当前摘录草稿</span>
              <span>{activeDraft.source === "pdf" ? `PDF p.${activeDraft.page}` : "AI 输出"}</span>
              {activeDraft.linked_annotation_id && <span>已保存</span>}
            </div>
            <textarea
              value={activeDraft.quote}
              onChange={(e) => onDraftChange({ quote: e.target.value })}
              rows={5}
              className="w-full resize-y rounded-lg border border-border bg-card px-2 py-1.5 text-xs leading-5 outline-none focus:border-primary/50"
            />
            <textarea
              value={activeDraft.note}
              onChange={(e) => onDraftChange({ note: e.target.value })}
              placeholder="给这段摘录添加备注"
              rows={3}
              className="mt-2 w-full resize-y rounded-lg border border-border bg-card px-2 py-1.5 text-xs leading-5 outline-none focus:border-primary/50"
            />
            <select
              value={activeDraft.annotation_type}
              onChange={(e) => onDraftChange({ annotation_type: e.target.value as AnnotationType })}
              className="mt-2 w-full rounded-lg border border-border bg-card px-2 py-1.5 text-xs"
            >
              {(["highlight", "note", "question", "correction"] as AnnotationType[]).map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <button onClick={onCreateAnnotation} className="rounded-lg border border-border px-2 py-1.5 text-xs hover:bg-muted">
                {activeDraft.linked_annotation_id ? "更新摘录" : "保存摘录"}
              </button>
              <button onClick={onCreateQuestionAnnotation} className="rounded-lg border border-border px-2 py-1.5 text-xs hover:bg-muted">保存为问题</button>
              <button onClick={onCreateCard} className="rounded-lg border border-border px-2 py-1.5 text-xs hover:bg-muted">建卡片</button>
              <button onClick={() => onReviewMark("trusted")} className="rounded-lg border border-border px-2 py-1.5 text-xs hover:bg-muted">可信</button>
              <button onClick={() => onReviewMark("pending")} className="rounded-lg border border-border px-2 py-1.5 text-xs hover:bg-muted">待核验</button>
              <button onClick={() => onReviewMark("error")} className="rounded-lg border border-border px-2 py-1.5 text-xs hover:bg-muted">错误</button>
              <button onClick={() => onReviewMark("valuable")} className="rounded-lg border border-border px-2 py-1.5 text-xs hover:bg-muted">有价值</button>
            </div>
          </section>
        )}

        <section>
          <h3 className="mb-2 text-xs font-medium text-muted-foreground">页码级摘录</h3>
          <div className="space-y-2">
            {annotations.map((annotation) => (
              <AnnotationItem
                key={annotation.annotation_id}
                annotation={annotation}
                onJumpPage={onJumpPage}
                onEdit={onEditAnnotation}
                onUpdate={onUpdateAnnotation}
                onDelete={onDeleteAnnotation}
              />
            ))}
            {!annotations.length && <p className="py-6 text-center text-xs text-muted-foreground">暂无摘录。</p>}
          </div>
        </section>

        <section>
          <h3 className="mb-2 text-xs font-medium text-muted-foreground">AI 复核标记</h3>
          <div className="space-y-2">
            {reviewMarks.map((mark) => (
              <div key={mark.mark_id} className="rounded-lg border border-border bg-background p-3">
                <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>{mark.status}</span>
                  <span>{mark.source_ref || "AI"}</span>
                </div>
                <p className="line-clamp-3 text-xs leading-5">{mark.quote}</p>
                {mark.note && <p className="mt-1 text-xs text-muted-foreground">{mark.note}</p>}
              </div>
            ))}
            {!reviewMarks.length && <p className="py-6 text-center text-xs text-muted-foreground">暂无复核标记。</p>}
          </div>
        </section>
      </div>
    </aside>
  );
}

function AnnotationItem({
  annotation,
  onJumpPage,
  onEdit,
  onUpdate,
  onDelete,
}: {
  annotation: PaperAnnotation;
  onJumpPage: (page: number) => void;
  onEdit: (annotation: PaperAnnotation) => void;
  onUpdate: (annotation: PaperAnnotation, patch: { note?: string; annotation_type?: AnnotationType }) => void;
  onDelete: (annotation: PaperAnnotation) => void;
}) {
  const [note, setNote] = useState(annotation.note);
  const [type, setType] = useState<AnnotationType>(annotation.annotation_type);

  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <button onClick={() => onJumpPage(annotation.page)} className="block w-full text-left">
        <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
          <span>p.{annotation.page || "-"}</span>
          <span>{annotation.annotation_type}</span>
        </div>
        <p className="line-clamp-3 text-xs leading-5">{annotation.quote}</p>
      </button>
      <div className="mt-2 grid gap-2">
        <select
          value={type}
          onChange={(e) => setType(e.target.value as AnnotationType)}
          className="rounded-lg border border-border bg-card px-2 py-1.5 text-xs"
        >
          {(["highlight", "note", "question", "correction"] as AnnotationType[]).map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="备注"
          rows={2}
          className="resize-y rounded-lg border border-border bg-card px-2 py-1.5 text-xs outline-none focus:border-primary/50"
        />
        <div className="flex gap-2">
          <button onClick={() => onEdit(annotation)} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">编辑</button>
          <button onClick={() => onUpdate(annotation, { note, annotation_type: type })} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">保存</button>
          <button onClick={() => onDelete(annotation)} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">删除</button>
        </div>
      </div>
    </div>
  );
}
