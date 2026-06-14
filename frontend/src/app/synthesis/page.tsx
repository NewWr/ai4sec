"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getPapersDiscovery,
  getResearchConstructionJob,
  getResearchConstructionState,
  listCanonicalEntities,
  listKnowledgeCards,
  startResearchConstruction,
  updateDiscoveryGapStatus,
  updateDiscoveryRelationStatus,
  updateResearchIdeaFeedback,
} from "@/lib/api";
import { labelFor } from "@/lib/labels";
import type {
  CanonicalEntity,
  DiscoveryEdge,
  DiscoveryGap,
  DiscoveryGapStatusRequest,
  DiscoveryRelationStatus,
  KnowledgeCard,
  PapersDiscovery,
  ResearchConstructionJob,
  ResearchConstructionState,
} from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { PageContainer } from "@/components/PageContainer";
import { IconSphere, IconRefresh } from "@/components/icons";

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function evidenceStrengthLabel(value: string): string {
  if (value === "multi-paper") return "多论文证据";
  return value || "综合";
}

const COMPARABILITY_LABELS: Record<string, string> = {
  task: "任务",
  dataset: "数据集",
  metric: "指标",
  setting: "设置",
  claim_direction: "论点方向",
  verdict: "结论",
};

const ENTITY_TYPE_LABELS: Record<string, string> = {
  method: "方法",
  dataset: "数据集",
  metric: "指标",
  result: "结果",
  limitation: "局限",
};

