"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getDailyRefreshStatus,
  ingestDailyRecommendation,
  listDailyRecommendations,
  promoteDailyRecommendation,
  refreshDailyRecommendations,
  updateDailyRecommendationFeedback,
} from "@/lib/api";
import type {
  DailyRecommendationItem,
  DailyRecommendationListResponse,
  DailyRecommendationRefreshResponse,
  DailyRecommendationStatus,
  DailyRecommendationTopic,
  ReadingMode,
} from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { PageContainer } from "@/components/PageContainer";
import { IconSparkles, IconRefresh } from "@/components/icons";

const PAGE_SIZE = 20;

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    candidate: "候选",
    interested: "感兴趣",
    irrelevant: "不相关",
    dismissed: "已忽略",
    ingesting: "入库中",
    ingested: "已入库",
    ingest_failed: "入库失败",
  };
  return labels[status] || status;
}

function statusTone(status: string): string {
  if (status === "ingested" || status === "interested") return "chip-success";
  if (status === "irrelevant" || status === "ingest_failed") return "chip-danger";
  if (status === "dismissed") return "chip-muted";
  return "chip-primary";
}

function topicName(topic?: DailyRecommendationTopic): string {
  if (!topic) return "";
  return topic.name_zh || topic.name || topic.topic_id;
}

function shortAuthors(authors: string[]): string {
  if (!authors.length) return "";
  if (authors.length <= 3) return authors.join(", ");
  return `${authors.slice(0, 3).join(", ")} 等`;
}

function translationHint(item: DailyRecommendationItem): string {
  const parts = [];
  if (item.title_translation_status && item.title_translation_status !== "done") {
    parts.push(`标题 ${item.title_translation_status}`);
  }
  if (item.abstract_translation_status && item.abstract_translation_status !== "done") {
    parts.push(`摘要 ${item.abstract_translation_status}`);
  }
  return parts.join(" / ");
}

function scoreTags(item: DailyRecommendationItem): string[] {
  const behavior = (item.score_detail.matched_behavior || []).slice(0, 4);
  return behavior.map((term) => String(term)).filter(Boolean);
}

const PARSE_OPTIONS: Array<{ value: ReadingMode; label: string; desc: string }> = [
  { value: "lens", label: "Lens", desc: "结构化精读，适合判断是否值得深入阅读" },
  { value: "snap", label: "Snap", desc: "快速洞察，适合先获取核心结论" },
  { value: "sphere", label: "Sphere", desc: "扩展关联，适合追踪研究脉络" },
  { value: "auto", label: "Auto", desc: "综合问答式解读，适合不确定分析入口时使用" },
];

type IngestDraft = {
  item: DailyRecommendationItem;
  parseMode: ReadingMode;
  sourceOnly: boolean;
};

