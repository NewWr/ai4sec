"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
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
import { CollectionOverview, DiscoveryLoader, PaperCard, PaperDeleteDialog, ReadingWorkbench } from "./components";
import type {
  DifySyncStatus,
  DiscoveryEdge,
  DiscoveryNode,
  DiscoveryReadingPath,
  DiscoveryRelationStatus,
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

  const handleRelationStatus = useCallback(async (relationId: string, status: DiscoveryRelationStatus) => {
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
