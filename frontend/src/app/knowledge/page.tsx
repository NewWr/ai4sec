"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  batchUpdateKnowledgeCardStatus,
  createKnowledgeCard,
  createWritingSnippet,
  deleteWritingSnippet,
  exportPapersBibtex,
  exportPapersRis,
  exportWritingMarkdown,
  generateKnowledgeCards,
  importReferences,
  listKnowledgeCards,
  listWritingSnippets,
  mergeKnowledgeCard,
  updateKnowledgeCard,
  updateWritingSnippet,
} from "@/lib/api";
import type {
  KnowledgeCard,
  KnowledgeCardStatus,
  KnowledgeCardType,
  WritingSnippet,
  SectionHint,
} from "@/lib/types";

const CARD_TYPES: KnowledgeCardType[] = ["claim", "method", "dataset", "metric", "result", "limitation", "question", "idea"];
const CARD_STATUSES: KnowledgeCardStatus[] = ["draft", "verified", "rejected", "merged"];
const SECTION_HINTS: SectionHint[] = ["related_work", "method", "experiment", "limitation"];

type CardDraft = {
  card_type: KnowledgeCardType;
  title: string;
  content: string;
  paper_id: string;
  source_page: string;
  source_quote: string;
  tags: string;
};

const EMPTY_DRAFT: CardDraft = {
  card_type: "claim",
  title: "",
  content: "",
  paper_id: "",
  source_page: "",
  source_quote: "",
  tags: "",
};

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function KnowledgePage() {
  const [cards, setCards] = useState<KnowledgeCard[]>([]);
  const [snippets, setSnippets] = useState<WritingSnippet[]>([]);
  const [query, setQuery] = useState("");
  const [cardType, setCardType] = useState("");
  const [assetLevel, setAssetLevel] = useState<"" | "action" | "synthesis" | "evidence">("action");
  const [status, setStatus] = useState("active");
  const [createdBy, setCreatedBy] = useState("");
  const [runId, setRunId] = useState("");
  const [hasSource, setHasSource] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState<CardDraft>(EMPTY_DRAFT);
  const [referenceText, setReferenceText] = useState("");
  const [referenceFormat, setReferenceFormat] = useState<"bibtex" | "ris">("bibtex");
  const [mergeTargets, setMergeTargets] = useState<Record<string, string>>({});
  const [exportText, setExportText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cardRows, snippetRows] = await Promise.all([
        listKnowledgeCards({
          query,
          cardType,
          status: status === "active" ? "" : status,
          createdBy,
          runId,
          assetLevel,
          hasSource,
        }),
        listWritingSnippets(),
      ]);
      setCards(status === "active" ? cardRows.filter((card) => card.status !== "rejected" && card.status !== "merged") : cardRows);
      setSelectedIds(new Set());
      setSnippets(snippetRows);
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setLoading(false);
    }
  }, [assetLevel, cardType, createdBy, hasSource, query, runId, status]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const qs = new URLSearchParams(window.location.search);
    const statusParam = qs.get("status");
    if (statusParam === "draft" || statusParam === "verified" || statusParam === "rejected" || statusParam === "merged") {
      setStatus(statusParam);
    }
    const createdByParam = qs.get("created_by");
    if (createdByParam === "ai" || createdByParam === "user") setCreatedBy(createdByParam);
    const runIdParam = qs.get("run_id");
    if (runIdParam) setRunId(runIdParam);
    const hasSourceParam = qs.get("has_source");
    if (hasSourceParam === "true" || hasSourceParam === "false") setHasSource(hasSourceParam);
    const assetLevelParam = qs.get("asset_level");
    if (assetLevelParam === "action" || assetLevelParam === "synthesis" || assetLevelParam === "evidence") {
      setAssetLevel(assetLevelParam);
    }
  }, []);

  const pendingAiCards = useMemo(
    () => cards.filter((card) => card.created_by === "ai" && card.status === "draft"),
    [cards],
  );

  const assetCounts = useMemo(
    () => ({
      action: cards.filter((card) => card.asset_level === "action").length,
      synthesis: cards.filter((card) => card.asset_level === "synthesis").length,
      evidence: cards.filter((card) => card.asset_level === "evidence").length,
    }),
    [cards],
  );

  const selectedCards = useMemo(
    () => cards.filter((card) => selectedIds.has(card.card_id)),
    [cards, selectedIds],
  );

  const toggleSelected = useCallback((cardId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(cardId)) next.delete(cardId);
      else next.add(cardId);
      return next;
    });
  }, []);

  const handleCreateCard = useCallback(async () => {
    const title = draft.title.trim();
    if (!title) {
      setError("请输入卡片标题。");
      return;
    }
    setSaving(true);
    try {
      await createKnowledgeCard({
        card_type: draft.card_type,
        title,
        content: draft.content.trim(),
        paper_id: draft.paper_id.trim(),
        source_page: draft.source_page ? Number(draft.source_page) : 0,
        source_quote: draft.source_quote.trim(),
        tags: draft.tags.trim(),
        status: "draft",
        created_by: "user",
      });
      setDraft(EMPTY_DRAFT);
      await load();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setSaving(false);
    }
  }, [draft, load]);

  const handleStatus = useCallback(async (card: KnowledgeCard, nextStatus: KnowledgeCardStatus) => {
    if (nextStatus === "verified" && !hasTraceableSource(card)) {
      const ok = window.confirm("这张卡片来源不完整，仍要确认吗？");
      if (!ok) return;
    }
    try {
      const updated = await updateKnowledgeCard(card.card_id, { status: nextStatus, allow_untraceable: nextStatus === "verified" && !hasTraceableSource(card) });
      setCards((prev) => prev.map((item) => item.card_id === card.card_id ? updated : item));
    } catch (err) {
      setError(errMessage(err));
    }
  }, []);

  const handleBatchStatus = useCallback(async (nextStatus: KnowledgeCardStatus) => {
    if (!selectedCards.length) return;
    const hasUntraceable = selectedCards.some((card) => nextStatus === "verified" && !hasTraceableSource(card));
    if (hasUntraceable) {
      const ok = window.confirm("选中的卡片包含来源不完整的事实卡片，仍要确认吗？");
      if (!ok) return;
    }
    try {
      const updated = await batchUpdateKnowledgeCardStatus({
        card_ids: selectedCards.map((card) => card.card_id),
        status: nextStatus,
        allow_untraceable: hasUntraceable,
      });
      const byId = new Map(updated.map((card) => [card.card_id, card]));
      setCards((prev) => prev.map((item) => byId.get(item.card_id) || item));
      setSelectedIds(new Set());
    } catch (err) {
      setError(errMessage(err));
    }
  }, [selectedCards]);

  const handleGenerateCards = useCallback(async () => {
    const targetRunId = runId.trim();
    const targetPaperId = draft.paper_id.trim();
    if (!targetRunId && !targetPaperId) {
      setError("请输入 run_id，或在新建卡片区域填写 paper_id 后生成。");
      return;
    }
    setSaving(true);
    try {
      const res = await generateKnowledgeCards({
        run_id: targetRunId,
        paper_id: targetPaperId,
        force: false,
        max_cards: 12,
      });
      setExportText(`生成状态：${res.status}\n新建 ${res.cards_created} 张，跳过 ${res.cards_skipped} 张，重复 ${res.duplicate_count} 张。\n${res.error_msg || ""}`);
      if (res.run_id && !runId) setRunId(res.run_id);
      setCreatedBy("ai");
      setStatus("draft");
      setAssetLevel("action");
      await load();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setSaving(false);
    }
  }, [draft.paper_id, load, runId]);

  const handleSnippet = useCallback(async (card: KnowledgeCard, sectionHint: SectionHint) => {
    if (card.status === "rejected" || card.status === "merged") {
      setError("废弃或已合并的卡片不能加入写作素材。");
      return;
    }
    if (card.status === "draft") {
      const ok = window.confirm("这张卡片还未确认，仍要加入写作素材吗？");
      if (!ok) return;
    }
    try {
      await createWritingSnippet({
        content: card.content || card.title,
        source_card_id: card.card_id,
        paper_id: card.paper_id,
        citation_key: card.citation_key,
        source_page: card.source_page,
        source_quote: card.source_quote,
        section_hint: sectionHint,
      });
      setSnippets(await listWritingSnippets());
    } catch (err) {
      setError(errMessage(err));
    }
  }, []);

  const handleMerge = useCallback(async (card: KnowledgeCard) => {
    const target = mergeTargets[card.card_id];
    if (!target) return;
    try {
      const updated = await mergeKnowledgeCard(card.card_id, target);
      setCards((prev) => prev.map((item) => item.card_id === card.card_id ? updated : item));
      setMergeTargets((prev) => ({ ...prev, [card.card_id]: "" }));
    } catch (err) {
      setError(errMessage(err));
    }
  }, [mergeTargets]);

  const handleExportMarkdown = useCallback(async () => {
    try {
      setExportText((await exportWritingMarkdown()).content);
    } catch (err) {
      setError(errMessage(err));
    }
  }, []);

  const handleExportBibtex = useCallback(async () => {
    try {
      setExportText((await exportPapersBibtex()).content);
    } catch (err) {
      setError(errMessage(err));
    }
  }, []);

  const handleExportRis = useCallback(async () => {
    try {
      setExportText((await exportPapersRis()).content);
    } catch (err) {
      setError(errMessage(err));
    }
  }, []);

  const handleImportReferences = useCallback(async () => {
    const content = referenceText.trim();
    if (!content) {
      setError("请输入 BibTeX 或 RIS 内容。");
      return;
    }
    setSaving(true);
    try {
      const res = await importReferences({ content, format: referenceFormat });
      setExportText(`导入 ${res.imported} 条，跳过 ${res.skipped} 条。\n仅导入引用记录，不代表已有 PDF 或解析结果。\n${res.paper_ids.join("\n")}`);
      setReferenceText("");
      await load();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setSaving(false);
    }
  }, [load, referenceFormat, referenceText]);

  return (
    <div className="mx-auto max-w-6xl px-5 py-8">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">知识卡片</h1>
          <p className="mt-1 text-sm text-muted-foreground">管理已确认知识、待确认 AI 卡片和写作素材。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={handleExportMarkdown} className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted">
            导出素材 Markdown
          </button>
          <button onClick={handleExportBibtex} className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted">
            导出 BibTeX
          </button>
          <button onClick={handleExportRis} className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted">
            导出 RIS
          </button>
        </div>
      </div>

      {error && <p className="mb-4 rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}

      <section className="mb-5 grid gap-4 lg:grid-cols-[1.2fr_.8fr]">
        <div className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">新建知识卡片</h2>
          <div className="grid gap-2 md:grid-cols-2">
            <select value={draft.card_type} onChange={(e) => setDraft({ ...draft, card_type: e.target.value as KnowledgeCardType })} className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
              {CARD_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
            <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="标题" className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50" />
            <input value={draft.paper_id} onChange={(e) => setDraft({ ...draft, paper_id: e.target.value })} placeholder="paper_id" className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50" />
            <input value={draft.source_page} onChange={(e) => setDraft({ ...draft, source_page: e.target.value })} placeholder="来源页码" inputMode="numeric" className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50" />
            <textarea value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} placeholder="内容" rows={3} className="resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50 md:col-span-2" />
            <textarea value={draft.source_quote} onChange={(e) => setDraft({ ...draft, source_quote: e.target.value })} placeholder="原文摘录" rows={2} className="resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50 md:col-span-2" />
            <input value={draft.tags} onChange={(e) => setDraft({ ...draft, tags: e.target.value })} placeholder="标签，逗号分隔" className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50 md:col-span-2" />
          </div>
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <button onClick={handleGenerateCards} disabled={saving} className="rounded-lg border border-border px-4 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50">
              生成 AI 草稿
            </button>
            <button onClick={handleCreateCard} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
              {saving ? "保存中" : "保存卡片"}
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">导入参考文献</h2>
          <div className="mb-2 flex items-center gap-2">
            <select
              value={referenceFormat}
              onChange={(e) => setReferenceFormat(e.target.value as "bibtex" | "ris")}
              className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
            >
              <option value="bibtex">BibTeX</option>
              <option value="ris">RIS</option>
            </select>
            <button
              onClick={handleImportReferences}
              disabled={saving}
              className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
            >
              导入
            </button>
          </div>
          <textarea
            value={referenceText}
            onChange={(e) => setReferenceText(e.target.value)}
            placeholder="@article{...} 或 TY  - JOUR"
            rows={8}
            className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-primary/50"
          />
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">写作素材篮</h2>
          <div className="max-h-[28rem] space-y-2 overflow-auto pr-1">
            {snippets.slice(0, 12).map((snippet) => (
              <SnippetItem
                key={snippet.snippet_id}
                snippet={snippet}
                onUpdate={async (content) => {
                  await updateWritingSnippet(snippet.snippet_id, { content });
                  setSnippets(await listWritingSnippets());
                }}
                onDelete={async () => {
                  await deleteWritingSnippet(snippet.snippet_id);
                  setSnippets(await listWritingSnippets());
                }}
                onError={setError}
              />
            ))}
            {!snippets.length && <p className="py-8 text-center text-sm text-muted-foreground">暂无素材。</p>}
          </div>
        </div>
      </section>

      <section className="mb-5 rounded-xl border border-border bg-card p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {[
            { value: "action", label: "行动卡", count: assetCounts.action },
            { value: "synthesis", label: "综合卡", count: assetCounts.synthesis },
            { value: "evidence", label: "证据卡", count: assetCounts.evidence },
            { value: "", label: "全部", count: cards.length },
          ].map((item) => (
            <button
              key={item.value || "all"}
              type="button"
              onClick={() => setAssetLevel(item.value as "" | "action" | "synthesis" | "evidence")}
              className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                assetLevel === item.value
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border hover:bg-muted"
              }`}
            >
              {item.label} {item.count}
            </button>
          ))}
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索卡片标题、内容、quote 或标签" className="min-w-[16rem] flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50" />
          <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="run_id" className="w-44 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50" />
          <select value={cardType} onChange={(e) => setCardType(e.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
            <option value="">全部类型</option>
            {CARD_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
          <select value={createdBy} onChange={(e) => setCreatedBy(e.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
            <option value="">全部来源</option>
            <option value="ai">AI 草稿</option>
            <option value="user">用户创建</option>
          </select>
          <select value={hasSource} onChange={(e) => setHasSource(e.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
            <option value="">来源状态</option>
            <option value="true">有来源</option>
            <option value="false">来源不完整</option>
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
            <option value="active">活跃卡片</option>
            <option value="">全部状态</option>
            {CARD_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <button onClick={load} className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted">刷新</button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>待确认 AI 卡片：{pendingAiCards.length}；已选择：{selectedIds.size}</span>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setSelectedIds(new Set(cards.map((card) => card.card_id)))} disabled={!cards.length} className="rounded-lg border border-border px-2 py-1 transition-colors hover:bg-muted disabled:opacity-40">
              全选
            </button>
            <button onClick={() => setSelectedIds(new Set())} disabled={!selectedIds.size} className="rounded-lg border border-border px-2 py-1 transition-colors hover:bg-muted disabled:opacity-40">
              清空
            </button>
            <button onClick={() => handleBatchStatus("verified")} disabled={!selectedIds.size} className="rounded-lg border border-border px-2 py-1 transition-colors hover:bg-muted disabled:opacity-40">
              批量确认
            </button>
            <button onClick={() => handleBatchStatus("rejected")} disabled={!selectedIds.size} className="rounded-lg border border-border px-2 py-1 transition-colors hover:bg-muted disabled:opacity-40">
              批量废弃
            </button>
          </div>
        </div>
      </section>

      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">加载中...</div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {cards.map((card) => (
            <CardItem
              key={card.card_id}
              card={card}
              cards={cards}
              mergeTarget={mergeTargets[card.card_id] || ""}
              onMergeTargetChange={(value) => setMergeTargets((prev) => ({ ...prev, [card.card_id]: value }))}
              onStatus={handleStatus}
              onSnippet={handleSnippet}
              onMerge={handleMerge}
              selected={selectedIds.has(card.card_id)}
              onToggleSelected={toggleSelected}
            />
          ))}
          {!cards.length && <div className="rounded-xl border border-border bg-card p-10 text-center text-sm text-muted-foreground lg:col-span-2">暂无知识卡片。</div>}
        </div>
      )}

      {exportText && (
        <section className="mt-5 rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">导出内容</h2>
          <pre className="max-h-96 overflow-auto rounded-lg border border-border bg-background p-3 text-xs leading-5 whitespace-pre-wrap">{exportText}</pre>
        </section>
      )}
    </div>
  );
}

function hasTraceableSource(card: KnowledgeCard): boolean {
  if (card.asset_level !== "evidence") return true;
  if (card.card_type === "idea" || card.card_type === "question") return true;
  return Boolean(card.paper_id && (card.source_quote || card.evidence_ids.length > 0));
}

function SnippetItem({
  snippet,
  onUpdate,
  onDelete,
  onError,
}: {
  snippet: WritingSnippet;
  onUpdate: (content: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(snippet.content);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await onUpdate(content);
      setEditing(false);
    } catch (err) {
      onError(errMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    const ok = window.confirm("删除这条写作素材？");
    if (!ok) return;
    try {
      await onDelete();
    } catch (err) {
      onError(errMessage(err));
    }
  };

  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{snippet.section_hint}</span>
        {snippet.citation_key && <span>@{snippet.citation_key}</span>}
      </div>
      {editing ? (
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={3}
          className="mt-2 w-full resize-y rounded-lg border border-border bg-card px-2 py-1.5 text-sm outline-none focus:border-primary/50"
        />
      ) : (
        <p className="mt-1 line-clamp-3 text-sm leading-6">{snippet.content}</p>
      )}
      <div className="mt-2 space-y-1 text-xs text-muted-foreground">
        {(snippet.paper_id || snippet.source_card_id || snippet.source_page > 0) && (
          <p>
            {snippet.paper_id && <span>paper: {snippet.paper_id.slice(0, 10)} </span>}
            {snippet.source_card_id && <span>card: {snippet.source_card_id.slice(0, 10)} </span>}
            {snippet.source_page > 0 && <span>p.{snippet.source_page}</span>}
          </p>
        )}
        {snippet.source_quote && <p className="line-clamp-2">quote: {snippet.source_quote}</p>}
      </div>
      <div className="mt-2 flex gap-2">
        {editing ? (
          <>
            <button onClick={save} disabled={saving} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50">
              {saving ? "保存中" : "保存"}
            </button>
            <button onClick={() => { setEditing(false); setContent(snippet.content); }} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">
              取消
            </button>
          </>
        ) : (
          <button onClick={() => setEditing(true)} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">编辑</button>
        )}
        <button onClick={remove} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">删除</button>
      </div>
    </div>
  );
}

function CardItem({
  card,
  cards,
  mergeTarget,
  onMergeTargetChange,
  onStatus,
  onSnippet,
  onMerge,
  selected,
  onToggleSelected,
}: {
  card: KnowledgeCard;
  cards: KnowledgeCard[];
  mergeTarget: string;
  onMergeTargetChange: (value: string) => void;
  onStatus: (card: KnowledgeCard, status: KnowledgeCardStatus) => void;
  onSnippet: (card: KnowledgeCard, sectionHint: SectionHint) => void;
  onMerge: (card: KnowledgeCard) => void;
  selected: boolean;
  onToggleSelected: (cardId: string) => void;
}) {
  return (
    <article className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 gap-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelected(card.card_id)}
            className="mt-1 h-4 w-4 shrink-0"
            aria-label="选择卡片"
          />
          <div className="min-w-0">
          <div className="flex flex-wrap gap-1.5">
            <span className={`rounded-full px-2 py-0.5 text-xs ${
              card.asset_level === "action"
                ? "bg-primary/10 text-primary"
                : card.asset_level === "synthesis"
                  ? "bg-success/10 text-success"
                  : "bg-muted text-muted-foreground"
            }`}>
              {card.asset_level}
            </span>
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{card.card_type}</span>
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{card.status}</span>
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{card.created_by}</span>
            {card.asset_level === "action" && card.action_type && <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{card.action_type}</span>}
            {card.priority && <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">P {card.priority}</span>}
            {card.confidence > 0 && <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">conf {card.confidence.toFixed(2)}</span>}
            <span className={`rounded-full px-2 py-0.5 text-xs ${hasTraceableSource(card) ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive"}`}>
              {hasTraceableSource(card) ? "有来源" : "来源不完整"}
            </span>
          </div>
          <h2 className="mt-2 break-words text-base font-semibold">{card.title}</h2>
          </div>
        </div>
        {card.paper_id && (
          <Link href={`/papers#paper-${card.paper_id}`} className="rounded-lg border border-border px-2 py-1.5 text-xs transition-colors hover:bg-muted">
            来源论文
          </Link>
        )}
      </div>
      {card.content && <p className="mt-3 text-sm leading-6 text-muted-foreground">{card.content}</p>}
      {(card.why_useful || card.next_action || card.risk_or_caveat) && (
        <div className="mt-3 space-y-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-sm">
          {card.why_useful && (
            <p>
              <span className="font-medium text-foreground">用途：</span>
              <span className="text-muted-foreground">{card.why_useful}</span>
            </p>
          )}
          {card.next_action && (
            <p>
              <span className="font-medium text-foreground">下一步：</span>
              <span className="text-muted-foreground">{card.next_action}</span>
            </p>
          )}
          {card.expected_output && (
            <p>
              <span className="font-medium text-foreground">产出：</span>
              <span className="text-muted-foreground">{card.expected_output}</span>
            </p>
          )}
          {card.risk_or_caveat && (
            <p>
              <span className="font-medium text-foreground">边界：</span>
              <span className="text-muted-foreground">{card.risk_or_caveat}</span>
            </p>
          )}
        </div>
      )}
      {card.source_quote && (
        <blockquote className="mt-3 border-l-2 border-primary/50 pl-3 text-xs leading-5 text-muted-foreground">
          p.{card.source_page || "-"} {card.source_quote}
        </blockquote>
      )}
      {(card.run_id || card.source_kind || card.source_ref || card.quality_flags.length > 0) && (
        <div className="mt-3 space-y-1 rounded-lg border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
          {card.run_id && <p>run: {card.run_id}</p>}
          {(card.source_kind || card.source_ref) && <p>source: {[card.source_kind, card.source_ref].filter(Boolean).join(" / ")}</p>}
          {card.evidence_strength && <p>evidence: {card.evidence_strength}</p>}
          {card.supporting_paper_ids.length > 0 && <p>supporting papers: {card.supporting_paper_ids.map((id) => id.slice(0, 10)).join(", ")}</p>}
          {card.quality_flags.length > 0 && <p>flags: {card.quality_flags.join(", ")}</p>}
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {card.tags.split(",").map((tag) => tag.trim()).filter(Boolean).map((tag) => (
          <span key={tag} className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">{tag}</span>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button onClick={() => onStatus(card, "verified")} className="rounded-lg border border-border px-2.5 py-1.5 text-xs hover:bg-muted">确认</button>
        <button onClick={() => onStatus(card, "rejected")} className="rounded-lg border border-border px-2.5 py-1.5 text-xs hover:bg-muted">废弃</button>
        {SECTION_HINTS.map((hint) => (
          <button
            key={hint}
            onClick={() => onSnippet(card, hint)}
            disabled={card.status === "rejected" || card.status === "merged"}
            className="rounded-lg border border-border px-2.5 py-1.5 text-xs hover:bg-muted disabled:opacity-40"
          >
            加入 {hint}
          </button>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <select value={mergeTarget} onChange={(e) => onMergeTargetChange(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-border bg-background px-2 py-2 text-sm">
          <option value="">合并到...</option>
          {cards.filter((item) => item.card_id !== card.card_id && item.status !== "merged").map((item) => (
            <option key={item.card_id} value={item.card_id}>{item.title}</option>
          ))}
        </select>
        <button onClick={() => onMerge(card)} disabled={!mergeTarget} className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50">
          合并
        </button>
      </div>
    </article>
  );
}