export default function DailyRecommendationsPage() {
  const [date, setDate] = useState("");
  const [topicId, setTopicId] = useState("");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<DailyRecommendationListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [ingestDraft, setIngestDraft] = useState<IngestDraft | null>(null);
  const [refreshJob, setRefreshJob] = useState<DailyRecommendationRefreshResponse | null>(null);

  const topicById = useMemo(() => {
    const map = new Map<string, DailyRecommendationTopic>();
    for (const topic of data?.topics || []) map.set(topic.topic_id, topic);
    return map;
  }, [data]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await listDailyRecommendations({
        date: date || undefined,
        topic_id: topicId,
        status,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }));
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setLoading(false);
    }
  }, [date, page, status, topicId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setPage(0);
  }, [date, status, topicId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const items = data?.items || [];
    if (!q) return items;
    return items.filter((item) => {
      const haystack = [
        item.title_en,
        item.title_zh,
        item.abstract_en,
        item.abstract_zh,
        item.arxiv_id,
        item.primary_category,
        item.reason,
      ].join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }, [data, query]);

  const feedback = useCallback(async (item: DailyRecommendationItem, action: "interested" | "irrelevant" | "dismissed") => {
    setActing((prev) => ({ ...prev, [item.item_id]: action }));
    try {
      await updateDailyRecommendationFeedback(item.item_id, { action });
      setMessage(action === "interested" ? "已标记感兴趣。" : action === "irrelevant" ? "已标记不相关。" : "已忽略。");
      setError("");
      await load();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setActing((prev) => ({ ...prev, [item.item_id]: "" }));
    }
  }, [load]);

  const ingest = useCallback(async () => {
    if (!ingestDraft) return;
    const item = ingestDraft.item;
    setActing((prev) => ({ ...prev, [item.item_id]: "ingest" }));
    try {
      const res = await ingestDailyRecommendation(item.item_id, {
        parse_mode: ingestDraft.parseMode,
        language: "zh",
        source_space_id: "daily_source",
        analysis_space_id: "daily_analysis",
        sync_to_dify: true,
        ingest_source_only: ingestDraft.sourceOnly,
        start_run: !ingestDraft.sourceOnly,
      });
      setMessage(res.run_id ? `已入库并开始 ${ingestDraft.parseMode} 解读：${res.run_id}` : "已入库原文。");
      setError("");
      setIngestDraft(null);
      await load();
    } catch (err) {
      setError(errMessage(err));
      await load();
    } finally {
      setActing((prev) => ({ ...prev, [item.item_id]: "" }));
    }
  }, [ingestDraft, load]);

  const promote = useCallback(async (item: DailyRecommendationItem) => {
    setActing((prev) => ({ ...prev, [item.item_id]: "promote" }));
    try {
      await promoteDailyRecommendation(item.item_id, {
        source_target_space_id: "main_source",
        analysis_target_space_id: "main_analysis",
        copy: true,
      });
      setMessage("已复制到主研究知识库。");
      setError("");
      await load();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setActing((prev) => ({ ...prev, [item.item_id]: "" }));
    }
  }, [load]);

  const startRefresh = useCallback(async () => {
    setError("");
    setMessage("");
    try {
      const job = await refreshDailyRecommendations({
        date: date || undefined,
        topic_id: topicId || undefined,
        force: true,
      });
      setRefreshJob(job);
      setMessage(`刷新任务已启动：${job.job_id}`);
    } catch (err) {
      setError(errMessage(err));
    }
  }, [date, topicId]);

  useEffect(() => {
    if (!refreshJob?.job_id || ["done", "failed"].includes(refreshJob.status)) return;
    let cancelled = false;
    const id = setInterval(() => {
      getDailyRefreshStatus(refreshJob.job_id)
        .then((job) => {
          if (cancelled) return;
          setRefreshJob(job);
          if (job.status === "done") {
            setMessage(`刷新完成：新增或更新 ${job.inserted_or_updated} 篇。`);
            void load();
          } else if (job.status === "failed") {
            setError(job.message || "刷新失败");
          }
        })
        .catch((err) => {
          if (!cancelled) setError(errMessage(err));
        });
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [load, refreshJob?.job_id, refreshJob?.status]);

  const counts = useMemo(() => {
    const ret: Record<DailyRecommendationStatus | "all", number> = {
      all: 0,
      candidate: 0,
      interested: 0,
      irrelevant: 0,
      dismissed: 0,
      ingesting: 0,
      ingested: 0,
      ingest_failed: 0,
    };
    for (const item of data?.items || []) {
      ret.all += 1;
      ret[item.status] = (ret[item.status] || 0) + 1;
    }
    return ret;
  }, [data]);

  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageStart = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const pageEnd = Math.min(total, page * PAGE_SIZE + (data?.items.length || 0));

  return (
    <PageContainer size="wide">
      <PageHeader
        icon={IconSparkles}
        title="每日论文推荐"
        subtitle="默认按推荐日期倒序显示全部论文；系统每天 06:00 自动更新，候选论文需手动选择解析方式后入库。"
        actions={
          <button
            onClick={startRefresh}
            disabled={Boolean(refreshJob?.job_id && !["done", "failed"].includes(refreshJob.status))}
            className="btn btn-primary"
          >
            <IconRefresh className="text-base" />
            {refreshJob?.job_id && !["done", "failed"].includes(refreshJob.status) ? "刷新中" : "立即刷新"}
          </button>
        }
      />

      {error && <p className="alert alert-error mb-4">{error}</p>}
      {message && <p className="alert alert-info mb-4">{message}</p>}
      {refreshJob?.job_id && (
        <p className="alert mb-4 text-muted-foreground">
          刷新任务 {refreshJob.job_id}：{refreshJob.status}，已抓取 {refreshJob.fetched}，新增或更新 {refreshJob.inserted_or_updated}。
        </p>
      )}

      <section className="mb-4 grid gap-3 surface-card p-3 soft-shadow md:grid-cols-[220px_1fr_160px_160px]">
        <div className="flex min-w-0 gap-2">
          <input
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
            className="field min-w-0 flex-1"
            title="按推荐日期筛选；留空显示全部日期"
          />
          {date && (
            <button
              onClick={() => setDate("")}
              className="btn btn-outline btn-sm shrink-0"
            >
              全部
            </button>
          )}
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索当前页标题、摘要、arXiv ID、推荐理由"
          className="field"
        />
        <select
          value={topicId}
          onChange={(event) => setTopicId(event.target.value)}
          className="field"
        >
          <option value="">全部主题</option>
          {(data?.topics || []).map((topic) => (
            <option key={topic.topic_id} value={topic.topic_id}>{topicName(topic)}</option>
          ))}
        </select>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="field"
        >
          <option value="">全部状态 ({counts.all})</option>
          <option value="candidate">候选 ({counts.candidate})</option>
          <option value="interested">感兴趣 ({counts.interested})</option>
          <option value="ingested">已入库 ({counts.ingested})</option>
          <option value="irrelevant">不相关 ({counts.irrelevant})</option>
          <option value="dismissed">已忽略 ({counts.dismissed})</option>
          <option value="ingest_failed">入库失败 ({counts.ingest_failed})</option>
        </select>
      </section>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
        <span>
          共 {total} 篇，当前显示 {pageStart}-{pageEnd}，第 {page + 1}/{totalPages} 页
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPage((prev) => Math.max(0, prev - 1))}
            disabled={loading || page === 0}
            className="rounded-lg border border-border px-3 py-1.5 hover:bg-muted disabled:opacity-50"
          >
            上一页
          </button>
          <button
            onClick={() => setPage((prev) => prev + 1)}
            disabled={loading || !data?.has_more}
            className="rounded-lg border border-border px-3 py-1.5 hover:bg-muted disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      </div>

      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">加载中...</div>
      ) : filtered.length === 0 ? (
        <div className="surface-card p-8 text-center text-sm text-muted-foreground">
          当前筛选条件下没有候选论文。
        </div>
      ) : (
        <section className="space-y-3">
          {filtered.map((item) => {
            const busy = Boolean(acting[item.item_id]);
            const hint = translationHint(item);
            const behaviorTags = scoreTags(item);
            const gapMatches = item.score_detail.matched_gaps || [];
            return (
              <article key={item.item_id} id={`daily-${item.item_id}`} className="surface-card p-4 soft-shadow">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className={`chip ${statusTone(item.status)}`}>{statusLabel(item.status)}</span>
                    <span className="chip">{topicName(topicById.get(item.topic_id)) || item.topic_id}</span>
                    <span className="chip">{item.primary_category}</span>
                    <span className="chip">score {item.score.toFixed(2)}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <a href={item.arxiv_url} target="_blank" rel="noreferrer" className="btn btn-outline btn-sm">arXiv</a>
                    <a href={item.pdf_url} target="_blank" rel="noreferrer" className="btn btn-outline btn-sm">PDF</a>
                    {item.linked_paper_id && (
                      <Link href={`/papers#paper-${item.linked_paper_id}`} className="btn btn-outline-success btn-sm">
                        本地论文
                      </Link>
                    )}
                    {item.linked_run_id && (
                      <Link href={`/paper/${item.linked_paper_id}/run/${item.linked_run_id}`} className="btn btn-outline btn-sm">
                        解读结果
                      </Link>
                    )}
                  </div>
                </div>

                <h2 className="text-base font-semibold leading-snug">{item.title_zh || item.title_en}</h2>
                {item.title_zh && <p className="mt-1 text-sm leading-snug text-muted-foreground">{item.title_en}</p>}
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span>{item.arxiv_id}</span>
                  <span>{shortAuthors(item.authors)}</span>
                  <span>发布 {item.published_at || "-"}</span>
                  <span>更新 {item.updated_at || "-"}</span>
                  {hint && <span>翻译：{hint}</span>}
                </div>

                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                  <div className="rounded-lg border border-border bg-background p-3">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">中文摘要</div>
                    <p className="whitespace-pre-wrap text-sm leading-6">{item.abstract_zh || item.abstract_en}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-3">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">英文摘要</div>
                    <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{item.abstract_en}</p>
                  </div>
                </div>

                <div className="mt-3 rounded-lg border border-primary/15 bg-primary/5 px-3 py-2 text-xs leading-5 text-primary">
                  {item.reason || "规则推荐"}
                </div>

                {(behaviorTags.length > 0 || gapMatches.length > 0) && (
                  <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                    {behaviorTags.map((term) => (
                      <span key={`behavior-${item.item_id}-${term}`} className="chip chip-primary">
                        行为 {term}
                      </span>
                    ))}
                    {gapMatches.map((gap) => (
                      <Link
                        key={`gap-${item.item_id}-${gap.gap_id}`}
                        href={`/synthesis#gap-${gap.gap_id}`}
                        className="chip chip-warning"
                        title={(gap.matched_terms || []).join(", ")}
                      >
                        命中想法 {gap.title || gap.gap_id}
                      </Link>
                    ))}
                  </div>
                )}

                {item.error_msg && (
                  <p className="mt-3 alert alert-error">{item.error_msg}</p>
                )}

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => feedback(item, "interested")}
                    disabled={busy}
                    className="btn btn-outline-success btn-sm"
                  >
                    感兴趣
                  </button>
                  <button
                    onClick={() => feedback(item, "irrelevant")}
                    disabled={busy}
                    className="btn btn-outline-danger btn-sm"
                  >
                    不相关
                  </button>
                  <button
                    onClick={() => feedback(item, "dismissed")}
                    disabled={busy}
                    className="btn btn-ghost btn-sm"
                  >
                    忽略
                  </button>
                  <button
                    onClick={() => setIngestDraft({ item, parseMode: "lens", sourceOnly: false })}
                    disabled={busy || item.status === "ingested" || item.status === "ingesting"}
                    className="btn btn-primary btn-sm"
                  >
                    {acting[item.item_id] === "ingest" ? "处理中" : "选择解析方式"}
                  </button>
                  {item.linked_paper_id && (
                    <button
                      onClick={() => promote(item)}
                      disabled={busy}
                      className="btn btn-outline-primary btn-sm"
                    >
                      {acting[item.item_id] === "promote" ? "转正中" : "转正到主库"}
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </section>
      )}
      {ingestDraft && (
        <div className="modal-overlay">
          <div className="modal-panel max-w-xl p-5">
            <div className="mb-4">
              <h2 className="text-base font-semibold">选择解析方式并入库</h2>
              <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{ingestDraft.item.title_zh || ingestDraft.item.title_en}</p>
            </div>
            <div className="space-y-2">
              {PARSE_OPTIONS.map((option) => (
                <label
                  key={option.value}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2 ${
                    ingestDraft.parseMode === option.value
                      ? "border-primary bg-primary/10"
                      : "border-border bg-background"
                  }`}
                >
                  <input
                    type="radio"
                    name="parse-mode"
                    value={option.value}
                    checked={ingestDraft.parseMode === option.value}
                    onChange={() => setIngestDraft({ ...ingestDraft, parseMode: option.value })}
                    className="mt-1"
                  />
                  <span>
                    <span className="block text-sm font-medium">{option.label}</span>
                    <span className="block text-xs leading-5 text-muted-foreground">{option.desc}</span>
                  </span>
                </label>
              ))}
            </div>
            <label className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={ingestDraft.sourceOnly}
                onChange={(event) => setIngestDraft({ ...ingestDraft, sourceOnly: event.target.checked })}
              />
              只入库原文，不立即解读
            </label>
            <div className="mt-4 rounded-lg border border-border bg-background px-3 py-2 text-xs leading-5 text-muted-foreground">
              原文将进入“每日推荐原文知识库”；解读报告将进入“每日推荐解读知识库”。
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setIngestDraft(null)}
                disabled={Boolean(acting[ingestDraft.item.item_id])}
                className="btn btn-outline"
              >
                取消
              </button>
              <button
                onClick={ingest}
                disabled={Boolean(acting[ingestDraft.item.item_id])}
                className="btn btn-primary"
              >
                {acting[ingestDraft.item.item_id] ? "处理中" : "确认入库"}
              </button>
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
