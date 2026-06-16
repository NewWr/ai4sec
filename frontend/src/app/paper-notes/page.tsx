"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import MarkdownRenderer from "@/components/MarkdownRenderer";
import { PageContainer } from "@/components/PageContainer";
import { PageHeader } from "@/components/PageHeader";
import { IconRefresh, IconSearch, IconSparkles } from "@/components/icons";
import {
  addPaperNoteToDaily,
  generatePaperNoteCards,
  getExternalPaperNote,
  getPaperNotesSync,
  listPaperNoteFacets,
  listPaperNotes,
  promotePaperNote,
  refreshPaperNoteScore,
  startPaperNoteRun,
  syncPaperNoteToSpace,
  syncPaperNotes,
  updatePaperNoteStatus,
} from "@/lib/api";
import type {
  ExternalNoteSort,
  ExternalNoteStatus,
  ExternalNoteSyncRun,
  ExternalNoteFacets,
  ExternalPaperNote,
  ExternalPaperNoteListResponse,
  ReadingMode,
} from "@/lib/types";

const PAGE_SIZE = 20;

const STATUS_LABELS: Record<ExternalNoteStatus, string> = {
  new: "新笔记",
  useful: "有用",
  later: "稍后",
  ignored: "已忽略",
  irrelevant: "不相关",
  promoted: "已入库",
  linked: "已关联",
  stale: "过期",
};

const RUN_MODES: ReadingMode[] = ["lens", "snap", "sphere", "auto"];

const RUN_MODE_LABELS: Record<ReadingMode, string> = {
  lens: "结构化精读",
  snap: "快速洞察",
  sphere: "关联脉络",
  auto: "智能问答",
};

const RUN_MODE_HINTS: Record<ReadingMode, string> = {
  lens: "按问题、方法、实验、局限展开精读",
  snap: "快速提取核心结论和阅读价值",
  sphere: "分析相关工作和研究脉络",
  auto: "按当前笔记自动组织综合解读",
};

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function statusTone(status: string): string {
  if (status === "useful" || status === "promoted" || status === "linked") return "chip-success";
  if (status === "ignored" || status === "irrelevant") return "chip-danger";
  if (status === "later") return "chip-warning";
  return "chip-primary";
}

function scoreLabel(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : "0.00";
}

function isExternalPaperNote(value: unknown): value is ExternalPaperNote {
  return Boolean(value && typeof value === "object" && "note_id" in value && "source_path" in value);
}

function isPaperNoteRunResult(value: unknown): value is { note_id: string; paper_id: string; run_id: string; status: string } {
  return Boolean(value && typeof value === "object" && "note_id" in value && "paper_id" in value && "run_id" in value);
}

