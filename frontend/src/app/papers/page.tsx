"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  bulkUpdatePaperLifecycle,
  createPaperCollection,
  createRun,
  deletePaper,
  deletePaperCollection,
  getPapersDiscovery,
  listPaperCollections,
  listPapers,
  movePaperCollection,
  retryPaperDifySync,
  updatePaperLifecycle,
  updateDiscoveryRelationStatus,
  updatePaper,
  updatePaperCollection,
} from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import {
  IconArrowRight,
  IconCheck,
  IconSphere,
  IconUpload,
} from "@/components/icons";
import type {
  DifySyncStatus,
  DiscoveryEdge,
  DiscoveryNode,
  DiscoveryReadingPath,
  DiscoveryTheme,
  PaperCollection,
  PaperCollectionItem,
  PaperLibraryItem,
  PapersDiscovery,
  PaperPriority,
  ReadingMode,
  ReadingStatus,
  ReadingDecision,
} from "@/lib/types";

type OutputLanguage = "en" | "zh";
type CollectionDraft = { id: string; name: string; description: string; parentId: string };
type PaperDraft = {
  paperId: string;
  title: string;
  titleZh: string;
  summaryZh: string;
  doi: string;
  venue: string;
  year: string;
  sciRank: string;
  ccfRank: string;
};

const MODES: ReadingMode[] = ["snap", "lens", "sphere", "auto"];
const READING_STATUSES: Array<{ value: ReadingStatus; label: string }> = [
  { value: "unread", label: "待读" },
  { value: "skimmed", label: "已略读" },
  { value: "reading", label: "精读中" },
  { value: "read", label: "已读" },
  { value: "archived", label: "归档" },
];
const PRIORITIES: Array<{ value: PaperPriority; label: string }> = [
  { value: "high", label: "高" },
  { value: "medium", label: "中" },
  { value: "low", label: "低" },
];
const DECISIONS: Array<{ value: Exclude<ReadingDecision, "">; label: string }> = [
  { value: "must_read", label: "必读" },
  { value: "useful", label: "有用" },
  { value: "background", label: "背景" },
  { value: "discard", label: "舍弃" },
];

function parseTime(iso: string): number {
  if (!iso) return 0;
  const ts = iso.includes("T") ? Date.parse(iso) : Date.parse(iso.replace(" ", "T") + "Z");
  return Number.isNaN(ts) ? 0 : ts;
}

function formatDate(iso: string, locale: string): string {
  const ts = parseTime(iso);
  if (!ts) return "";
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(ts));
}

function syncTone(status: string): string {
  if (status === "synced" || status === "skipped") return "bg-success/10 text-success border-success/20";
  if (status === "failed") return "bg-destructive/10 text-destructive border-destructive/25";
  if (status === "running" || status === "pending") return "bg-primary/10 text-primary border-primary/20";
  return "bg-muted text-muted-foreground border-border";
}

function statusTone(status: string): string {
  if (status === "done" || status === "synced") return "bg-success";
  if (status === "failed") return "bg-destructive";
  if (status === "running" || status === "pending") return "bg-primary";
  return "bg-muted-foreground";
}

function shortTitle(title: string, max = 64): string {
  return title.length > max ? `${title.slice(0, max - 1)}...` : title;
}

function displayTitle(item?: PaperLibraryItem): string {
  if (!item) return "";
  return item.display?.title_zh || item.title || item.paper_id;
}

function displayCollectionName(collection: PaperCollection): string {
  return collection.name_zh || collection.name || collection.collection_id;
}

function buildChildrenByParent(collections: PaperCollection[]): Map<string, PaperCollection[]> {
  const map = new Map<string, PaperCollection[]>();
  for (const collection of collections) {
    const parent = collection.parent_id || "";
    map.set(parent, [...(map.get(parent) || []), collection]);
  }
  for (const value of map.values()) {
    value.sort((a, b) => a.sort_order - b.sort_order || displayCollectionName(a).localeCompare(displayCollectionName(b)));
  }
  return map;
}

function collectionDescendantIds(collections: PaperCollection[], collectionId: string): Set<string> {
  const childrenByParent = buildChildrenByParent(collections);
  const ids = new Set<string>();
  const visit = (id: string) => {
    ids.add(id);
    for (const child of childrenByParent.get(id) || []) {
      visit(child.collection_id);
    }
  };
  if (collectionId) visit(collectionId);
  return ids;
}

function collectionOptionRows(
  collections: PaperCollection[],
  opts: { excludeIds?: Set<string>; includeUnclassified?: boolean } = {},
): { collection: PaperCollection; level: number }[] {
  const excludeIds = opts.excludeIds || new Set<string>();
  const includeUnclassified = opts.includeUnclassified ?? true;
  const childrenByParent = buildChildrenByParent(collections);
  const rows: { collection: PaperCollection; level: number }[] = [];
  const visited = new Set<string>();
  const visit = (parentId: string, level: number) => {
    for (const collection of childrenByParent.get(parentId) || []) {
      if (visited.has(collection.collection_id)) continue;
      if (excludeIds.has(collection.collection_id)) continue;
      if (!includeUnclassified && collection.collection_id === "unclassified") continue;
      rows.push({ collection, level });
      visited.add(collection.collection_id);
      visit(collection.collection_id, level + 1);
    }
  };
  visit("", 1);
  for (const collection of collections) {
    if (visited.has(collection.collection_id) || excludeIds.has(collection.collection_id)) continue;
    if (!includeUnclassified && collection.collection_id === "unclassified") continue;
    rows.push({ collection, level: 1 });
    visited.add(collection.collection_id);
    visit(collection.collection_id, 2);
  }
  return rows;
}

function collectionOptionLabel(collection: PaperCollection, level: number): string {
  const prefix = level > 1 ? `${"  ".repeat(level - 1)}└ ` : "";
  return `${prefix}${displayCollectionName(collection)}`;
}

function displayWorkflowStatus(status: string): string {
  const labels: Record<string, string> = {
    candidate: "候选",
    confirmed: "已保留",
    kept: "已保留",
    needs_more_evidence: "需要更多证据",
    promoted_to_idea: "已提升为想法",
    rejected: "已忽略",
    unverified: "未确认",
    uncovered: "未覆盖",
    partially_covered: "部分覆盖",
    insufficient_corpus: "语料不足",
    unknown: "未知",
  };
  return labels[status] || status;
}

function collectionIdsInScope(collections: PaperCollection[], collectionId: string): Set<string> | null {
  if (!collectionId) return null;
  return collectionDescendantIds(collections, collectionId);
}

