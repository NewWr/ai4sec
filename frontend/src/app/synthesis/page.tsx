"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getPapersDiscovery, listKnowledgeCards, updateDiscoveryGapStatus, updateDiscoveryRelationStatus } from "@/lib/api";
import type { DiscoveryEdge, DiscoveryGap, DiscoveryGapStatusRequest, DiscoveryRelationStatus, KnowledgeCard, PapersDiscovery } from "@/lib/types";

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function SynthesisPage() {
  const [discovery, setDiscovery] = useState<PapersDiscovery | null>(null);
  const [cards, setCards] = useState<KnowledgeCard[]>([]);
  const [detailGap, setDetailGap] = useState<DiscoveryGap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextDiscovery, synthesisCards] = await Promise.all([
        getPapersDiscovery(200),
        listKnowledgeCards({ assetLevel: "synthesis", status: "verified", limit: 100 }),
      ]);
      setDiscovery(nextDiscovery);
      setCards(synthesisCards);
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

  const conflicts = useMemo(
    () => (discovery?.edges || []).filter((edge) => edge.relation.includes("冲突") || edge.relation === "conflicting_claim"),
    [discovery],
  );

  const gaps = discovery?.gaps || [];

  const setRelationStatus = async (edge: DiscoveryEdge, status: DiscoveryRelationStatus) => {
    if (!edge.relation_id) return;
    try {
      setDiscovery(await updateDiscoveryRelationStatus(edge.relation_id, { status }));
    } catch (err) {
      setError(errMessage(err));
    }
  };

  const setGapStatus = async (gap: DiscoveryGap, status: DiscoveryGapStatusRequest["status"]) => {
    try {
      setDiscovery(await updateDiscoveryGapStatus(gap.gap_id, { status, rejection_reason: status === "rejected" ? "Rejected from synthesis board" : "" }));
    } catch (err) {
      setError(errMessage(err));
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-5 py-8">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">综合与想法</h1>
          <p className="mt-1 text-sm text-muted-foreground">跨论文综合卡、冲突关系和研究 gap 候选。</p>
        </div>
        <button onClick={load} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">刷新综合</button>
      </div>
      {error && <p className="mb-4 rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">加载中...</div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
          <section className="rounded-xl border border-border bg-card p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">综合卡</h2>
              <Link href="/knowledge?asset_level=synthesis&status=verified" className="text-xs text-primary hover:underline">查看卡片列表</Link>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {cards.map((card) => (
                <article key={card.card_id} className="rounded-lg border border-border bg-background p-3">
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    <span className="rounded-full bg-success/10 px-2 py-0.5 text-success">{card.synthesis_type || "synthesis"}</span>
                    <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">{card.evidence_strength || "multi-paper"}</span>
                    <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">{card.supporting_paper_ids.length} papers</span>
                  </div>
                  <h3 className="mt-2 text-sm font-semibold">{card.title}</h3>
                  <p className="mt-2 line-clamp-4 text-sm leading-6 text-muted-foreground">{card.content}</p>
                  <p className="mt-2 text-xs text-muted-foreground">supporting cards: {card.supporting_card_ids.length}</p>
                </article>
              ))}
              {!cards.length && <p className="py-10 text-center text-sm text-muted-foreground md:col-span-2">暂无综合卡。</p>}
            </div>
          </section>

          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-3 text-sm font-semibold">冲突看板</h2>
            <div className="space-y-3">
              {conflicts.map((edge) => (
                <article key={edge.relation_id || `${edge.source}-${edge.target}`} className="rounded-lg border border-border bg-background p-3">
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-destructive">{edge.relation}</span>
                    <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">{edge.status}</span>
                    {edge.verifier_version && <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">{edge.verifier_version}</span>}
                    <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">conf {edge.confidence.toFixed(2)}</span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{edge.evidence.join(" / ")}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                    <Link href={`/papers#paper-${edge.source}`} className="rounded-full border border-border px-2 py-0.5 hover:bg-muted">源论文</Link>
                    <Link href={`/papers#paper-${edge.target}`} className="rounded-full border border-border px-2 py-0.5 hover:bg-muted">目标论文</Link>
                    {[...edge.source_evidence_ids, ...edge.target_evidence_ids].slice(0, 6).map((evidenceId) => (
                      <span key={evidenceId} className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">evidence {evidenceId.slice(0, 8)}</span>
                    ))}
                  </div>
                  {edge.negative_checks.length > 0 && (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">存疑：{edge.negative_checks.slice(0, 2).join(" / ")}</p>
                  )}
                  {edge.comparability_json && Object.keys(edge.comparability_json).length > 0 && (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      comparability: {["task", "dataset", "metric", "setting", "claim_direction", "verdict"]
                        .map((key) => `${key}=${String(edge.comparability_json[key] ?? "")}`)
                        .join(" / ")}
                    </p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button onClick={() => setRelationStatus(edge, "confirmed")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">确认</button>
                    <button onClick={() => setRelationStatus(edge, "verified")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">验证</button>
                    <button onClick={() => setRelationStatus(edge, "needs_more_evidence")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">需证据</button>
                    <button onClick={() => setRelationStatus(edge, "rejected")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">忽略</button>
                  </div>
                </article>
              ))}
              {!conflicts.length && <p className="py-10 text-center text-sm text-muted-foreground">暂无冲突关系。</p>}
            </div>
          </section>

          <section className="rounded-xl border border-border bg-card p-4 xl:col-span-2">
            <h2 className="mb-3 text-sm font-semibold">想法看板</h2>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {gaps.map((gap) => (
                <GapCard
                  key={gap.gap_id}
                  gap={gap}
                  onOpen={() => setDetailGap(gap)}
                  onStatus={setGapStatus}
                />
              ))}
              {!gaps.length && <p className="py-10 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">暂无 gap 候选。</p>}
            </div>
          </section>
        </div>
      )}
      {detailGap && (
        <GapDetailDialog
          gap={detailGap}
          onClose={() => setDetailGap(null)}
          onStatus={setGapStatus}
        />
      )}
    </div>
  );
}

function GapCard({
  gap,
  onOpen,
  onStatus,
}: {
  gap: DiscoveryGap;
  onOpen: () => void;
  onStatus: (gap: DiscoveryGap, status: DiscoveryGapStatusRequest["status"]) => void;
}) {
  return (
    <article id={`gap-${gap.gap_id}`} className="scroll-mt-20 rounded-lg border border-border bg-background p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap gap-1.5 text-xs">
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary">{gap.status}</span>
          <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">novel {gap.scores.novelty.toFixed(2)}</span>
          <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">feasible {gap.scores.feasibility.toFixed(2)}</span>
          {gap.hit_by_paper_ids.length > 0 && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
              hit {gap.hit_by_paper_ids.length}
            </span>
          )}
        </div>
        <button
          onClick={onOpen}
          className="shrink-0 rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted"
        >
          放大查看
        </button>
      </div>
      <h3 className="mt-2 text-sm font-semibold">{gap.title}</h3>
      <p className="mt-2 line-clamp-4 text-sm leading-6 text-muted-foreground">{gap.description || gap.hypothesis}</p>
      {gap.research_question && <p className="mt-2 text-xs leading-5 text-muted-foreground">question: {gap.research_question}</p>}
      {gap.target_task && <p className="mt-1 text-xs leading-5 text-muted-foreground">task: {gap.target_task}</p>}
      {gap.baseline_plan && <p className="mt-1 text-xs leading-5 text-muted-foreground">baseline: {gap.baseline_plan}</p>}
      {gap.contribution && <p className="mt-1 text-xs leading-5 text-muted-foreground">contribution: {gap.contribution}</p>}
      {gap.minimum_experiment && <p className="mt-2 text-xs leading-5 text-muted-foreground">min exp: {gap.minimum_experiment}</p>}
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        trace: {gap.support_evidence_ids.length} support / {gap.counter_evidence_ids.length} counter / {gap.related_card_ids.length} cards / {gap.related_synthesis_card_ids.length} synthesis / {gap.history_json.length} history
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button onClick={() => onStatus(gap, "reviewing")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">复核</button>
        <button onClick={() => onStatus(gap, "pursue")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">追踪</button>
        <button onClick={() => onStatus(gap, "experiment_planned")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">实验计划</button>
        <button onClick={() => onStatus(gap, "needs_more_evidence")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">需证据</button>
        <button onClick={() => onStatus(gap, "promoted_to_idea")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">推进</button>
        <button onClick={() => onStatus(gap, "covered")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">已覆盖</button>
        <button onClick={() => onStatus(gap, "rejected")} className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">忽略</button>
      </div>
    </article>
  );
}

function GapDetailDialog({
  gap,
  onClose,
  onStatus,
}: {
  gap: DiscoveryGap;
  onClose: () => void;
  onStatus: (gap: DiscoveryGap, status: DiscoveryGapStatusRequest["status"]) => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const updateStatus = (status: DiscoveryGapStatusRequest["status"]) => {
    onStatus(gap, status);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4 py-6" onClick={onClose}>
      <div
        className="flex max-h-[88vh] w-full max-w-4xl flex-col rounded-xl border border-border bg-card shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap gap-1.5 text-xs">
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary">{gap.status}</span>
              <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">coverage {gap.coverage_status || "unknown"}</span>
              <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">v{gap.gap_version}</span>
            </div>
            <h2 className="mt-2 break-words text-lg font-semibold">{gap.title || "未命名想法"}</h2>
            <p className="mt-1 break-all text-xs text-muted-foreground">{gap.gap_id}</p>
          </div>
          <button onClick={onClose} className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">
            关闭
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          <div className="grid gap-3 md:grid-cols-3">
            <ScoreItem label="novelty" value={gap.scores.novelty} />
            <ScoreItem label="feasibility" value={gap.scores.feasibility} />
            <ScoreItem label="evidence" value={gap.scores.evidence_strength} />
            <ScoreItem label="risk" value={gap.scores.risk} />
            <ScoreItem label="experiment cost" value={gap.scores.experiment_cost} />
            <ScoreItem label="domain value" value={gap.scores.domain_value} />
          </div>

          <DetailBlock label="完整描述" value={gap.full_description || gap.description} />
          <DetailBlock label="假设" value={gap.hypothesis} />
          <DetailBlock label="研究问题" value={gap.research_question || gap.question} />
          <DetailBlock label="目标任务" value={gap.target_task} />
          <DetailBlock label="约束" value={gap.constraints_json.join(" / ")} />
          <DetailBlock label="Baseline 计划" value={gap.baseline_plan} />
          <DetailBlock label="贡献点" value={gap.contribution} />
          <DetailBlock label="目标 venue" value={gap.target_venue} />
          <DetailBlock label="最小实验" value={gap.minimum_experiment} />
          {gap.rejection_reason && <DetailBlock label="拒绝原因" value={gap.rejection_reason} />}

          <IdList label="支撑 evidence" ids={gap.support_evidence_ids} />
          <IdList label="反向 evidence" ids={gap.counter_evidence_ids} />
          <IdList label="相关卡片" ids={gap.related_card_ids} />
          <IdList label="相关综合卡" ids={gap.related_synthesis_card_ids} />
          <IdList label="命中新论文" ids={gap.hit_by_paper_ids} />
          <IdList label="关联论文" ids={gap.paper_ids} />

          {gap.signals.length > 0 && (
            <div className="mt-4 rounded-lg border border-border bg-background p-3">
              <h3 className="text-xs font-semibold text-muted-foreground">signals</h3>
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                {gap.signals.map((signal) => (
                  <span key={signal} className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">{signal}</span>
                ))}
              </div>
            </div>
          )}

          {gap.history_json.length > 0 && (
            <div className="mt-4 rounded-lg border border-border bg-background p-3">
              <h3 className="text-xs font-semibold text-muted-foreground">历史</h3>
              <div className="mt-2 space-y-2">
                {gap.history_json.map((entry, idx) => (
                  <pre key={idx} className="overflow-auto rounded-md bg-muted p-2 text-xs leading-5 text-muted-foreground">
                    {JSON.stringify(entry, null, 2)}
                  </pre>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-border px-5 py-4">
          <button onClick={() => updateStatus("reviewing")} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">复核</button>
          <button onClick={() => updateStatus("pursue")} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">追踪</button>
          <button onClick={() => updateStatus("experiment_planned")} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">实验计划</button>
          <button onClick={() => updateStatus("needs_more_evidence")} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">需证据</button>
          <button onClick={() => updateStatus("promoted_to_idea")} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">推进</button>
          <button onClick={() => updateStatus("covered")} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">已覆盖</button>
          <button onClick={() => updateStatus("rejected")} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">忽略</button>
        </div>
      </div>
    </div>
  );
}

function ScoreItem({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-semibold">{value.toFixed(2)}</p>
    </div>
  );
}

function DetailBlock({ label, value }: { label: string; value: string }) {
  if (!value.trim()) return null;
  return (
    <div className="mt-4 rounded-lg border border-border bg-background p-3">
      <h3 className="text-xs font-semibold text-muted-foreground">{label}</h3>
      <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">{value}</p>
    </div>
  );
}

function IdList({ label, ids }: { label: string; ids: string[] }) {
  if (!ids.length) return null;
  return (
    <div className="mt-4 rounded-lg border border-border bg-background p-3">
      <h3 className="text-xs font-semibold text-muted-foreground">{label}</h3>
      <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
        {ids.map((id) => (
          <button
            key={id}
            onClick={() => navigator.clipboard?.writeText(id)}
            title={id}
            className="rounded-full border border-border px-2 py-0.5 text-muted-foreground hover:bg-muted"
          >
            {id.length > 14 ? `${id.slice(0, 12)}...` : id}
          </button>
        ))}
      </div>
    </div>
  );
}