export default function SynthesisPage() {
  const [discovery, setDiscovery] = useState<PapersDiscovery | null>(null);
  const [cards, setCards] = useState<KnowledgeCard[]>([]);
  const [entities, setEntities] = useState<CanonicalEntity[]>([]);
  const [detailGap, setDetailGap] = useState<DiscoveryGap | null>(null);
  const [constructionState, setConstructionState] = useState<ResearchConstructionState | null>(null);
  const [constructionJob, setConstructionJob] = useState<ResearchConstructionJob | null>(null);
  const [adminToken, setAdminToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [constructing, setConstructing] = useState(false);
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
      getResearchConstructionState().then(setConstructionState).catch(() => undefined);
      listCanonicalEntities({ limit: 100 }).then((res) => setEntities(res.entities)).catch(() => undefined);
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
  const ideaBoard = useMemo(
    () =>
      [...gaps].sort((left, right) => {
        const leftScore = left.scores.novelty * left.scores.feasibility * Math.max(left.scores.domain_value, 0.1);
        const rightScore = right.scores.novelty * right.scores.feasibility * Math.max(right.scores.domain_value, 0.1);
        return rightScore - leftScore;
      }),
    [gaps],
  );

  useEffect(() => {
    if (!constructionJob || !["pending", "running"].includes(constructionJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getResearchConstructionJob(constructionJob.job_id);
        setConstructionJob(nextJob);
        if (!["pending", "running"].includes(nextJob.status)) {
          setConstructing(false);
          await load();
        }
      } catch (err) {
        setError(errMessage(err));
        setConstructing(false);
      }
    }, 1800);
    return () => window.clearInterval(timer);
  }, [constructionJob, load]);

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
      setDiscovery(await updateDiscoveryGapStatus(gap.gap_id, { status, rejection_reason: status === "rejected" ? "从综合看板忽略" : "" }));
    } catch (err) {
      setError(errMessage(err));
    }
  };

  const runConstruction = async (dryRun: boolean) => {
    setConstructing(true);
    try {
      const job = await startResearchConstruction({ dry_run: dryRun, force: !dryRun }, adminToken);
      setConstructionJob(job);
      setConstructionState(await getResearchConstructionState());
      if (dryRun || !["pending", "running"].includes(job.status)) {
        setConstructing(false);
        await load();
      }
      setError("");
    } catch (err) {
      setError(errMessage(err));
      setConstructing(false);
    }
  };

  const setIdeaFeedback = async (gap: DiscoveryGap, verdict: "up" | "down" | "accepted" | "rejected") => {
    try {
      await updateResearchIdeaFeedback(gap.gap_id, { verdict, reason: verdict === "rejected" ? "综合看板反馈" : "" });
      await load();
    } catch (err) {
      setError(errMessage(err));
    }
  };

  return (
    <PageContainer size="wide">
      <PageHeader
        icon={IconSphere}
        title="综合与想法"
        subtitle="跨论文综合卡、冲突关系和研究空白候选。"
        actions={
          <>
            <input
              value={adminToken}
              onChange={(event) => setAdminToken(event.target.value)}
              placeholder="Admin Token"
              className="field field-sm w-36"
            />
            <button onClick={() => runConstruction(true)} disabled={constructing} className="btn btn-outline btn-sm">预算预估</button>
            <button onClick={() => runConstruction(false)} disabled={constructing} className="btn btn-primary btn-sm">立即构建</button>
            <button onClick={load} className="btn btn-outline btn-sm">
              <IconRefresh className="text-base" />
              刷新综合
            </button>
          </>
        }
      />
      {error && <p className="alert alert-error mb-4">{error}</p>}
      <ConstructionPanel state={constructionState} job={constructionJob} />
      {loading ? (
        <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
          <div className="skeleton h-72" />
          <div className="skeleton h-72" />
        </div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
          <section className="surface-card p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">综合卡</h2>
              <Link href="/knowledge?asset_level=synthesis&status=verified" className="text-xs text-primary hover:underline">查看卡片列表</Link>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {cards.map((card) => (
                <article key={card.card_id} className="rounded-lg border border-border bg-background p-3">
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    <span className="chip chip-success">{card.synthesis_type || "综合"}</span>
                    <span className="chip chip-muted">{evidenceStrengthLabel(card.evidence_strength || "multi-paper")}</span>
                    <span className="chip chip-muted">{card.supporting_paper_ids.length} 篇论文</span>
                  </div>
                  <h3 className="mt-2 text-sm font-semibold">{card.title}</h3>
                  <p className="mt-2 line-clamp-4 text-sm leading-6 text-muted-foreground">{card.content}</p>
                  <p className="mt-2 text-xs text-muted-foreground">支撑卡片：{card.supporting_card_ids.length}</p>
                </article>
              ))}
              {!cards.length && <p className="py-10 text-center text-sm text-muted-foreground md:col-span-2">暂无综合卡。</p>}
            </div>
          </section>

          <section className="surface-card p-4">
            <h2 className="mb-3 text-sm font-semibold">冲突看板</h2>
            <div className="space-y-3">
              {conflicts.map((edge) => (
                <article key={edge.relation_id || `${edge.source}-${edge.target}`} className="rounded-lg border border-border bg-background p-3">
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    <span className="chip chip-danger">{labelFor("discoveryRelation", edge.relation)}</span>
                    <span className="chip chip-muted">{labelFor("discoveryRelationStatus", edge.status)}</span>
                    {edge.verifier_version && <span className="chip chip-muted">{edge.verifier_version}</span>}
                    <span className="chip chip-muted">置信度 {edge.confidence.toFixed(2)}</span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{edge.evidence.join(" / ")}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                    <Link href={`/papers#paper-${edge.source}`} className="rounded-full border border-border px-2 py-0.5 hover:bg-muted">源论文</Link>
                    <Link href={`/papers#paper-${edge.target}`} className="rounded-full border border-border px-2 py-0.5 hover:bg-muted">目标论文</Link>
                    {[...edge.source_evidence_ids, ...edge.target_evidence_ids].slice(0, 6).map((evidenceId) => (
                      <span key={evidenceId} className="chip chip-muted">证据 {evidenceId.slice(0, 8)}</span>
                    ))}
                  </div>
                  {edge.negative_checks.length > 0 && (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">存疑：{edge.negative_checks.slice(0, 2).join(" / ")}</p>
                  )}
                  {edge.comparability_json && Object.keys(edge.comparability_json).length > 0 && (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      可比性：{["task", "dataset", "metric", "setting", "claim_direction", "verdict"]
                        .map((key) => `${COMPARABILITY_LABELS[key]}=${String(edge.comparability_json[key] ?? "")}`)
                        .join(" / ")}
                    </p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button onClick={() => setRelationStatus(edge, "confirmed")} className="btn btn-outline btn-sm">确认</button>
                    <button onClick={() => setRelationStatus(edge, "verified")} className="btn btn-outline btn-sm">验证</button>
                    <button onClick={() => setRelationStatus(edge, "needs_more_evidence")} className="btn btn-outline btn-sm">需证据</button>
                    <button onClick={() => setRelationStatus(edge, "rejected")} className="btn btn-outline btn-sm">忽略</button>
                  </div>
                </article>
              ))}
              {!conflicts.length && <p className="py-10 text-center text-sm text-muted-foreground">暂无冲突关系。</p>}
            </div>
          </section>

          <section className="surface-card p-4 xl:col-span-2">
            <h2 className="mb-3 text-sm font-semibold">想法看板</h2>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {ideaBoard.map((gap) => (
                <GapCard
                  key={gap.gap_id}
                  gap={gap}
                  onOpen={() => setDetailGap(gap)}
                  onStatus={setGapStatus}
                  onFeedback={setIdeaFeedback}
                />
              ))}
              {!gaps.length && <p className="py-10 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">暂无研究空白候选。</p>}
            </div>
          </section>

          <section className="surface-card p-4 xl:col-span-2">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">规范实体对比表</h2>
              <span className="text-xs text-muted-foreground">{entities.length} 个规范实体（方法 / 数据集 / 指标，跨论文归并）</span>
            </div>
            {entities.length ? (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="px-2 py-2 font-medium">规范名称</th>
                      <th className="px-2 py-2 font-medium">类型</th>
                      <th className="px-2 py-2 font-medium">别名</th>
                      <th className="px-2 py-2 font-medium">论文数</th>
                      <th className="px-2 py-2 font-medium">引用论文</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entities.map((entity) => (
                      <tr key={entity.entity_id} className="border-b border-border/60 align-top">
                        <td className="px-2 py-2 font-medium">{entity.canonical_name}</td>
                        <td className="px-2 py-2">
                          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                            {ENTITY_TYPE_LABELS[entity.entity_type] || entity.entity_type || "实体"}
                          </span>
                        </td>
                        <td className="px-2 py-2 text-xs text-muted-foreground">{entity.aliases.slice(0, 4).join(" / ") || "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{entity.paper_count}</td>
                        <td className="px-2 py-2 text-xs text-muted-foreground">
                          {entity.mentions
                            .map((mention) => mention.paper_title || mention.paper_id)
                            .filter(Boolean)
                            .slice(0, 4)
                            .join("；") || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="py-10 text-center text-sm text-muted-foreground">暂无规范实体；运行“立即构建”并配置 embedding 后，按方法 / 数据集 / 指标跨论文归并生成。</p>
            )}
          </section>
        </div>
      )}
      {detailGap && (
        <GapDetailDialog
          gap={detailGap}
          onClose={() => setDetailGap(null)}
          onStatus={setGapStatus}
          onFeedback={setIdeaFeedback}
        />
      )}
    </PageContainer>
  );
}

function ConstructionPanel({
  state,
  job,
}: {
  state: ResearchConstructionState | null;
  job: ResearchConstructionJob | null;
}) {
  const estimate = state?.estimate || job?.estimate || {};
  const result = job?.result || {};
  return (
    <div className="mb-5 grid gap-3 surface-card p-4 md:grid-cols-[1.2fr_.8fr]">
      <div>
        <div className="flex flex-wrap gap-1.5 text-xs">
          <span className="chip chip-muted">chat 预估 {String(estimate.estimated_chat_calls ?? "-")}</span>
          <span className="chip chip-muted">embedding 批次 {String(estimate.estimated_embedding_batches ?? "-")}</span>
          <span className="chip chip-muted">候选想法 {String(estimate.candidate_gaps ?? "-")}</span>
          <span className="chip chip-muted">新实体 {String(estimate.new_entity_mentions ?? "-")}</span>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          构建批处理按实体规范化、语义索引、综合、想法、画像顺序执行；未配置 LLM 或 embedding 时自动降级。
        </p>
      </div>
      <div className="rounded-lg border border-border bg-background p-3 text-xs text-muted-foreground">
        {job ? (
          <div className="space-y-1">
            <p className="font-medium text-foreground">批次 {job.job_id}</p>
            <p>状态：{job.status}{job.dry_run ? " / dry-run" : ""}</p>
            {job.error_msg && <p className="text-destructive">{job.error_msg}</p>}
            {Object.keys(result).length > 0 && <p>结果模块：{Object.keys(result).join(" / ")}</p>}
          </div>
        ) : (
          <p>暂无本页启动的构建批次。</p>
        )}
      </div>
    </div>
  );
}

function GapCard({
  gap,
  onOpen,
  onStatus,
  onFeedback,
}: {
  gap: DiscoveryGap;
  onOpen: () => void;
  onStatus: (gap: DiscoveryGap, status: DiscoveryGapStatusRequest["status"]) => void;
  onFeedback: (gap: DiscoveryGap, verdict: "up" | "down" | "accepted" | "rejected") => void;
}) {
  return (
    <article id={`gap-${gap.gap_id}`} className="scroll-mt-20 rounded-lg border border-border bg-background p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap gap-1.5 text-xs">
          <span className="chip chip-primary">{labelFor("gapStatus", gap.status)}</span>
          <span className="chip chip-muted">新颖性 {gap.scores.novelty.toFixed(2)}</span>
          <span className="chip chip-muted">可行性 {gap.scores.feasibility.toFixed(2)}</span>
          {gap.hit_by_paper_ids.length > 0 && (
            <span className="chip chip-warning">
              命中 {gap.hit_by_paper_ids.length}
            </span>
          )}
          {gap.scored_by && (
            <span className="chip chip-muted">{gap.scored_by === "llm" ? "AI 构建" : "启发式"}</span>
          )}
        </div>
        <button
          onClick={onOpen}
          className="shrink-0 btn btn-outline btn-sm"
        >
          放大查看
        </button>
      </div>
      <h3 className="mt-2 text-sm font-semibold">{gap.title}</h3>
      <p className="mt-2 line-clamp-4 text-sm leading-6 text-muted-foreground">{gap.description || gap.hypothesis}</p>
      {gap.research_question && <p className="mt-2 text-xs leading-5 text-muted-foreground">研究问题：{gap.research_question}</p>}
      {gap.target_task && <p className="mt-1 text-xs leading-5 text-muted-foreground">任务：{gap.target_task}</p>}
      {gap.baseline_plan && <p className="mt-1 text-xs leading-5 text-muted-foreground">基线方案：{gap.baseline_plan}</p>}
      {gap.contribution && <p className="mt-1 text-xs leading-5 text-muted-foreground">贡献点：{gap.contribution}</p>}
      {gap.llm_rationale && <p className="mt-1 text-xs leading-5 text-muted-foreground">AI 理由：{gap.llm_rationale}</p>}
      {gap.minimum_experiment && <p className="mt-2 text-xs leading-5 text-muted-foreground">最小实验：{gap.minimum_experiment}</p>}
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        证据链：{gap.support_evidence_ids.length} 条支撑证据 / {gap.counter_evidence_ids.length} 条反向证据 / {gap.related_card_ids.length} 张卡片 / {gap.related_synthesis_card_ids.length} 张综合卡 / {gap.history_json.length} 条历史
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button onClick={() => onStatus(gap, "reviewing")} className="btn btn-outline btn-sm">复核</button>
        <button onClick={() => onStatus(gap, "pursue")} className="btn btn-outline btn-sm">追踪</button>
        <button onClick={() => onStatus(gap, "experiment_planned")} className="btn btn-outline btn-sm">实验计划</button>
        <button onClick={() => onStatus(gap, "needs_more_evidence")} className="btn btn-outline btn-sm">需证据</button>
        <button onClick={() => onStatus(gap, "promoted_to_idea")} className="btn btn-outline btn-sm">推进</button>
        <button onClick={() => onStatus(gap, "covered")} className="btn btn-outline btn-sm">已覆盖</button>
        <button onClick={() => onStatus(gap, "rejected")} className="btn btn-outline btn-sm">忽略</button>
        <button onClick={() => onFeedback(gap, "up")} className="btn btn-outline btn-sm">赞</button>
        <button onClick={() => onFeedback(gap, "down")} className="btn btn-outline btn-sm">踩</button>
      </div>
    </article>
  );
}

function GapDetailDialog({
  gap,
  onClose,
  onStatus,
  onFeedback,
}: {
  gap: DiscoveryGap;
  onClose: () => void;
  onStatus: (gap: DiscoveryGap, status: DiscoveryGapStatusRequest["status"]) => void;
  onFeedback: (gap: DiscoveryGap, verdict: "up" | "down" | "accepted" | "rejected") => void;
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
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="flex max-h-[88vh] w-full max-w-4xl flex-col surface-card shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap gap-1.5 text-xs">
              <span className="chip chip-primary">{labelFor("gapStatus", gap.status)}</span>
              <span className="chip chip-muted">覆盖状态 {labelFor("coverageStatus", gap.coverage_status || "unknown")}</span>
              <span className="chip chip-muted">v{gap.gap_version}</span>
            </div>
            <h2 className="mt-2 break-words text-lg font-semibold">{gap.title || "未命名想法"}</h2>
            <p className="mt-1 break-all text-xs text-muted-foreground">{gap.gap_id}</p>
          </div>
          <button onClick={onClose} className="shrink-0 btn btn-outline btn-sm">
            关闭
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          <div className="grid gap-3 md:grid-cols-3">
            <ScoreItem label={labelFor("scoreName", "novelty")} value={gap.scores.novelty} />
            <ScoreItem label={labelFor("scoreName", "feasibility")} value={gap.scores.feasibility} />
            <ScoreItem label={labelFor("scoreName", "evidence_strength")} value={gap.scores.evidence_strength} />
            <ScoreItem label={labelFor("scoreName", "risk")} value={gap.scores.risk} />
            <ScoreItem label={labelFor("scoreName", "experiment_cost")} value={gap.scores.experiment_cost} />
            <ScoreItem label={labelFor("scoreName", "domain_value")} value={gap.scores.domain_value} />
          </div>

          <DetailBlock label="完整描述" value={gap.full_description || gap.description} />
          <DetailBlock label="假设" value={gap.hypothesis} />
          <DetailBlock label="研究问题" value={gap.research_question || gap.question} />
          <DetailBlock label="目标任务" value={gap.target_task} />
          <DetailBlock label="约束" value={gap.constraints_json.join(" / ")} />
          <DetailBlock label="基线方案" value={gap.baseline_plan} />
          <DetailBlock label="贡献点" value={gap.contribution} />
          <DetailBlock label="AI 构建理由" value={gap.llm_rationale || ""} />
          <DetailBlock label="新颖性依据" value={gap.novelty_basis || ""} />
          <DetailBlock label="外部查新证据" value={gap.novelty_evidence_json || ""} />
          <DetailBlock label="对抗式自评" value={gap.critique_json || ""} />
          <DetailBlock label="想法谱系父节点" value={gap.lineage_parent_id || ""} />
          <DetailBlock label="目标会议/期刊" value={gap.target_venue} />
          <DetailBlock label="最小实验" value={gap.minimum_experiment} />
          {gap.rejection_reason && <DetailBlock label="拒绝原因" value={gap.rejection_reason} />}

          <IdList label="支撑证据" ids={gap.support_evidence_ids} />
          <IdList label="反向证据" ids={gap.counter_evidence_ids} />
          <IdList label="相关卡片" ids={gap.related_card_ids} />
          <IdList label="相关综合卡" ids={gap.related_synthesis_card_ids} />
          <IdList label="命中新论文" ids={gap.hit_by_paper_ids} />
          <IdList label="关联论文" ids={gap.paper_ids} />

          {gap.signals.length > 0 && (
            <div className="mt-4 rounded-lg border border-border bg-background p-3">
              <h3 className="text-xs font-semibold text-muted-foreground">信号</h3>
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                {gap.signals.map((signal) => (
                  <span key={signal} className="chip chip-muted">{signal}</span>
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
          <button onClick={() => updateStatus("reviewing")} className="btn btn-outline btn-sm">复核</button>
          <button onClick={() => updateStatus("pursue")} className="btn btn-outline btn-sm">追踪</button>
          <button onClick={() => updateStatus("experiment_planned")} className="btn btn-outline btn-sm">实验计划</button>
          <button onClick={() => updateStatus("needs_more_evidence")} className="btn btn-outline btn-sm">需证据</button>
          <button onClick={() => updateStatus("promoted_to_idea")} className="btn btn-outline btn-sm">推进</button>
          <button onClick={() => updateStatus("covered")} className="btn btn-outline btn-sm">已覆盖</button>
          <button onClick={() => updateStatus("rejected")} className="btn btn-outline btn-sm">忽略</button>
          <button onClick={() => onFeedback(gap, "accepted")} className="btn btn-outline btn-sm">采纳</button>
          <button onClick={() => onFeedback(gap, "rejected")} className="btn btn-outline btn-sm">反馈拒绝</button>
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
