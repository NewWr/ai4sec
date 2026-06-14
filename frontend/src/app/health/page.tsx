"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { fixKnowledgeHealthIssue, getKnowledgeHealth } from "@/lib/api";
import type { KnowledgeHealth, KnowledgeHealthIssue } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { IconWrench, IconRefresh } from "@/components/icons";

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function severityTone(severity: string): string {
  if (severity === "high") return "border-destructive/30 bg-destructive/10 text-destructive";
  if (severity === "medium") return "border-primary/30 bg-primary/10 text-primary";
  return "border-border bg-muted text-muted-foreground";
}

export default function HealthPage() {
  const [health, setHealth] = useState<KnowledgeHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [fixing, setFixing] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setHealth(await getKnowledgeHealth());
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleFix = useCallback(async (issue: KnowledgeHealthIssue) => {
    setFixing(issue.issue_type);
    try {
      const res = await fixKnowledgeHealthIssue({
        issue_type: issue.issue_type,
        paper_ids: issue.paper_ids,
      });
      setMessage(res.message);
      setError("");
      await load();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setFixing("");
    }
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl px-5 py-8">
      <PageHeader
        icon={IconWrench}
        title="知识库维护"
        subtitle="查看解析、同步、元数据、笔记和卡片质量问题。"
        actions={
          <button onClick={load} className="btn btn-outline btn-sm">
            <IconRefresh className="text-base" />
            刷新
          </button>
        }
      />

      {error && <p className="alert alert-error mb-4">{error}</p>}
      {message && <p className="alert alert-info mb-4">{message}</p>}

      {loading || !health ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="skeleton h-[88px]" />
          ))}
        </div>
      ) : (
        <>
          <section className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="论文总数" value={health.total_papers} />
            <Metric label="未解决问题" value={health.unresolved_issues} />
            <Metric label="同步失败" value={health.sync_failed_papers} />
            <Metric label="待重建索引" value={health.stale_index_documents} />
            <Metric label="无证据 verified" value={health.verified_cards_without_evidence} />
            <Metric label="草稿积压" value={health.draft_backlog_count} />
            <Metric label="弱综合卡" value={health.weak_synthesis_cards} />
            <Metric label="Gap 缺实验" value={health.gaps_missing_support_or_experiment} />
            <Metric label="写作缺 trace" value={health.writing_snippets_missing_trace} />
            <Metric label="孤立 evidence" value={health.isolated_evidence_count} />
            <Metric label="本地问答命中率" value={`${Math.round(health.local_qa_graph_hit_ratio * 100)}%`} />
            <Metric label="导出缺引用率" value={`${Math.round(health.export_citation_missing_rate * 100)}%`} />
          </section>

          <section className="grid gap-3 lg:grid-cols-2">
            {health.issues.map((issue) => (
              <article key={issue.issue_type} className={`rounded-xl border p-4 ${severityTone(issue.severity)}`}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold">{issue.label}</h2>
                    <p className="mt-1 text-xs opacity-80">{issue.issue_type}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {canFix(issue.issue_type) && (
                      <button
                        onClick={() => handleFix(issue)}
                        disabled={fixing === issue.issue_type || issue.count === 0}
                        className="rounded-lg border border-current/20 bg-card/60 px-2 py-1 text-xs transition-colors hover:bg-card disabled:opacity-50"
                      >
                        {fixing === issue.issue_type ? "处理中" : fixLabel(issue.issue_type)}
                      </button>
                    )}
                    {actionHref(issue.issue_type) && (
                      <Link
                        href={actionHref(issue.issue_type) || "#"}
                        className="rounded-lg border border-current/20 bg-card/60 px-2 py-1 text-xs transition-colors hover:bg-card"
                      >
                        {actionLabel(issue.issue_type)}
                      </Link>
                    )}
                    <span className="rounded-full bg-card/70 px-2 py-0.5 text-sm font-semibold">{issue.count}</span>
                  </div>
                </div>
                {issue.paper_ids.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {issue.paper_ids.slice(0, 10).map((paperId) => (
                      <Link key={paperId} href={`/papers#paper-${paperId}`} className="rounded-full border border-current/20 px-2 py-0.5 text-xs hover:bg-card/60">
                        {paperId.slice(0, 10)}
                      </Link>
                    ))}
                  </div>
                )}
                {issue.groups.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {issue.groups.slice(0, 5).map((group) => (
                      <div key={`${group.reason}-${group.key}-${group.paper_ids.join("-")}`} className="rounded-lg border border-current/15 bg-card/50 p-2">
                        <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs">
                          <span className="rounded bg-background/70 px-1.5 py-0.5">{group.reason}</span>
                          <span className="opacity-75">{group.key}</span>
                        </div>
                        <p className="line-clamp-2 text-xs leading-5 opacity-90">{group.titles.join(" / ")}</p>
                      </div>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </section>
        </>
      )}
    </div>
  );
}

function canFix(issueType: string): boolean {
  return ["sync_failed", "missing_metadata", "duplicates", "stale_index"].includes(issueType);
}

function fixLabel(issueType: string): string {
  if (issueType === "sync_failed") return "标记重试";
  if (issueType === "missing_metadata") return "补 citation key";
  if (issueType === "duplicates") return "刷新候选";
  if (issueType === "stale_index") return "标记重建";
  return "处理";
}

function actionHref(issueType: string): string {
  if (issueType === "pending_ai_cards") return "/knowledge?status=draft";
  if (issueType === "read_without_notes") return "/papers";
  if (issueType === "reading_without_cards") return "/knowledge";
  if (issueType === "unparsed") return "/papers";
  return "";
}

function actionLabel(issueType: string): string {
  if (issueType === "pending_ai_cards") return "去审核";
  if (issueType === "read_without_notes") return "去补笔记";
  if (issueType === "reading_without_cards") return "去建卡片";
  if (issueType === "unparsed") return "查看论文";
  return "查看";
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="surface-card lift soft-shadow p-4">
      <div className="text-2xl font-semibold tracking-tight">{value}</div>
      <div className="mt-1 text-sm text-muted-foreground">{label}</div>
    </div>
  );
}