export default function PapersPage() {
  const { t, locale } = useTranslation();
  const [items, setItems] = useState<PaperLibraryItem[]>([]);
  const [collections, setCollections] = useState<PaperCollection[]>([]);
  const [collectionItems, setCollectionItems] = useState<PaperCollectionItem[]>([]);
  const [discovery, setDiscovery] = useState<PapersDiscovery | null>(null);
  const [loading, setLoading] = useState(true);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryLoaded, setDiscoveryLoaded] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [selectedCollection, setSelectedCollection] = useState("");
  const [selectedTheme, setSelectedTheme] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [decisionFilter, setDecisionFilter] = useState("");
  const [syncFilter, setSyncFilter] = useState("");
  const [selectedPaperIds, setSelectedPaperIds] = useState<Set<string>>(() => new Set());
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [running, setRunning] = useState<Record<string, boolean>>({});
  const [moving, setMoving] = useState<Record<string, boolean>>({});
  const [updatingLifecycle, setUpdatingLifecycle] = useState<Record<string, boolean>>({});
  const [bulkUpdating, setBulkUpdating] = useState(false);
  const [updatingDiscovery, setUpdatingDiscovery] = useState<Record<string, boolean>>({});
  const [modeByPaper, setModeByPaper] = useState<Record<string, ReadingMode>>({});
  const [langByPaper, setLangByPaper] = useState<Record<string, OutputLanguage>>({});
  const [questionByPaper, setQuestionByPaper] = useState<Record<string, string>>({});
  const [selectedRunByPaper, setSelectedRunByPaper] = useState<Record<string, string>>({});
  const [newCollectionName, setNewCollectionName] = useState("");
  const [newCollectionDescription, setNewCollectionDescription] = useState("");
  const [newCollectionParentId, setNewCollectionParentId] = useState("");
  const [creatingCollection, setCreatingCollection] = useState(false);
  const [collectionDraft, setCollectionDraft] = useState<CollectionDraft | null>(null);
  const [updatingCollections, setUpdatingCollections] = useState<Record<string, boolean>>({});
  const [paperDraft, setPaperDraft] = useState<PaperDraft | null>(null);
  const [pendingDeletePaper, setPendingDeletePaper] = useState<PaperLibraryItem | null>(null);
  const [updatingPapers, setUpdatingPapers] = useState<Record<string, boolean>>({});
  const [deletingPapers, setDeletingPapers] = useState<Record<string, boolean>>({});

  const refreshLibrary = useCallback(async () => {
    const [papers, collectionData] = await Promise.all([
      listPapers({
        reading_status: statusFilter,
        priority: priorityFilter,
        decision: decisionFilter,
        collection_id: selectedCollection,
        sync_status: syncFilter,
      }),
      listPaperCollections(),
    ]);
    setItems(papers);
    setCollections(collectionData.collections);
    setCollectionItems(collectionData.items);
  }, [decisionFilter, priorityFilter, selectedCollection, statusFilter, syncFilter]);

  const load = useCallback(() => {
    setLoading(true);
    refreshLibrary()
      .then(() => {
        setError("");
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [refreshLibrary]);

  useEffect(() => {
    load();
  }, [load]);

  const itemById = useMemo(
    () => new Map(items.map((item) => [item.paper_id, item])),
    [items],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const selectedCollectionIds = collectionIdsInScope(collections, selectedCollection);
    const selectedPaperIds = selectedCollectionIds
      ? new Set(collectionItems.filter((item) => selectedCollectionIds.has(item.collection_id)).map((item) => item.paper_id))
      : null;
    const themePaperIds = selectedTheme
      ? new Set(discovery?.themes.find((theme) => theme.theme_id === selectedTheme)?.paper_ids || [])
      : null;
    return items.filter((item) => {
      if (selectedPaperIds && !selectedPaperIds.has(item.paper_id)) return false;
      if (themePaperIds && !themePaperIds.has(item.paper_id)) return false;
      if (!q) return true;
      const haystack = `${item.title} ${item.display?.title_zh || ""} ${item.display?.summary_zh || ""} ${item.paper_id} ${item.doi} ${item.venue}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [collectionItems, collections, discovery, items, query, selectedCollection, selectedTheme]);

  const workbench = useMemo(() => {
    const counts = {
      today: 0,
      unread: 0,
      reading: 0,
      readToOrganize: 0,
      unsynced: 0,
      unclassified: 0,
    };
    for (const item of items) {
      const active = item.decision !== "discard" && item.reading_status !== "archived";
      if (active && item.priority === "high" && item.reading_status !== "read") counts.today += 1;
      if (active && item.reading_status === "unread") counts.unread += 1;
      if (active && item.reading_status === "reading") counts.reading += 1;
      if (item.reading_status === "read" && !item.decision) counts.readToOrganize += 1;
      if (active && !["synced", "skipped"].includes(item.dify_sync.status)) counts.unsynced += 1;
      if (item.reading_status !== "archived" && (!item.primary_collection_id || item.primary_collection_id === "unclassified")) counts.unclassified += 1;
    }
    return counts;
  }, [items]);

  const updateSync = useCallback((paperId: string, sync: DifySyncStatus) => {
    setItems((prev) =>
      prev.map((item) => (item.paper_id === paperId ? { ...item, dify_sync: sync } : item)),
    );
  }, []);

  const handleLoadDiscovery = useCallback(async () => {
    setDiscoveryLoading(true);
    setError("");
    try {
      setDiscovery(await getPapersDiscovery());
      setDiscoveryLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDiscoveryLoading(false);
    }
  }, []);

  const handleRetrySync = useCallback(
    async (paperId: string) => {
      setSyncing((prev) => ({ ...prev, [paperId]: true }));
      setError("");
      try {
        const sync = await retryPaperDifySync(paperId);
        updateSync(paperId, sync);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSyncing((prev) => ({ ...prev, [paperId]: false }));
      }
    },
    [updateSync],
  );

  const handleCreateRun = useCallback(
    async (item: PaperLibraryItem) => {
      const mode = modeByPaper[item.paper_id] || "snap";
      const question = (questionByPaper[item.paper_id] || "").trim();
      if (mode === "auto" && !question) {
        setError(t("upload.question_required"));
        return;
      }
      setRunning((prev) => ({ ...prev, [item.paper_id]: true }));
      setError("");
      try {
        const run = await createRun({
          paper_id: item.paper_id,
          mode,
          llm_model: "",
          language: langByPaper[item.paper_id] || locale,
          question: mode === "auto" ? question : "",
        });
        window.location.href = `/paper/${item.paper_id}/run/${run.run_id}`;
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setRunning((prev) => ({ ...prev, [item.paper_id]: false }));
      }
    },
    [langByPaper, locale, modeByPaper, questionByPaper, t],
  );

  const handleMovePaper = useCallback(async (paperId: string, collectionId: string) => {
    if (!collectionId) return;
    setMoving((prev) => ({ ...prev, [paperId]: true }));
    setError("");
    try {
      await movePaperCollection(paperId, { collection_id: collectionId, is_primary: true });
      await refreshLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setMoving((prev) => ({ ...prev, [paperId]: false }));
    }
  }, [refreshLibrary]);

  const handleLifecycleUpdate = useCallback(async (
    paperId: string,
    patch: { reading_status?: ReadingStatus; priority?: PaperPriority; decision?: ReadingDecision; read_progress?: number },
  ) => {
    setUpdatingLifecycle((prev) => ({ ...prev, [paperId]: true }));
    setError("");
    try {
      const paper = await updatePaperLifecycle(paperId, {
        ...patch,
        last_read_at: patch.reading_status === "reading" || patch.reading_status === "read" ? new Date().toISOString() : undefined,
      });
      setItems((prev) => prev.map((item) => item.paper_id === paperId ? { ...item, ...paper } : item));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUpdatingLifecycle((prev) => ({ ...prev, [paperId]: false }));
    }
  }, []);

  const handleBulkLifecycle = useCallback(async (patch: { reading_status?: ReadingStatus; priority?: PaperPriority; decision?: ReadingDecision }) => {
    const ids = Array.from(selectedPaperIds);
    if (!ids.length) return;
    setBulkUpdating(true);
    setError("");
    try {
      await bulkUpdatePaperLifecycle({ paper_ids: ids, ...patch });
      await refreshLibrary();
      setSelectedPaperIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBulkUpdating(false);
    }
  }, [refreshLibrary, selectedPaperIds]);

  const handleCreateCollection = useCallback(async () => {
    const name = newCollectionName.trim();
    if (!name) {
      setError("请输入结构名称。");
      return;
    }
    setCreatingCollection(true);
    setError("");
    try {
      await createPaperCollection({
        name,
        name_zh: name,
        description_zh: newCollectionDescription.trim(),
        parent_id: newCollectionParentId || "",
      });
      await refreshLibrary();
      setNewCollectionName("");
      setNewCollectionDescription("");
      setNewCollectionParentId("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreatingCollection(false);
    }
  }, [newCollectionDescription, newCollectionName, newCollectionParentId, refreshLibrary]);

  const handleEditCollection = useCallback((collection: PaperCollection) => {
    setCollectionDraft({
      id: collection.collection_id,
      name: displayCollectionName(collection),
      description: collection.description_zh || collection.description || "",
      parentId: collection.parent_id || "",
    });
  }, []);

  const handleUpdateCollection = useCallback(async () => {
    if (!collectionDraft) return;
    const name = collectionDraft.name.trim();
    if (!name) {
      setError("请输入结构名称。");
      return;
    }
    setUpdatingCollections((prev) => ({ ...prev, [collectionDraft.id]: true }));
    setError("");
    try {
      await updatePaperCollection(collectionDraft.id, {
        name,
        name_zh: name,
        description_zh: collectionDraft.description.trim(),
        parent_id: collectionDraft.parentId,
      });
      await refreshLibrary();
      setCollectionDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUpdatingCollections((prev) => ({ ...prev, [collectionDraft.id]: false }));
    }
  }, [collectionDraft, refreshLibrary]);

  const handleDeleteCollection = useCallback(async (collectionId: string) => {
    setUpdatingCollections((prev) => ({ ...prev, [collectionId]: true }));
    setError("");
    try {
      await deletePaperCollection(collectionId);
      await refreshLibrary();
      if (selectedCollection === collectionId) setSelectedCollection("");
      if (collectionDraft?.id === collectionId) setCollectionDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUpdatingCollections((prev) => ({ ...prev, [collectionId]: false }));
    }
  }, [collectionDraft?.id, refreshLibrary, selectedCollection]);

  const handleEditPaper = useCallback((item: PaperLibraryItem) => {
    setPaperDraft({
      paperId: item.paper_id,
      title: item.title || "",
      titleZh: item.display?.title_zh || "",
      summaryZh: item.display?.summary_zh || "",
      doi: item.doi || "",
      venue: item.venue || "",
      year: item.year ? String(item.year) : "",
      sciRank: item.sci_rank || "",
      ccfRank: item.ccf_rank || "",
    });
  }, []);

  const handleUpdatePaper = useCallback(async () => {
    if (!paperDraft) return;
    const yearText = paperDraft.year.trim();
    const year = yearText ? Number(yearText) : 0;
    if (Number.isNaN(year) || year < 0 || year > 3000) {
      setError("请输入有效年份。");
      return;
    }
    setUpdatingPapers((prev) => ({ ...prev, [paperDraft.paperId]: true }));
    setError("");
    try {
      await updatePaper(paperDraft.paperId, {
        title: paperDraft.title.trim(),
        title_zh: paperDraft.titleZh.trim(),
        summary_zh: paperDraft.summaryZh.trim(),
        doi: paperDraft.doi.trim(),
        venue: paperDraft.venue.trim(),
        year,
        sci_rank: paperDraft.sciRank.trim(),
        ccf_rank: paperDraft.ccfRank.trim(),
      });
      await refreshLibrary();
      setPaperDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUpdatingPapers((prev) => ({ ...prev, [paperDraft.paperId]: false }));
    }
  }, [paperDraft, refreshLibrary]);

  const handleDeletePaper = useCallback(async (paperId: string) => {
    setDeletingPapers((prev) => ({ ...prev, [paperId]: true }));
    setError("");
    try {
      await deletePaper(paperId);
      await refreshLibrary();
      if (paperDraft?.paperId === paperId) setPaperDraft(null);
      setPendingDeletePaper(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingPapers((prev) => ({ ...prev, [paperId]: false }));
    }
  }, [paperDraft?.paperId, refreshLibrary]);

  const handleRelationStatus = useCallback(async (relationId: string, status: "confirmed" | "needs_more_evidence" | "rejected" | "unverified") => {
    if (!relationId) return;
    let previous: PapersDiscovery | null = null;
    setDiscovery((prev) => {
      previous = prev;
      if (!prev) return prev;
      return {
        ...prev,
        edges: status === "rejected"
          ? prev.edges.filter((edge) => edge.relation_id !== relationId)
          : prev.edges.map((edge) => edge.relation_id === relationId ? { ...edge, status } : edge),
      };
    });
    setUpdatingDiscovery((prev) => ({ ...prev, [`relation:${relationId}`]: true }));
    setError("");
    try {
      setDiscovery(await updateDiscoveryRelationStatus(relationId, { status }));
    } catch (err) {
      if (previous) setDiscovery(previous);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUpdatingDiscovery((prev) => ({ ...prev, [`relation:${relationId}`]: false }));
    }
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-5 py-8">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{t("papers.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">按收纳结构浏览论文，再查看研究发现地图。</p>
        </div>
        <Link
          href="/upload"
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover"
        >
          <IconUpload />
          {t("papers.upload")}
        </Link>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("papers.search_placeholder")}
          className="w-full max-w-md rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <button
          onClick={load}
          className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted"
        >
          {t("papers.refresh")}
        </button>
      </div>

      <ReadingWorkbench
        counts={workbench}
        statusFilter={statusFilter}
        priorityFilter={priorityFilter}
        decisionFilter={decisionFilter}
        syncFilter={syncFilter}
        selectedCount={selectedPaperIds.size}
        bulkUpdating={bulkUpdating}
        onStatusFilter={setStatusFilter}
        onPriorityFilter={setPriorityFilter}
        onDecisionFilter={setDecisionFilter}
        onSyncFilter={setSyncFilter}
        onBulkLifecycle={handleBulkLifecycle}
      />

      {error && <p className="mb-4 rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}

      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">{t("papers.loading")}</div>
      ) : (
        <>
          <CollectionOverview
            collections={collections}
            collectionItems={collectionItems}
            items={items}
            selectedCollection={selectedCollection}
            collectionDraft={collectionDraft}
            newCollectionName={newCollectionName}
            newCollectionDescription={newCollectionDescription}
            newCollectionParentId={newCollectionParentId}
            creatingCollection={creatingCollection}
            updatingCollections={updatingCollections}
            onSelect={(id) => {
              setSelectedCollection(id);
              setSelectedTheme("");
            }}
            onEditCollection={handleEditCollection}
            onCollectionDraftChange={setCollectionDraft}
            onUpdateCollection={handleUpdateCollection}
            onCancelEditCollection={() => setCollectionDraft(null)}
            onDeleteCollection={handleDeleteCollection}
            onNewCollectionNameChange={setNewCollectionName}
            onNewCollectionDescriptionChange={setNewCollectionDescription}
            onNewCollectionParentChange={setNewCollectionParentId}
            onCreateCollection={handleCreateCollection}
          />

          {filtered.length === 0 ? (
            <div className="rounded-xl border border-border bg-card px-5 py-12 text-center text-sm text-muted-foreground">
              {t("papers.empty")}
            </div>
          ) : (
            <section className="mb-8 space-y-3">
              {filtered.map((item) => (
                <PaperCard
                  key={item.paper_id}
                  item={item}
                  t={t}
                  locale={locale}
                  collection={collections.find((collection) => collection.collection_id === item.primary_collection_id)}
                  mode={modeByPaper[item.paper_id] || "snap"}
                  language={langByPaper[item.paper_id] || locale}
                  question={questionByPaper[item.paper_id] || ""}
                  selectedRunId={selectedRunByPaper[item.paper_id] || item.latest_run?.run_id || ""}
                  syncing={Boolean(syncing[item.paper_id])}
                  running={Boolean(running[item.paper_id])}
                  moving={Boolean(moving[item.paper_id])}
                  updating={Boolean(updatingPapers[item.paper_id])}
                  deleting={Boolean(deletingPapers[item.paper_id])}
                  lifecycleUpdating={Boolean(updatingLifecycle[item.paper_id])}
                  selected={selectedPaperIds.has(item.paper_id)}
                  collections={collections}
                  paperDraft={paperDraft?.paperId === item.paper_id ? paperDraft : null}
                  onSelectedChange={(checked) => setSelectedPaperIds((prev) => {
                    const next = new Set(prev);
                    if (checked) next.add(item.paper_id);
                    else next.delete(item.paper_id);
                    return next;
                  })}
                  onLifecycleUpdate={(patch) => handleLifecycleUpdate(item.paper_id, patch)}
                  onModeChange={(mode) => setModeByPaper((prev) => ({ ...prev, [item.paper_id]: mode }))}
                  onLanguageChange={(language) => setLangByPaper((prev) => ({ ...prev, [item.paper_id]: language }))}
                  onQuestionChange={(question) => setQuestionByPaper((prev) => ({ ...prev, [item.paper_id]: question }))}
                  onSelectedRunChange={(runId) => setSelectedRunByPaper((prev) => ({ ...prev, [item.paper_id]: runId }))}
                  onPaperDraftChange={setPaperDraft}
                  onEditPaper={() => handleEditPaper(item)}
                  onSavePaper={handleUpdatePaper}
                  onCancelEditPaper={() => setPaperDraft(null)}
                  onDeletePaper={() => setPendingDeletePaper(item)}
                  onRetrySync={() => handleRetrySync(item.paper_id)}
                  onCreateRun={() => handleCreateRun(item)}
                  onMovePaper={(collectionId) => handleMovePaper(item.paper_id, collectionId)}
                />
              ))}
            </section>
          )}

          {pendingDeletePaper && (
            <PaperDeleteDialog
              item={pendingDeletePaper}
              deleting={Boolean(deletingPapers[pendingDeletePaper.paper_id])}
              onCancel={() => setPendingDeletePaper(null)}
              onConfirm={() => handleDeletePaper(pendingDeletePaper.paper_id)}
            />
          )}

          <DiscoveryLoader
            discovery={discovery}
            discoveryLoaded={discoveryLoaded}
            discoveryLoading={discoveryLoading}
            itemById={itemById}
            collections={collections}
            selectedCollection={selectedCollection}
            collectionItems={collectionItems}
            selectedTheme={selectedTheme}
            updating={updatingDiscovery}
            t={t}
            onLoadDiscovery={handleLoadDiscovery}
            onSelectTheme={setSelectedTheme}
            onRelationStatus={handleRelationStatus}
          />
        </>
      )}
    </div>
  );
}

function CollectionOverview({
  collections,
  collectionItems,
  items,
  selectedCollection,
  collectionDraft,
  newCollectionName,
  newCollectionDescription,
  newCollectionParentId,
  creatingCollection,
  updatingCollections,
  onSelect,
  onEditCollection,
  onCollectionDraftChange,
  onUpdateCollection,
  onCancelEditCollection,
  onDeleteCollection,
  onNewCollectionNameChange,
  onNewCollectionDescriptionChange,
  onNewCollectionParentChange,
  onCreateCollection,
}: {
  collections: PaperCollection[];
  collectionItems: PaperCollectionItem[];
  items: PaperLibraryItem[];
  selectedCollection: string;
  collectionDraft: CollectionDraft | null;
  newCollectionName: string;
  newCollectionDescription: string;
  newCollectionParentId: string;
  creatingCollection: boolean;
  updatingCollections: Record<string, boolean>;
  onSelect: (id: string) => void;
  onEditCollection: (collection: PaperCollection) => void;
  onCollectionDraftChange: (draft: CollectionDraft | null) => void;
  onUpdateCollection: () => void;
  onCancelEditCollection: () => void;
  onDeleteCollection: (collectionId: string) => void;
  onNewCollectionNameChange: (value: string) => void;
  onNewCollectionDescriptionChange: (value: string) => void;
  onNewCollectionParentChange: (value: string) => void;
  onCreateCollection: () => void;
}) {
  const itemById = useMemo(() => new Map(items.map((item) => [item.paper_id, item])), [items]);
  const childrenByParent = useMemo(() => buildChildrenByParent(collections), [collections]);
  const paperIdsByCollection = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const item of collectionItems) {
      map.set(item.collection_id, [...(map.get(item.collection_id) || []), item.paper_id]);
    }
    return map;
  }, [collectionItems]);
  const roots = childrenByParent.get("") || collections.filter((collection) => !collection.parent_id);
  const newCollectionOptions = useMemo(
    () => collectionOptionRows(collections, { includeUnclassified: false }),
    [collections],
  );
  const editParentOptions = useMemo(() => {
    if (!collectionDraft) return [];
    return collectionOptionRows(collections, {
      excludeIds: collectionDescendantIds(collections, collectionDraft.id),
      includeUnclassified: false,
    });
  }, [collectionDraft, collections]);

  return (
    <section className="mb-6 rounded-xl border border-border bg-card p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">论文收纳结构</h2>
          <p className="mt-1 text-sm text-muted-foreground">先按研究结构查看当前论文归属。</p>
        </div>
        <button
          onClick={() => onSelect("")}
          className={`rounded-lg border px-3 py-2 text-sm ${
            selectedCollection ? "border-border hover:bg-muted" : "border-primary bg-primary text-primary-foreground"
          }`}
        >
          全部论文 · {items.length}
        </button>
      </div>
      <div className="mb-4 grid gap-2 border-b border-border pb-4 md:grid-cols-[1fr_1fr_1.4fr_auto]">
        <select
          value={newCollectionParentId}
          onChange={(e) => onNewCollectionParentChange(e.target.value)}
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
        >
          <option value="">一级结构</option>
          {newCollectionOptions.map(({ collection, level }) => (
            <option key={collection.collection_id} value={collection.collection_id}>
              {collectionOptionLabel(collection, level)}
            </option>
          ))}
        </select>
        <input
          value={newCollectionName}
          onChange={(e) => onNewCollectionNameChange(e.target.value)}
          placeholder={newCollectionParentId ? "新建子结构名称" : "新建一级结构名称"}
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <input
          value={newCollectionDescription}
          onChange={(e) => onNewCollectionDescriptionChange(e.target.value)}
          placeholder="结构说明"
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <button
          onClick={onCreateCollection}
          disabled={creatingCollection}
          className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
        >
          {creatingCollection ? "创建中" : "新建结构"}
        </button>
      </div>
      {collectionDraft && (
        <div className="mb-4 grid gap-2 rounded-lg border border-border bg-background p-3 md:grid-cols-[1fr_1fr_1.2fr_auto_auto]">
          <select
            value={collectionDraft.parentId}
            onChange={(e) => onCollectionDraftChange({ ...collectionDraft, parentId: e.target.value })}
            disabled={collectionDraft.id === "unclassified"}
            className="rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
          >
            <option value="">一级结构</option>
            {editParentOptions.map(({ collection, level }) => (
              <option key={collection.collection_id} value={collection.collection_id}>
                {collectionOptionLabel(collection, level)}
              </option>
            ))}
          </select>
          <input
            value={collectionDraft.name}
            onChange={(e) => onCollectionDraftChange({ ...collectionDraft, name: e.target.value })}
            placeholder="结构名称"
            className="rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <input
            value={collectionDraft.description}
            onChange={(e) => onCollectionDraftChange({ ...collectionDraft, description: e.target.value })}
            placeholder="结构说明"
            className="rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button
            onClick={onUpdateCollection}
            disabled={Boolean(updatingCollections[collectionDraft.id])}
            className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-50"
          >
            {updatingCollections[collectionDraft.id] ? "保存中" : "保存"}
          </button>
          <button
            onClick={onCancelEditCollection}
            className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted"
          >
            取消
          </button>
        </div>
      )}
      <div className="space-y-2">
        {roots.map((collection) => (
          <CollectionBlock
            key={collection.collection_id}
            collection={collection}
            level={1}
            childrenByParent={childrenByParent}
            paperIdsByCollection={paperIdsByCollection}
            itemById={itemById}
            selectedCollection={selectedCollection}
            updatingCollections={updatingCollections}
            onSelect={onSelect}
            onEdit={onEditCollection}
            onDelete={onDeleteCollection}
          />
        ))}
      </div>
    </section>
  );
}

function ReadingWorkbench({
  counts,
  statusFilter,
  priorityFilter,
  decisionFilter,
  syncFilter,
  selectedCount,
  bulkUpdating,
  onStatusFilter,
  onPriorityFilter,
  onDecisionFilter,
  onSyncFilter,
  onBulkLifecycle,
}: {
  counts: {
    today: number;
    unread: number;
    reading: number;
    readToOrganize: number;
    unsynced: number;
    unclassified: number;
  };
  statusFilter: string;
  priorityFilter: string;
  decisionFilter: string;
  syncFilter: string;
  selectedCount: number;
  bulkUpdating: boolean;
  onStatusFilter: (value: string) => void;
  onPriorityFilter: (value: string) => void;
  onDecisionFilter: (value: string) => void;
  onSyncFilter: (value: string) => void;
  onBulkLifecycle: (patch: { reading_status?: ReadingStatus; priority?: PaperPriority; decision?: ReadingDecision }) => void;
}) {
  const cards = [
    { label: "今日阅读队列", value: counts.today, onClick: () => onPriorityFilter("high") },
    { label: "待读", value: counts.unread, onClick: () => onStatusFilter("unread") },
    { label: "精读中", value: counts.reading, onClick: () => onStatusFilter("reading") },
    { label: "已读待整理", value: counts.readToOrganize, onClick: () => onStatusFilter("read") },
    { label: "未同步", value: counts.unsynced, onClick: () => onSyncFilter("not_synced") },
    { label: "未归类", value: counts.unclassified, onClick: () => undefined },
  ];
  return (
    <section className="mb-5 rounded-xl border border-border bg-card p-4">
      <div className="mb-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {cards.map((card) => (
          <button
            key={card.label}
            onClick={card.onClick}
            className="rounded-lg border border-border bg-background px-3 py-2 text-left transition-colors hover:border-primary/40"
          >
            <div className="text-lg font-semibold">{card.value}</div>
            <div className="mt-1 text-xs text-muted-foreground">{card.label}</div>
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select value={statusFilter} onChange={(e) => onStatusFilter(e.target.value)} className="rounded-lg border border-border bg-background px-2 py-2 text-sm">
          <option value="">全部阅读阶段</option>
          {READING_STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <select value={priorityFilter} onChange={(e) => onPriorityFilter(e.target.value)} className="rounded-lg border border-border bg-background px-2 py-2 text-sm">
          <option value="">全部优先级</option>
          {PRIORITIES.map((item) => <option key={item.value} value={item.value}>{item.label}优先级</option>)}
        </select>
        <select value={decisionFilter} onChange={(e) => onDecisionFilter(e.target.value)} className="rounded-lg border border-border bg-background px-2 py-2 text-sm">
          <option value="">全部读后用途</option>
          {DECISIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <select value={syncFilter} onChange={(e) => onSyncFilter(e.target.value)} className="rounded-lg border border-border bg-background px-2 py-2 text-sm">
          <option value="">全部同步状态</option>
          <option value="not_synced">未同步</option>
          <option value="pending">待同步</option>
          <option value="running">同步中</option>
          <option value="synced">已同步</option>
          <option value="failed">失败</option>
        </select>
        <button
          onClick={() => {
            onStatusFilter("");
            onPriorityFilter("");
            onDecisionFilter("");
            onSyncFilter("");
          }}
          className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted"
        >
          清除筛选
        </button>
        <div className="flex-1" />
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">已选 {selectedCount}</span>
          <button
            onClick={() => onBulkLifecycle({ reading_status: "read" })}
            disabled={!selectedCount || bulkUpdating}
            className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            设为已读
          </button>
          <button
            onClick={() => onBulkLifecycle({ reading_status: "reading", priority: "high" })}
            disabled={!selectedCount || bulkUpdating}
            className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            加入精读
          </button>
          <button
            onClick={() => onBulkLifecycle({ reading_status: "archived" })}
            disabled={!selectedCount || bulkUpdating}
            className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            归档
          </button>
          <button
            onClick={() => onBulkLifecycle({ decision: "background" })}
            disabled={!selectedCount || bulkUpdating}
            className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            标为背景
          </button>
        </div>
      </div>
    </section>
  );
}

function CollectionBlock({
  collection,
  level,
  childrenByParent,
  paperIdsByCollection,
  itemById,
  selectedCollection,
  updatingCollections,
  onSelect,
  onEdit,
  onDelete,
}: {
  collection: PaperCollection;
  level: number;
  childrenByParent: Map<string, PaperCollection[]>;
  paperIdsByCollection: Map<string, string[]>;
  itemById: Map<string, PaperLibraryItem>;
  selectedCollection: string;
  updatingCollections: Record<string, boolean>;
  onSelect: (id: string) => void;
  onEdit: (collection: PaperCollection) => void;
  onDelete: (collectionId: string) => void;
}) {
  const paperIds = paperIdsByCollection.get(collection.collection_id) || [];
  const papers = paperIds.map((paperId) => itemById.get(paperId)).filter(Boolean) as PaperLibraryItem[];
  const children = childrenByParent.get(collection.collection_id) || [];
  const active = selectedCollection === collection.collection_id;
  const updating = Boolean(updatingCollections[collection.collection_id]);
  const canDelete = collection.collection_id !== "unclassified" && children.length === 0 && paperIds.length === 0;
  return (
    <div className="relative">
      {level > 1 && <div className="absolute left-3 top-0 h-full w-px bg-border" />}
      <div className={`rounded-lg border p-3 ${active ? "border-primary bg-accent" : "border-border bg-background"}`} style={{ marginLeft: `${(level - 1) * 20}px` }}>
        <div className="flex items-start justify-between gap-3">
          <button onClick={() => onSelect(collection.collection_id)} className="min-w-0 flex-1 text-left">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                  {level} 级
                </span>
                <span className="break-words text-sm font-semibold">{displayCollectionName(collection)}</span>
              </div>
              {(collection.description_zh || collection.description) && (
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                  {collection.description_zh || collection.description}
                </p>
              )}
            </div>
          </button>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
            <span className="rounded-full bg-card px-2 py-0.5 text-xs text-muted-foreground">
              {collection.paper_count}
            </span>
            <button
              onClick={() => onEdit(collection)}
              className="rounded-md border border-border px-2 py-1 text-xs transition-colors hover:bg-card"
            >
              编辑
            </button>
            <button
              onClick={() => onDelete(collection.collection_id)}
              disabled={!canDelete || updating}
              className="rounded-md border border-border px-2 py-1 text-xs transition-colors hover:bg-card disabled:cursor-not-allowed disabled:opacity-40"
              title={canDelete ? "删除空目录" : "只能删除无子目录且无论文的结构"}
            >
              删除
            </button>
          </div>
        </div>
        {papers.length > 0 && (
          <div className="mt-3 space-y-1.5 border-l border-border pl-3">
            {papers.slice(0, 4).map((paper) => (
              <a key={paper.paper_id} href={`#paper-${paper.paper_id}`} className="block truncate rounded-md px-2 py-1.5 text-xs hover:bg-card">
                {displayTitle(paper)}
              </a>
            ))}
          </div>
        )}
      </div>
      {children.length > 0 && (
        <div className="mt-2 space-y-2">
          {children.map((child) => (
            <CollectionBlock
              key={child.collection_id}
              collection={child}
              level={level + 1}
              childrenByParent={childrenByParent}
              paperIdsByCollection={paperIdsByCollection}
              itemById={itemById}
              selectedCollection={selectedCollection}
              updatingCollections={updatingCollections}
              onSelect={onSelect}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DiscoveryLoader({
  discovery,
  discoveryLoaded,
  discoveryLoading,
  itemById,
  collections,
  selectedCollection,
  collectionItems,
  selectedTheme,
  updating,
  t,
  onLoadDiscovery,
  onSelectTheme,
  onRelationStatus,
}: {
  discovery: PapersDiscovery | null;
  discoveryLoaded: boolean;
  discoveryLoading: boolean;
  itemById: Map<string, PaperLibraryItem>;
  collections: PaperCollection[];
  selectedCollection: string;
  collectionItems: PaperCollectionItem[];
  selectedTheme: string;
  updating: Record<string, boolean>;
  t: (key: string, vars?: Record<string, string | number>) => string;
  onLoadDiscovery: () => void;
  onSelectTheme: (themeId: string) => void;
  onRelationStatus: (relationId: string, status: "confirmed" | "needs_more_evidence" | "rejected" | "unverified") => void;
}) {
  if (!discoveryLoaded || !discovery) {
    return (
      <section className="rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <IconSphere className="h-5 w-5 text-primary" />
              研究关系辅助线索
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">按需生成主题、规则关系和阅读路径，不影响论文结构浏览。</p>
          </div>
          <button
            onClick={onLoadDiscovery}
            disabled={discoveryLoading}
            className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            {discoveryLoading ? "加载中" : "加载研究关系线索"}
          </button>
        </div>
      </section>
    );
  }

  return (
    <DiscoveryFlow
      discovery={discovery}
      itemById={itemById}
      collections={collections}
      selectedCollection={selectedCollection}
      collectionItems={collectionItems}
      selectedTheme={selectedTheme}
      updating={updating}
      t={t}
      onSelectTheme={onSelectTheme}
      onRelationStatus={onRelationStatus}
    />
  );
}

function DiscoveryFlow({
  discovery,
  itemById,
  collections,
  selectedCollection,
  collectionItems,
  selectedTheme,
  updating,
  t,
  onSelectTheme,
  onRelationStatus,
}: {
  discovery: PapersDiscovery;
  itemById: Map<string, PaperLibraryItem>;
  collections: PaperCollection[];
  selectedCollection: string;
  collectionItems: PaperCollectionItem[];
  selectedTheme: string;
  updating: Record<string, boolean>;
  t: (key: string, vars?: Record<string, string | number>) => string;
  onSelectTheme: (themeId: string) => void;
  onRelationStatus: (relationId: string, status: "confirmed" | "needs_more_evidence" | "rejected" | "unverified") => void;
}) {
  const nodeById = useMemo(
    () => new Map(discovery.nodes.map((node) => [node.paper_id, node])),
    [discovery.nodes],
  );
  const collectionPaperIds = useMemo(() => {
    const selectedCollectionIds = collectionIdsInScope(collections, selectedCollection);
    if (!selectedCollectionIds) return null;
    return new Set(collectionItems.filter((item) => selectedCollectionIds.has(item.collection_id)).map((item) => item.paper_id));
  }, [collectionItems, collections, selectedCollection]);
  const scopedThemes = useMemo(() => {
    if (!collectionPaperIds) return discovery.themes;
    return discovery.themes
      .map((theme) => ({
        ...theme,
        paper_ids: theme.paper_ids.filter((paperId) => collectionPaperIds.has(paperId)),
      }))
      .filter((theme) => theme.paper_ids.length > 0)
      .map((theme) => ({ ...theme, paper_count: theme.paper_ids.length }));
  }, [collectionPaperIds, discovery.themes]);
  const activeTheme = scopedThemes.find((theme) => theme.theme_id === selectedTheme) || null;
  const visiblePaperIds = useMemo(() => {
    const ids = new Set<string>();
    if (collectionPaperIds) {
      collectionPaperIds.forEach((paperId) => ids.add(paperId));
    }
    if (activeTheme) {
      const themeIds = new Set(activeTheme.paper_ids);
      if (ids.size) {
        Array.from(ids).forEach((paperId) => {
          if (!themeIds.has(paperId)) ids.delete(paperId);
        });
      } else {
        activeTheme.paper_ids.forEach((paperId) => ids.add(paperId));
      }
    }
    return ids.size ? ids : null;
  }, [activeTheme, collectionPaperIds]);
  const visibleEdges = useMemo(() => {
    if (!visiblePaperIds) return discovery.edges.slice(0, 10);
    return discovery.edges.filter((edge) => visiblePaperIds.has(edge.source) || visiblePaperIds.has(edge.target)).slice(0, 10);
  }, [discovery.edges, visiblePaperIds]);
  const visiblePaths = useMemo(() => {
    if (!visiblePaperIds) return discovery.reading_paths;
    return discovery.reading_paths
      .map((path) => ({ ...path, paper_ids: path.paper_ids.filter((paperId) => visiblePaperIds.has(paperId)) }))
      .filter((path) => path.paper_ids.length > 0);
  }, [discovery.reading_paths, visiblePaperIds]);

  return (
    <section className="space-y-4">
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <IconSphere className="h-5 w-5 text-primary" />
              研究关系辅助线索
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">基于本地证据规则生成主题、关系和阅读路径，仅作为辅助整理线索。</p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <Metric label={t("papers.discovery.total")} value={discovery.stats.total_papers} />
            <Metric label={t("papers.discovery.evidence")} value={discovery.stats.evidence_items} />
            <Metric label={t("papers.discovery.relations")} value={discovery.stats.relation_edges} />
            <Metric label={t("papers.discovery.analyzed")} value={discovery.stats.analyzed_papers} />
          </div>
        </div>
        <ThemeSelector themes={scopedThemes} selectedTheme={selectedTheme} onSelectTheme={onSelectTheme} t={t} />
      </div>

      <ThemeSummary themes={activeTheme ? [activeTheme] : scopedThemes.slice(0, 8)} itemById={itemById} />
      <RelationList edges={visibleEdges} nodeById={nodeById} updating={updating} t={t} onStatusChange={onRelationStatus} />
      <ReadingPathList paths={visiblePaths} nodeById={nodeById} t={t} />
    </section>
  );
}

function ThemeSelector({
  themes,
  selectedTheme,
  onSelectTheme,
  t,
}: {
  themes: DiscoveryTheme[];
  selectedTheme: string;
  onSelectTheme: (themeId: string) => void;
  t: (key: string) => string;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={() => onSelectTheme("")}
        className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
          selectedTheme ? "border-border text-muted-foreground hover:bg-muted" : "border-primary bg-primary text-primary-foreground"
        }`}
      >
        {t("papers.discovery.all_themes")}
      </button>
      {themes.map((theme) => (
        <button
          key={theme.theme_id}
          onClick={() => onSelectTheme(theme.theme_id)}
          className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
            selectedTheme === theme.theme_id
              ? "border-primary bg-primary text-primary-foreground"
              : "border-border text-muted-foreground hover:bg-muted"
          }`}
          title={theme.keywords.join(", ")}
        >
          {theme.name} · {theme.paper_count}
        </button>
      ))}
    </div>
  );
}

function ThemeSummary({ themes, itemById }: { themes: DiscoveryTheme[]; itemById: Map<string, PaperLibraryItem> }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h3 className="mb-3 text-sm font-semibold">主题归纳</h3>
      {themes.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无主题。</div>
      ) : (
        <div className="space-y-3">
          {themes.map((theme) => (
            <div key={theme.theme_id} className="rounded-lg border border-border bg-background p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-medium">{theme.name}</div>
                <div className="text-xs text-muted-foreground">{theme.paper_count} 篇</div>
              </div>
              {theme.keywords.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {theme.keywords.map((keyword) => (
                    <span key={keyword} className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      {keyword}
                    </span>
                  ))}
                </div>
              )}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {theme.paper_ids.slice(0, 6).map((paperId) => (
                  <a key={paperId} href={`#paper-${paperId}`} className="rounded-full border border-border px-2 py-0.5 text-xs hover:bg-muted">
                    {shortTitle(displayTitle(itemById.get(paperId)) || paperId, 32)}
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="min-w-[5.5rem] rounded-lg border border-border px-3 py-2">
      <div className="text-base font-semibold leading-none">{value}</div>
      <div className="mt-1 text-muted-foreground">{label}</div>
    </div>
  );
}

function RelationActionButton({
  busy,
  active,
  onClick,
  children,
}: {
  busy?: boolean;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors disabled:opacity-50 ${
        active ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted"
      }`}
    >
      {busy ? "处理中" : children}
    </button>
  );
}

function RelationList({
  edges,
  nodeById,
  updating,
  t,
  onStatusChange,
}: {
  edges: DiscoveryEdge[];
  nodeById: Map<string, DiscoveryNode>;
  updating: Record<string, boolean>;
  t: (key: string) => string;
  onStatusChange: (relationId: string, status: "confirmed" | "needs_more_evidence" | "rejected" | "unverified") => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <IconSphere className="h-4 w-4 text-primary" />
        规则关系线索
      </div>
      <p className="mb-3 text-xs leading-5 text-muted-foreground">
        这些关系来自本地证据规则匹配，用于辅助归纳，不代表最终研究结论。
      </p>
      {edges.length === 0 ? (
        <div className="py-10 text-center text-sm text-muted-foreground">{t("papers.discovery.no_edges")}</div>
      ) : (
        <div className="space-y-3">
          {edges.map((edge) => {
            const source = nodeById.get(edge.source);
            const target = nodeById.get(edge.target);
            return (
              <div key={edge.relation_id || `${edge.source}-${edge.target}`} className="rounded-lg border border-border bg-background p-3">
                <div className="grid gap-2 md:grid-cols-[1fr_auto_1fr] md:items-center">
                  <PaperNode node={source} />
                  <div className="flex items-center gap-2 text-xs text-muted-foreground md:flex-col">
                    <div className="h-px w-10 bg-border md:h-6 md:w-px" />
                    <span>{Math.round(edge.weight * 100)}%</span>
                    <span className="rounded-full bg-muted px-2 py-0.5">{edge.relation}</span>
                    <div className="h-px w-10 bg-border md:h-6 md:w-px" />
                  </div>
                  <PaperNode node={target} />
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {[...edge.positive_checks, ...edge.evidence].slice(0, 8).map((word) => (
                    <span key={word} className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      {word}
                    </span>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
                    {displayWorkflowStatus(edge.status)}
                  </span>
                  {edge.relation_id && (
                    <>
                      <RelationActionButton
                        active={edge.status === "confirmed"}
                        busy={updating[`relation:${edge.relation_id}`]}
                        onClick={() => onStatusChange(edge.relation_id, "confirmed")}
                      >
                        保留关系
                      </RelationActionButton>
                      <RelationActionButton
                        active={edge.status === "needs_more_evidence"}
                        busy={updating[`relation:${edge.relation_id}`]}
                        onClick={() => onStatusChange(edge.relation_id, "needs_more_evidence")}
                      >
                        补充证据
                      </RelationActionButton>
                      <RelationActionButton
                        busy={updating[`relation:${edge.relation_id}`]}
                        onClick={() => onStatusChange(edge.relation_id, "rejected")}
                      >
                        忽略
                      </RelationActionButton>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PaperNode({ node }: { node?: DiscoveryNode }) {
  if (!node) return <div className="text-sm text-muted-foreground">Unknown paper</div>;
  return (
    <a href={`#paper-${node.paper_id}`} className="group min-w-0 rounded-lg border border-border bg-card px-3 py-2 hover:border-primary/40">
      <div className="flex min-w-0 items-start gap-2">
        <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${statusTone(node.status)}`} />
        <div className="min-w-0">
          <div className="truncate text-sm font-medium group-hover:text-primary">{shortTitle(node.title)}</div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {[node.venue, node.year || ""].filter(Boolean).join(" · ")}
          </div>
        </div>
      </div>
    </a>
  );
}

function ReadingPathList({
  paths,
  nodeById,
  t,
}: {
  paths: DiscoveryReadingPath[];
  nodeById: Map<string, DiscoveryNode>;
  t: (key: string) => string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-3 text-sm font-semibold">{t("papers.discovery.paths")}</div>
      {!paths.length ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无阅读路径。</div>
      ) : (
        <div className="space-y-3">
          {paths.map((path) => (
            <div key={path.path_id} className="rounded-lg border border-border bg-background p-3">
              <div className="text-sm font-semibold">{path.title}</div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{path.description}</p>
              <div className="mt-3 space-y-1.5">
                {path.paper_ids.map((paperId, idx) => {
                  const node = nodeById.get(paperId);
                  return (
                    <a key={paperId} href={`#paper-${paperId}`} className="flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-card">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] text-muted-foreground">
                        {idx + 1}
                      </span>
                      <span className="truncate">{node?.title || paperId}</span>
                    </a>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PaperCard({
  item,
  t,
  locale,
  collection,
  mode,
  language,
  question,
  selectedRunId,
  syncing,
  running,
  moving,
  updating,
  deleting,
  lifecycleUpdating,
  selected,
  collections,
  paperDraft,
  onSelectedChange,
  onLifecycleUpdate,
  onModeChange,
  onLanguageChange,
  onQuestionChange,
  onSelectedRunChange,
  onPaperDraftChange,
  onEditPaper,
  onSavePaper,
  onCancelEditPaper,
  onDeletePaper,
  onRetrySync,
  onCreateRun,
  onMovePaper,
}: {
  item: PaperLibraryItem;
  t: (key: string, vars?: Record<string, string | number>) => string;
  locale: string;
  collection?: PaperCollection;
  mode: ReadingMode;
  language: OutputLanguage;
  question: string;
  selectedRunId: string;
  syncing: boolean;
  running: boolean;
  moving: boolean;
  updating: boolean;
  deleting: boolean;
  lifecycleUpdating: boolean;
  selected: boolean;
  collections: PaperCollection[];
  paperDraft: PaperDraft | null;
  onSelectedChange: (checked: boolean) => void;
  onLifecycleUpdate: (patch: { reading_status?: ReadingStatus; priority?: PaperPriority; decision?: ReadingDecision; read_progress?: number }) => void;
  onModeChange: (mode: ReadingMode) => void;
  onLanguageChange: (language: OutputLanguage) => void;
  onQuestionChange: (question: string) => void;
  onSelectedRunChange: (runId: string) => void;
  onPaperDraftChange: (draft: PaperDraft | null) => void;
  onEditPaper: () => void;
  onSavePaper: () => void;
  onCancelEditPaper: () => void;
  onDeletePaper: () => void;
  onRetrySync: () => void;
  onCreateRun: () => void;
  onMovePaper: (collectionId: string) => void;
}) {
  const title = displayTitle(item);
  const originalTitle = item.title && item.title !== title ? item.title : "";
  const run = item.latest_run;
  const runs = item.runs || [];
  const sync = item.dify_sync;
  const canRetrySync = sync.status === "failed" || sync.status === "not_synced" || sync.status === "skipped";
  const selectedRun = runs.find((item) => item.run_id === selectedRunId) || run || runs[0] || null;
  const collectionOptions = collectionOptionRows(collections);

  return (
    <article id={`paper-${item.paper_id}`} className="scroll-mt-24 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start gap-2">
            <input
              type="checkbox"
              checked={selected}
              onChange={(e) => onSelectedChange(e.target.checked)}
              className="mt-1 h-4 w-4 rounded border-border"
              aria-label="选择论文"
            />
            <h2 className="min-w-0 flex-1 break-words text-base font-semibold">{title}</h2>
            <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${syncTone(sync.status)}`}>
              {t(`sync.${sync.status}`)}
            </span>
          </div>
          {originalTitle && <p className="mt-1 break-words text-xs text-muted-foreground">{originalTitle}</p>}
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{formatDate(item.created_at, locale)}</span>
            {collection && <span>{collection.name_zh || collection.name}</span>}
            {item.venue && <span>{item.venue}{item.year ? ` · ${item.year}` : ""}</span>}
            {item.doi && <span>{item.doi}</span>}
            {item.sci_rank && <span>SCI {item.sci_rank}</span>}
            {item.ccf_rank && <span>CCF {item.ccf_rank}</span>}
            {item.parse_status && <span>{t("papers.parse")}: {item.parse_status}</span>}
            {item.citation_key && <span>@{item.citation_key}</span>}
          </div>
          {(item.display?.summary_zh || item.display?.summary_en) && (
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              {item.display.summary_zh || item.display.summary_en}
            </p>
          )}
          <div className="mt-3 grid gap-2 text-sm md:grid-cols-2">
            <InfoLine
              label={t("papers.latest_run")}
              value={
                run
                  ? `${t(`upload.mode.${run.mode}.label`) || run.mode} · ${t(`run.status.${run.status}`) || run.status}`
                  : t("papers.no_runs")
              }
              href={run ? `/paper/${item.paper_id}/run/${run.run_id}` : ""}
            />
            <InfoLine
              label={t("papers.dify_doc")}
              value={sync.document_id || sync.error_msg || t("papers.no_doc")}
            />
          </div>
        </div>

        <div className="w-full shrink-0 space-y-3 lg:w-[23rem]">
          <div className="space-y-2 border-b border-border pb-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-muted-foreground">阅读阶段、优先级和读后用途</div>
              {lifecycleUpdating && <span className="text-xs text-primary">保存中</span>}
            </div>
            <div className="grid grid-cols-3 gap-2">
              <select
                value={item.reading_status}
                onChange={(e) => onLifecycleUpdate({ reading_status: e.target.value as ReadingStatus })}
                className="rounded-lg border border-border bg-background px-2 py-2 text-sm"
              >
                {READING_STATUSES.map((status) => (
                  <option key={status.value} value={status.value}>{status.label}</option>
                ))}
              </select>
              <select
                value={item.priority}
                onChange={(e) => onLifecycleUpdate({ priority: e.target.value as PaperPriority })}
                className="rounded-lg border border-border bg-background px-2 py-2 text-sm"
              >
                {PRIORITIES.map((priority) => (
                  <option key={priority.value} value={priority.value}>{priority.label}优先级</option>
                ))}
              </select>
              <select
                value={item.decision}
                onChange={(e) => onLifecycleUpdate({ decision: e.target.value as ReadingDecision })}
                className="rounded-lg border border-border bg-background px-2 py-2 text-sm"
              >
                <option value="">未决策</option>
                {DECISIONS.map((decision) => (
                  <option key={decision.value} value={decision.value}>{decision.label}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-10 text-xs text-muted-foreground">进度</span>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round(item.read_progress || 0)}
                onChange={(e) => onLifecycleUpdate({ read_progress: Number(e.target.value) })}
                className="min-w-0 flex-1"
              />
              <span className="w-10 text-right text-xs tabular-nums text-muted-foreground">{Math.round(item.read_progress || 0)}%</span>
            </div>
          </div>

          <div className="space-y-2 border-b border-border pb-3">
            <div className="text-xs font-medium text-muted-foreground">归类</div>
            <select
              value={item.primary_collection_id || ""}
              onChange={(e) => onMovePaper(e.target.value)}
              disabled={moving}
              className="w-full rounded-lg border border-border bg-background px-2 py-2 text-sm"
            >
              <option value="">选择收纳结构</option>
              {collectionOptions.map(({ collection, level }) => (
                <option key={collection.collection_id} value={collection.collection_id}>
                  {collectionOptionLabel(collection, level)}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">分析</div>
            {runs.length > 0 && (
              <div className="grid min-w-0 gap-2">
                <select
                  value={selectedRun?.run_id || ""}
                  onChange={(e) => onSelectedRunChange(e.target.value)}
                  className="min-w-0 w-full rounded-lg border border-border bg-background px-2 py-2 text-sm"
                >
                  {runs.map((item) => (
                    <option key={item.run_id} value={item.run_id}>
                      {(t(`upload.mode.${item.mode}.label`) || item.mode)} · {t(`run.status.${item.status}`) || item.status} · {formatDate(item.started_at, locale)}
                    </option>
                  ))}
                </select>
                {selectedRun && (
                  <Link
                    href={`/paper/${item.paper_id}/run/${selectedRun.run_id}`}
                    className="inline-flex w-full min-w-0 items-center justify-center rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted"
                  >
                    查看已有
                  </Link>
                )}
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <select
                value={mode}
                onChange={(e) => onModeChange(e.target.value as ReadingMode)}
                className="rounded-lg border border-border bg-background px-2 py-2 text-sm"
              >
                {MODES.map((m) => (
                  <option key={m} value={m}>{t(`upload.mode.${m}.label`)}</option>
                ))}
              </select>
              <select
                value={language}
                onChange={(e) => onLanguageChange(e.target.value as OutputLanguage)}
                className="rounded-lg border border-border bg-background px-2 py-2 text-sm"
              >
                <option value="en">English</option>
                <option value="zh">中文</option>
              </select>
            </div>
            {mode === "auto" && (
              <textarea
                value={question}
                onChange={(e) => onQuestionChange(e.target.value)}
                placeholder={t("upload.question_placeholder")}
                maxLength={2000}
                rows={2}
                className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
              />
            )}
            <div className="flex gap-2">
              <button
                onClick={onCreateRun}
                disabled={running}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-50"
              >
                {running ? t("papers.starting") : runs.length > 0 ? "重新分析" : t("papers.start_run")}
                {!running && <IconArrowRight />}
              </button>
              <button
                onClick={onRetrySync}
                disabled={syncing || !canRetrySync}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                title={sync.error_msg || t("papers.retry_sync")}
              >
                {syncing ? t("papers.syncing") : sync.status === "synced" ? <IconCheck /> : t("papers.retry_sync")}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2 border-t border-border pt-2">
              <button
                onClick={onEditPaper}
                disabled={updating || deleting}
                className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
              >
                编辑信息
              </button>
              <button
                onClick={onDeletePaper}
                disabled={deleting || updating}
                className="rounded-lg border border-destructive/30 px-3 py-2 text-sm text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-50"
              >
                {deleting ? "删除中" : "删除论文"}
              </button>
            </div>
          </div>
        </div>
      </div>
      {paperDraft && (
        <PaperEditPanel
          draft={paperDraft}
          updating={updating}
          onChange={onPaperDraftChange}
          onSave={onSavePaper}
          onCancel={onCancelEditPaper}
        />
      )}
    </article>
  );
}

function PaperDeleteDialog({
  item,
  deleting,
  onCancel,
  onConfirm,
}: {
  item: PaperLibraryItem;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const title = displayTitle(item);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4 py-6">
      <div className="w-full max-w-lg rounded-xl border border-border bg-card p-5 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-destructive/10 text-destructive">
            <span className="text-lg font-semibold">!</span>
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold">删除本地论文</h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              该操作会删除论文文件、解析块、分析记录、收纳关系和同步记录，删除后不能在当前系统中恢复。
            </p>
          </div>
        </div>
        <div className="mt-4 rounded-lg border border-border bg-background p-3">
          <div className="break-words text-sm font-medium">{title}</div>
          {item.title && item.title !== title && (
            <div className="mt-1 break-words text-xs text-muted-foreground">{item.title}</div>
          )}
          <div className="mt-2 text-xs text-muted-foreground">
            {[item.venue, item.year || "", item.doi].filter(Boolean).join(" · ") || item.paper_id}
          </div>
        </div>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={deleting}
            className="rounded-lg border border-border px-4 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            disabled={deleting}
            className="rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
          >
            {deleting ? "删除中" : "确认删除"}
          </button>
        </div>
      </div>
    </div>
  );
}

function PaperEditPanel({
  draft,
  updating,
  onChange,
  onSave,
  onCancel,
}: {
  draft: PaperDraft;
  updating: boolean;
  onChange: (draft: PaperDraft | null) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const update = (patch: Partial<PaperDraft>) => onChange({ ...draft, ...patch });
  return (
    <div className="mt-4 border-t border-border pt-4">
      <div className="grid gap-2 md:grid-cols-2">
        <input
          value={draft.titleZh}
          onChange={(e) => update({ titleZh: e.target.value })}
          placeholder="中文标题"
          className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <input
          value={draft.title}
          onChange={(e) => update({ title: e.target.value })}
          placeholder="原始标题"
          className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <input
          value={draft.venue}
          onChange={(e) => update({ venue: e.target.value })}
          placeholder="期刊或会议"
          className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <input
          value={draft.doi}
          onChange={(e) => update({ doi: e.target.value })}
          placeholder="DOI"
          className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <input
          value={draft.year}
          onChange={(e) => update({ year: e.target.value })}
          placeholder="年份"
          inputMode="numeric"
          className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <div className="grid grid-cols-2 gap-2">
          <input
            value={draft.sciRank}
            onChange={(e) => update({ sciRank: e.target.value })}
            placeholder="SCI 分区"
            className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <input
            value={draft.ccfRank}
            onChange={(e) => update({ ccfRank: e.target.value })}
            placeholder="CCF 等级"
            className="min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
        </div>
        <textarea
          value={draft.summaryZh}
          onChange={(e) => update({ summaryZh: e.target.value })}
          placeholder="中文简介"
          rows={3}
          className="min-w-0 resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50 md:col-span-2"
        />
      </div>
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <button
          onClick={onCancel}
          className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted"
        >
          取消
        </button>
        <button
          onClick={onSave}
          disabled={updating}
          className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-50"
        >
          {updating ? "保存中" : "保存信息"}
        </button>
      </div>
    </div>
  );
}

function InfoLine({ label, value, href }: { label: string; value: string; href?: string }) {
  const content = (
    <>
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate text-sm">{value}</span>
    </>
  );
  if (href) {
    return (
      <Link href={href} className="flex min-w-0 items-center gap-2 rounded-lg border border-border px-3 py-2 hover:bg-muted">
        {content}
      </Link>
    );
  }
  return <div className="flex min-w-0 items-center gap-2 rounded-lg border border-border px-3 py-2">{content}</div>;
}