export default function PaperNotesPage() {
  const [conference, setConference] = useState("");
  const [year, setYear] = useState("");
  const [domain, setDomain] = useState("");
  const [status, setStatus] = useState<ExternalNoteStatus | "">("");
  const [query, setQuery] = useState("");
  const [hasArxiv, setHasArxiv] = useState("");
  const [linked, setLinked] = useState("");
  const [minScore, setMinScore] = useState("0");
  const [sort, setSort] = useState<ExternalNoteSort>("utility");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<ExternalPaperNoteListResponse | null>(null);
  const [facets, setFacets] = useState<ExternalNoteFacets>({ conferences: [], years: [], domains: [] });
  const [selected, setSelected] = useState<ExternalPaperNote | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [acting, setActing] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [syncRun, setSyncRun] = useState<ExternalNoteSyncRun | null>(null);
  const [runMode, setRunMode] = useState<ReadingMode>("lens");
  const [markdownExpanded, setMarkdownExpanded] = useState(false);

  const patchNote = useCallback((note: ExternalPaperNote) => {
    setSelected((prev) => (prev?.note_id === note.note_id ? note : prev));
    setData((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        items: prev.items.map((item) => (
          item.note_id === note.note_id
            ? { ...item, ...note, markdown: item.markdown }
            : item
        )),
      };
    });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await listPaperNotes({
        conference,
        year: year ? Number(year) : undefined,
        domain,
        status,
        q: query,
        has_arxiv: hasArxiv === "" ? null : hasArxiv === "yes",
        linked: linked === "" ? null : linked === "yes",
        min_score: Number(minScore || 0),
        sort,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setData(next);
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setLoading(false);
    }
  }, [conference, domain, hasArxiv, linked, minScore, page, query, sort, status, year]);

  const selectItem = useCallback(async (noteId: string) => {
    if (selected?.note_id === noteId) return;
    setDetailLoading(true);
    try {
      setSelected(await getExternalPaperNote(noteId));
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setDetailLoading(false);
    }
  }, [selected?.note_id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    listPaperNoteFacets()
      .then(setFacets)
      .catch((err) => setError(errMessage(err)));
  }, []);

  useEffect(() => {
    setPage(0);
  }, [conference, domain, hasArxiv, linked, minScore, query, sort, status, year]);

  useEffect(() => {
    if (!syncRun?.sync_id || ["done", "failed", "partial"].includes(syncRun.status)) return;
    let cancelled = false;
    const id = setInterval(() => {
      getPaperNotesSync(syncRun.sync_id)
        .then((job) => {
          if (cancelled) return;
          setSyncRun(job);
          if (["done", "partial"].includes(job.status)) {
            setMessage(`同步完成：新增 ${job.inserted}，更新 ${job.updated}，失败 ${job.failed}`);
            void load();
            void listPaperNoteFacets().then(setFacets);
          } else if (job.status === "failed") {
            setError("同步失败");
          }
        })
        .catch((err) => {
          if (!cancelled) setError(errMessage(err));
        });
    }, 2500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [load, syncRun?.status, syncRun?.sync_id]);

  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageStart = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const pageEnd = Math.min(total, page * PAGE_SIZE + (data?.items.length || 0));

  const selectedMatches = useMemo(() => selected?.matches || [], [selected]);

  const startSync = useCallback(async () => {
    setError("");
    setMessage("");
    try {
      const job = await syncPaperNotes({ force: false });
      setSyncRun(job);
      setMessage(`同步任务已启动：${job.sync_id}`);
    } catch (err) {
      setError(errMessage(err));
    }
  }, []);

  const act = useCallback(async (note: ExternalPaperNote, action: string, fn: () => Promise<unknown>, done: string) => {
    setActing((prev) => ({ ...prev, [note.note_id]: action }));
    try {
      const result = await fn();
      if (isExternalPaperNote(result)) {
        patchNote(result);
      } else if (isPaperNoteRunResult(result)) {
        const updated = await getExternalPaperNote(result.note_id);
        patchNote({
          ...updated,
          linked_paper_id: result.paper_id || updated.linked_paper_id,
          linked_run_id: result.run_id || updated.linked_run_id,
        });
      } else if (action === "promote" || action === "run" || action === "daily" || action === "space" || action === "cards") {
        patchNote(await getExternalPaperNote(note.note_id));
      }
      setMessage(done);
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setActing((prev) => ({ ...prev, [note.note_id]: "" }));
    }
  }, [patchNote]);

  return (
    <PageContainer size="wide">
      <PageHeader
        icon={IconSearch}
        title="外部顶会论文雷达"
        subtitle="Paper-Notes 外部公开笔记默认保持来源隔离，确认后再进入本地论文库、解读流程或外部笔记知识库。"
        actions={
          <button
            onClick={startSync}
            disabled={Boolean(syncRun?.sync_id && !["done", "failed", "partial"].includes(syncRun.status))}
            className="btn btn-primary"
          >
            <IconRefresh className="text-base" />
            {syncRun?.sync_id && !["done", "failed", "partial"].includes(syncRun.status) ? "同步中" : "立即同步"}
          </button>
        }
      />

      {error && <p className="alert alert-error mb-4">{error}</p>}
      {message && <p className="alert alert-info mb-4">{message}</p>}
      {(syncRun || data?.latest_sync) && (
        <p className="alert mb-4 text-muted-foreground">
          同步状态 {(syncRun || data?.latest_sync)?.status}，扫描 {(syncRun || data?.latest_sync)?.scanned || 0}，新增 {(syncRun || data?.latest_sync)?.inserted || 0}，更新 {(syncRun || data?.latest_sync)?.updated || 0}，失败 {(syncRun || data?.latest_sync)?.failed || 0}
        </p>
      )}

      <section className="mb-4 grid gap-3 surface-card p-3 soft-shadow lg:grid-cols-[150px_120px_180px_150px_120px_120px_110px_120px_1fr]">
        <select value={conference} onChange={(e) => setConference(e.target.value)} className="field">
          <option value="">全部会议</option>
          {facets.conferences.map((item) => (
            <option key={String(item.value)} value={String(item.value)}>
              {String(item.value)} ({item.count})
            </option>
          ))}
        </select>
        <select value={year} onChange={(e) => setYear(e.target.value)} className="field">
          <option value="">全部年份</option>
          {facets.years.map((item) => (
            <option key={String(item.value)} value={String(item.value)}>
              {String(item.value)} ({item.count})
            </option>
          ))}
        </select>
        <select value={domain} onChange={(e) => setDomain(e.target.value)} className="field">
          <option value="">全部领域</option>
          {facets.domains.map((item) => (
            <option key={String(item.value)} value={String(item.value)}>
              {String(item.value)} ({item.count})
            </option>
          ))}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value as ExternalNoteStatus | "")} className="field">
          <option value="">全部状态</option>
          {Object.entries(STATUS_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        <select value={hasArxiv} onChange={(e) => setHasArxiv(e.target.value)} className="field">
          <option value="">arXiv</option>
          <option value="yes">有 arXiv</option>
          <option value="no">无 arXiv</option>
        </select>
        <select value={linked} onChange={(e) => setLinked(e.target.value)} className="field">
          <option value="">入库</option>
          <option value="yes">已入库</option>
          <option value="no">未入库</option>
        </select>
        <input value={minScore} onChange={(e) => setMinScore(e.target.value)} placeholder="最低分" inputMode="decimal" className="field" />
        <select value={sort} onChange={(e) => setSort(e.target.value as ExternalNoteSort)} className="field">
          <option value="utility">有用分</option>
          <option value="updated">更新时间</option>
          <option value="conference">会议</option>
          <option value="year">年份</option>
        </select>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索标题、摘要、arXiv、代码链接" className="field" />
      </section>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
        <span>共 {total} 条，当前 {pageStart}-{pageEnd}，第 {page + 1}/{totalPages} 页</span>
        <div className="flex items-center gap-2">
          <button onClick={() => setPage((prev) => Math.max(0, prev - 1))} disabled={loading || page === 0} className="btn btn-outline btn-sm">上一页</button>
          <button onClick={() => setPage((prev) => prev + 1)} disabled={loading || !data?.has_more} className="btn btn-outline btn-sm">下一页</button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,480px)]">
        <section className="space-y-3">
          {loading ? (
            <div className="py-16 text-center text-sm text-muted-foreground">加载中...</div>
          ) : !data?.items.length ? (
            <div className="surface-card p-8 text-center text-sm text-muted-foreground">暂无外部笔记。点击立即同步开始拉取 Paper-Notes。</div>
          ) : (
            data.items.map((item) => {
              const busy = Boolean(acting[item.note_id]);
              const active = selected?.note_id === item.note_id;
              return (
                <article
                  key={item.note_id}
                  className={`surface-card p-4 soft-shadow transition-colors ${active ? "border-primary/60" : ""}`}
                >
                  <button onClick={() => selectItem(item.note_id)} className="block w-full text-left">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap gap-1.5 text-xs">
                        <span className={`chip ${statusTone(item.status)}`}>{STATUS_LABELS[item.status] || item.status}</span>
                        <span className="chip">{item.conference || "-"} {item.year || ""}</span>
                        {item.domain && <span className="chip">{item.domain}</span>}
                        <span className="chip chip-primary">score {scoreLabel(item.utility_score)}</span>
                        {item.sync_status !== "not_synced" && <span className="chip">{item.sync_status}</span>}
                      </div>
                      <div className="flex flex-wrap gap-1.5 text-xs">
                        {item.arxiv_url && <a href={item.arxiv_url} target="_blank" rel="noreferrer" className="btn btn-outline btn-sm" onClick={(e) => e.stopPropagation()}>arXiv</a>}
                        {item.code_url && <a href={item.code_url} target="_blank" rel="noreferrer" className="btn btn-outline btn-sm" onClick={(e) => e.stopPropagation()}>Code</a>}
                        {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer" className="btn btn-outline btn-sm" onClick={(e) => e.stopPropagation()}>Source</a>}
                      </div>
                    </div>
                    <h2 className="text-base font-semibold leading-snug">{item.title_zh || item.title || item.source_path}</h2>
                    {item.title_zh && <p className="mt-1 text-sm leading-snug text-muted-foreground">{item.title}</p>}
                    {item.utility_reason && <p className="mt-2 text-sm leading-6 text-primary">{item.utility_reason}</p>}
                    <p className="mt-2 line-clamp-3 text-sm leading-6 text-muted-foreground">{item.summary || item.method || item.source_path}</p>
                  </button>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button disabled={busy} onClick={() => act(item, "useful", () => updatePaperNoteStatus(item.note_id, { status: "useful" }), "已标记有用。")} className="btn btn-outline-success btn-sm">有用</button>
                    <button disabled={busy} onClick={() => act(item, "later", () => updatePaperNoteStatus(item.note_id, { status: "later" }), "已标记稍后处理。")} className="btn btn-outline btn-sm">稍后</button>
                    <button disabled={busy} onClick={() => act(item, "ignored", () => updatePaperNoteStatus(item.note_id, { status: "ignored" }), "已忽略。")} className="btn btn-ghost btn-sm">忽略</button>
                    <button disabled={busy || Boolean(item.linked_paper_id)} onClick={() => act(item, "promote", () => promotePaperNote(item.note_id), "已入库。")} className="btn btn-primary btn-sm">{acting[item.note_id] === "promote" ? "入库中" : "入库"}</button>
                    <button disabled={busy} onClick={() => act(item, "score", () => refreshPaperNoteScore(item.note_id), "已刷新评分。")} className="btn btn-outline btn-sm">刷新评分</button>
                  </div>
                </article>
              );
            })
          )}
        </section>

        <aside className="surface-card p-4 xl:sticky xl:top-20 xl:max-h-[calc(100vh-6rem)] xl:overflow-y-auto">
          {!selected ? (
            <div className="py-16 text-center text-sm text-muted-foreground">选择一条外部笔记查看详情。</div>
          ) : (
            <div>
              {detailLoading && (
                <div className="mb-3 rounded-lg border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
                  正在加载当前笔记详情...
                </div>
              )}
              <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
                <span className={`chip ${statusTone(selected.status)}`}>{STATUS_LABELS[selected.status] || selected.status}</span>
                <span className="chip">{selected.conference || "-"} {selected.year || ""}</span>
                <span className="chip chip-primary">score {scoreLabel(selected.utility_score)}</span>
              </div>
              <h2 className="text-lg font-semibold leading-snug">{selected.title_zh || selected.title}</h2>
              {selected.title_zh && <p className="mt-1 text-sm text-muted-foreground">{selected.title}</p>}
              <p className="mt-3 rounded-lg border border-primary/15 bg-primary/5 p-3 text-sm leading-6 text-primary">
                {selected.utility_reason || "暂无评分解释。"}
              </p>

              <div className="mt-4 grid gap-2 text-sm">
                {selected.linked_paper_id && <Link href={`/papers#paper-${selected.linked_paper_id}`} className="btn btn-outline-success btn-sm">打开本地论文</Link>}
                {selected.linked_run_id && <Link href={`/paper/${selected.linked_paper_id}/run/${selected.linked_run_id}`} className="btn btn-outline btn-sm">打开解读结果</Link>}
                <div className="flex gap-2">
                  <select value={runMode} onChange={(e) => setRunMode(e.target.value as ReadingMode)} className="field field-sm flex-1">
                    {RUN_MODES.map((mode) => (
                      <option key={mode} value={mode}>
                        {RUN_MODE_LABELS[mode]}
                      </option>
                    ))}
                  </select>
                  <button
                    disabled={Boolean(acting[selected.note_id])}
                    title={selected.linked_paper_id ? RUN_MODE_HINTS[runMode] : "未入库时会先入库，再启动中文解读"}
                    onClick={() => act(
                      selected,
                      "run",
                      () => startPaperNoteRun(selected.note_id, {
                        mode: runMode,
                        language: "zh",
                        auto_promote: !selected.linked_paper_id,
                      }),
                      selected.linked_paper_id ? "已启动中文解读。" : "已入库并启动中文解读。",
                    )}
                    className="btn btn-primary btn-sm"
                  >
                    <IconSparkles className="text-base" />
                    {selected.linked_paper_id ? "启动解读" : "入库并解读"}
                  </button>
                </div>
                <p className="text-xs leading-5 text-muted-foreground">
                  {RUN_MODE_LABELS[runMode]}：{RUN_MODE_HINTS[runMode]}
                </p>
                <button disabled={Boolean(acting[selected.note_id]) || !selected.arxiv_id} onClick={() => act(selected, "daily", () => addPaperNoteToDaily(selected.note_id), "已加入每日推荐候选。")} className="btn btn-outline btn-sm">加入每日推荐</button>
                <button disabled={Boolean(acting[selected.note_id])} onClick={() => act(selected, "space", () => syncPaperNoteToSpace(selected.note_id, { space_id: "external_notes" }), "已同步到外部笔记知识库。")} className="btn btn-outline btn-sm">同步到外部笔记知识库</button>
                <button disabled={Boolean(acting[selected.note_id])} onClick={() => act(selected, "cards", () => generatePaperNoteCards(selected.note_id, { max_cards: 4 }), "已生成候选知识卡片。")} className="btn btn-outline btn-sm">生成卡片</button>
              </div>

              {selectedMatches.length > 0 && (
                <div className="mt-4">
                  <h3 className="text-sm font-semibold">本地关系</h3>
                  <div className="mt-2 space-y-2">
                    {selectedMatches.map((match) => (
                      <div key={match.match_id || `${match.target_kind}-${match.target_id}`} className="rounded-lg border border-border bg-background p-2 text-xs leading-5">
                        <div className="font-medium">{match.target_kind} / {match.match_type} / {match.confidence.toFixed(2)}</div>
                        <div className="text-muted-foreground">{match.reason || match.target_id}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-4 border-t border-border pt-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold">Markdown 预览</span>
                  <button
                    onClick={() => setMarkdownExpanded(true)}
                    className="btn btn-outline btn-sm"
                  >
                    放大查看
                  </button>
                </div>
                <div className="max-h-[520px] overflow-y-auto rounded-lg border border-border bg-background p-3">
                  <MarkdownRenderer content={selected.markdown || ""} softMathErrors />
                </div>
              </div>
            </div>
          )}
        </aside>
      </div>
      {selected && markdownExpanded && (
        <div className="modal-overlay">
          <div className="flex max-h-[92vh] w-full max-w-6xl flex-col surface-card p-4 shadow-xl">
            <div className="mb-3 flex items-start justify-between gap-3 border-b border-border pb-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold">{selected.title_zh || selected.title || "Markdown 预览"}</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {selected.conference || "-"} {selected.year || ""} / {selected.domain || "-"}
                </p>
              </div>
              <button onClick={() => setMarkdownExpanded(false)} className="btn btn-outline btn-sm">
                关闭
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-border bg-background p-4">
              <MarkdownRenderer content={selected.markdown || ""} softMathErrors />
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
