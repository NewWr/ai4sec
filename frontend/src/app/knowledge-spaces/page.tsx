"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import LibraryDocumentPreview from "@/components/LibraryDocumentPreview";
import SplitPane from "@/components/SplitPane";
import { IconLayers, IconRefresh } from "@/components/icons";
import {
  copyKnowledgeSpaceItem,
  createKnowledgeSpaceDifyDataset,
  getKnowledgeSpaceDifyMarkdown,
  listKnowledgeSpaceDifyDocuments,
  listKnowledgeSpaceItems,
  listKnowledgeSpaces,
  moveKnowledgeSpaceItem,
  removeKnowledgeSpaceItem,
  resyncKnowledgeSpaceItem,
  updateKnowledgeSpace,
  updateKnowledgeSpaceItem,
} from "@/lib/api";
import { labelFor } from "@/lib/labels";
import type {
  KnowledgeSpace,
  KnowledgeSpaceItem,
  KnowledgeSpaceItemKind,
  LibraryDocument,
} from "@/lib/types";

const ITEM_KINDS: Array<{ value: "" | KnowledgeSpaceItemKind; label: string }> = [
  { value: "", label: "全部内容" },
  { value: "paper", label: "论文原文" },
  { value: "run", label: "解读报告" },
  { value: "card", label: "知识卡片" },
  { value: "snippet", label: "写作素材" },
  { value: "dify_document", label: "Dify 文档" },
];

type ActiveTab = "items" | "dify";

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function spaceLabel(space: KnowledgeSpace): string {
  return space.name_zh || space.name || space.space_id;
}

function itemTitle(item: KnowledgeSpaceItem): string {
  return item.paper_title_zh || item.paper_title || item.original_filename || item.item_id;
}

function fmtTime(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  const ms = value > 10_000_000_000 ? value : value * 1000;
  return new Date(ms).toLocaleString();
}

export default function KnowledgeSpacesPage() {
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
  const [spaceId, setSpaceId] = useState("daily_source");
  const [activeTab, setActiveTab] = useState<ActiveTab>("items");
  const [itemKind, setItemKind] = useState<"" | KnowledgeSpaceItemKind>("");
  const [items, setItems] = useState<KnowledgeSpaceItem[]>([]);
  const [targetSpaceId, setTargetSpaceId] = useState("main_source");
  const [spaceDraft, setSpaceDraft] = useState({ name_zh: "", description_zh: "", dify_dataset_id: "" });
  const [datasetName, setDatasetName] = useState("");
  const [itemNotes, setItemNotes] = useState<Record<string, string>>({});
  const [difyDocs, setDifyDocs] = useState<LibraryDocument[]>([]);
  const [difyTotal, setDifyTotal] = useState(0);
  const [difyPage, setDifyPage] = useState(1);
  const [selectedDocId, setSelectedDocId] = useState("");
  const [selectedDocName, setSelectedDocName] = useState("");
  const [docContent, setDocContent] = useState("");
  const [previewExpanded, setPreviewExpanded] = useState(false);
  const [docLoading, setDocLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [difyLoading, setDifyLoading] = useState(false);
  const [acting, setActing] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const currentSpace = useMemo(
    () => spaces.find((space) => space.space_id === spaceId) || null,
    [spaces, spaceId],
  );

  const currentDatasetId = currentSpace?.dify_dataset_id.trim() || "";

  const loadSpaces = useCallback(async () => {
    const res = await listKnowledgeSpaces();
    setSpaces(res.spaces || []);
    if (!res.spaces.some((space) => space.space_id === spaceId) && res.spaces[0]) {
      setSpaceId(res.spaces[0].space_id);
    }
  }, [spaceId]);

  const loadItems = useCallback(async () => {
    if (!spaceId) return;
    setLoading(true);
    try {
      const res = await listKnowledgeSpaceItems({
        spaceId,
        itemKind: itemKind || undefined,
        limit: 200,
      });
      setItems(res.items || []);
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setLoading(false);
    }
  }, [itemKind, spaceId]);

  const loadDifyDocuments = useCallback(async (page = 1) => {
    if (!spaceId || !currentDatasetId) {
      setDifyDocs([]);
      setDifyTotal(0);
      return;
    }
    setDifyLoading(true);
    try {
      const res = await listKnowledgeSpaceDifyDocuments({ spaceId, page, limit: 20 });
      setDifyDocs(res.data || []);
      setDifyTotal(res.total || 0);
      setDifyPage(res.page || page);
      setError("");
    } catch (err) {
      setError(errMessage(err));
      setDifyDocs([]);
      setDifyTotal(0);
    } finally {
      setDifyLoading(false);
    }
  }, [currentDatasetId, spaceId]);

  useEffect(() => {
    loadSpaces().catch((err) => setError(errMessage(err)));
  }, [loadSpaces]);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  useEffect(() => {
    if (!currentSpace) return;
    setSpaceDraft({
      name_zh: currentSpace.name_zh,
      description_zh: currentSpace.description_zh,
      dify_dataset_id: currentSpace.dify_dataset_id,
    });
    setDatasetName(currentSpace.name_zh || currentSpace.name || currentSpace.space_id);
  }, [currentSpace]);

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const item of items) {
      next[`${item.space_id}:${item.item_kind}:${item.item_id}`] = item.note;
    }
    setItemNotes(next);
  }, [items]);

  useEffect(() => {
    setSelectedDocId("");
    setSelectedDocName("");
    setDocContent("");
    setDifyPage(1);
    if (activeTab === "dify") {
      loadDifyDocuments(1);
    }
  }, [activeTab, loadDifyDocuments, spaceId]);

  const operate = useCallback(async (action: "move" | "copy" | "remove", item: KnowledgeSpaceItem) => {
    const key = `${action}:${item.space_id}:${item.item_kind}:${item.item_id}`;
    setActing(key);
    try {
      if (action === "move") {
        await moveKnowledgeSpaceItem({
          space_id: item.space_id,
          item_kind: item.item_kind,
          item_id: item.item_id,
          target_space_id: targetSpaceId,
        });
        setMessage("已移动。");
      } else if (action === "copy") {
        await copyKnowledgeSpaceItem({
          space_id: item.space_id,
          item_kind: item.item_kind,
          item_id: item.item_id,
          target_space_id: targetSpaceId,
        });
        setMessage("已复制。");
      } else {
        await removeKnowledgeSpaceItem({
          space_id: item.space_id,
          item_kind: item.item_kind,
          item_id: item.item_id,
        });
        setMessage("已从当前知识库移除。");
      }
      setError("");
      await loadSpaces();
      await loadItems();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setActing("");
    }
  }, [loadItems, loadSpaces, targetSpaceId]);

  const saveSpace = useCallback(async () => {
    if (!currentSpace) return;
    setActing(`space:${currentSpace.space_id}`);
    try {
      await updateKnowledgeSpace(currentSpace.space_id, spaceDraft);
      setMessage("知识库配置已保存。");
      setError("");
      await loadSpaces();
      if (activeTab === "dify") await loadDifyDocuments(1);
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setActing("");
    }
  }, [activeTab, currentSpace, loadDifyDocuments, loadSpaces, spaceDraft]);

  const createDataset = useCallback(async () => {
    if (!currentSpace) return;
    setActing(`dataset:${currentSpace.space_id}`);
    try {
      await createKnowledgeSpaceDifyDataset(currentSpace.space_id, {
        name: datasetName,
        indexing_technique: "economy",
        permission: "only_me",
      });
      setMessage("Dify 数据集已创建并绑定。");
      setError("");
      await loadSpaces();
      await loadItems();
      await loadDifyDocuments(1);
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setActing("");
    }
  }, [currentSpace, datasetName, loadDifyDocuments, loadItems, loadSpaces]);

  const saveItemNote = useCallback(async (item: KnowledgeSpaceItem) => {
    const key = `${item.space_id}:${item.item_kind}:${item.item_id}`;
    setActing(`note:${key}`);
    try {
      await updateKnowledgeSpaceItem({
        space_id: item.space_id,
        item_kind: item.item_kind,
        item_id: item.item_id,
        note: itemNotes[key] || "",
      });
      setMessage("备注已保存。");
      setError("");
      await loadItems();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setActing("");
    }
  }, [itemNotes, loadItems]);

  const resync = useCallback(async (item: KnowledgeSpaceItem) => {
    const key = `${item.space_id}:${item.item_kind}:${item.item_id}`;
    setActing(`resync:${key}`);
    try {
      await resyncKnowledgeSpaceItem({
        space_id: item.space_id,
        item_kind: item.item_kind,
        item_id: item.item_id,
        force: true,
      });
      setMessage("同步已重试。");
      setError("");
      await loadItems();
      if (activeTab === "dify") await loadDifyDocuments(1);
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setActing("");
    }
  }, [activeTab, loadDifyDocuments, loadItems]);

  const selectDocument = useCallback(async (doc: LibraryDocument) => {
    if (!currentSpace) return;
    const docId = String(doc.id || "");
    if (!docId) return;
    setSelectedDocId(docId);
    setSelectedDocName(doc.name || docId);
    setDocContent("");
    setDocLoading(true);
    try {
      const res = await getKnowledgeSpaceDifyMarkdown(currentSpace.space_id, docId);
      setSelectedDocName(res.document_name || doc.name || docId);
      setDocContent(res.content || "");
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setDocLoading(false);
    }
  }, [currentSpace]);

  return (
    <div className="fixed inset-x-0 bottom-0 top-14 flex min-h-0 flex-col overflow-hidden px-5 py-5">
      <div className="mx-auto flex w-full max-w-7xl shrink-0 flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3.5">
          <span className="icon-tile flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-xl">
            <IconLayers />
          </span>
          <div>
            <h1 className="font-display text-2xl font-semibold tracking-tight">知识库中心</h1>
            <p className="mt-1 text-sm text-muted-foreground">统一管理本地知识空间、每日推荐知识库和 Dify 索引。</p>
          </div>
        </div>
        <button
          onClick={() => {
            loadSpaces();
            loadItems();
            if (activeTab === "dify") loadDifyDocuments(1);
          }}
          className="btn btn-outline btn-sm"
        >
          <IconRefresh className="text-base" />
          刷新
        </button>
      </div>

      <div className="mx-auto mt-4 w-full max-w-7xl shrink-0">
        {error && <p className="alert alert-error mb-3">{error}</p>}
        {message && <p className="alert alert-info mb-3">{message}</p>}
      </div>

      <div className="mx-auto grid min-h-0 w-full max-w-7xl flex-1 gap-4 overflow-hidden lg:grid-cols-[280px_1fr]">
        <aside className="min-h-0 overflow-auto rounded-lg border border-border bg-card p-3">
          <div className="space-y-2">
            {spaces.map((space) => (
              <button
                key={space.space_id}
                onClick={() => setSpaceId(space.space_id)}
                className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                  spaceId === space.space_id
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-background hover:bg-muted"
                }`}
              >
                <span className="block font-medium">{spaceLabel(space)}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {space.item_count} 项，论文 {space.paper_count}，解读 {space.run_count}
                </span>
                <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                  Dify: {space.dify_dataset_id || "未绑定"}
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="flex min-h-0 min-w-0 flex-col overflow-hidden">
          <div className="mb-3 shrink-0 rounded-lg border border-border bg-card p-4">
            <div className="mb-3 flex flex-wrap gap-2">
              <button
                onClick={() => setActiveTab("items")}
                className={`rounded-lg border px-3 py-1.5 text-sm ${
                  activeTab === "items" ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted"
                }`}
              >
                内容
              </button>
              <button
                onClick={() => setActiveTab("dify")}
                className={`rounded-lg border px-3 py-1.5 text-sm ${
                  activeTab === "dify" ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted"
                }`}
              >
                Dify 索引
              </button>
            </div>

            {activeTab === "items" ? (
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={itemKind}
                  onChange={(event) => setItemKind(event.target.value as "" | KnowledgeSpaceItemKind)}
                  className="field"
                >
                  {ITEM_KINDS.map((kind) => <option key={kind.value || "all"} value={kind.value}>{kind.label}</option>)}
                </select>
                <span className="text-sm text-muted-foreground">目标知识库</span>
                <select
                  value={targetSpaceId}
                  onChange={(event) => setTargetSpaceId(event.target.value)}
                  className="field"
                >
                  {spaces.filter((space) => space.space_id !== spaceId).map((space) => (
                    <option key={space.space_id} value={space.space_id}>{spaceLabel(space)}</option>
                  ))}
                </select>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">当前数据集</span>
                <code className="max-w-full truncate rounded-md bg-muted px-2 py-1 text-xs">
                  {currentDatasetId || "未绑定"}
                </code>
                <button
                  onClick={() => loadDifyDocuments(1)}
                  disabled={!currentDatasetId || difyLoading}
                  className="btn btn-outline btn-sm"
                >
                  {difyLoading ? "加载中" : "刷新索引"}
                </button>
              </div>
            )}

            {currentSpace && (
              <div className="mt-3 grid gap-2 md:grid-cols-[1fr_1fr_auto]">
                <input
                  value={spaceDraft.name_zh}
                  onChange={(event) => setSpaceDraft((prev) => ({ ...prev, name_zh: event.target.value }))}
                  placeholder="中文名称"
                  className="field"
                />
                <input
                  value={spaceDraft.dify_dataset_id}
                  onChange={(event) => setSpaceDraft((prev) => ({ ...prev, dify_dataset_id: event.target.value }))}
                  placeholder="Dify 数据集 ID，留空则跳过同步"
                  className="field"
                />
                <button
                  onClick={saveSpace}
                  disabled={Boolean(acting)}
                  className="btn btn-outline"
                >
                  {acting === `space:${currentSpace.space_id}` ? "保存中" : "保存知识库"}
                </button>
                <textarea
                  value={spaceDraft.description_zh}
                  onChange={(event) => setSpaceDraft((prev) => ({ ...prev, description_zh: event.target.value }))}
                  placeholder="知识库说明"
                  rows={2}
                  className="resize-y field md:col-span-3"
                />
              </div>
            )}
          </div>

          {activeTab === "items" ? (
            <ItemsPanel
              acting={acting}
              items={items}
              itemNotes={itemNotes}
              loading={loading}
              onNoteChange={(key, value) => setItemNotes((prev) => ({ ...prev, [key]: value }))}
              onOperate={operate}
              onResync={resync}
              onSaveNote={saveItemNote}
              targetSpaceId={targetSpaceId}
            />
          ) : (
            <DifyPanel
              acting={acting}
              currentDatasetId={currentDatasetId}
              datasetName={datasetName}
              difyDocs={difyDocs}
              difyLoading={difyLoading}
              difyPage={difyPage}
              difyTotal={difyTotal}
              docContent={docContent}
              docLoading={docLoading}
              onCreateDataset={createDataset}
              onDatasetNameChange={setDatasetName}
              onPageChange={(page) => loadDifyDocuments(page)}
              onExpandPreview={() => setPreviewExpanded(true)}
              onSelectDocument={selectDocument}
              selectedDocId={selectedDocId}
              selectedDocName={selectedDocName}
            />
          )}
        </section>
      </div>

      {previewExpanded && docContent && (
        <div className="fixed inset-0 z-50 flex flex-col bg-background">
          <div className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border px-5">
            <button
              onClick={() => setPreviewExpanded(false)}
              className="btn btn-primary btn-sm shrink-0"
            >
              返回知识库
            </button>
            <p className="min-w-0 flex-1 truncate text-center text-sm font-medium">{selectedDocName || "Dify 文档预览"}</p>
            <button
              onClick={() => setPreviewExpanded(false)}
              className="btn btn-outline btn-sm shrink-0"
            >
              关闭
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <LibraryDocumentPreview content={docContent} title={selectedDocName} wide />
          </div>
          <button
            onClick={() => setPreviewExpanded(false)}
            className="btn btn-primary fixed bottom-5 left-5 z-[60] shadow-lg"
          >
            返回知识库
          </button>
        </div>
      )}
    </div>
  );
}

function ItemsPanel({
  acting,
  items,
  itemNotes,
  loading,
  onNoteChange,
  onOperate,
  onResync,
  onSaveNote,
  targetSpaceId,
}: {
  acting: string;
  items: KnowledgeSpaceItem[];
  itemNotes: Record<string, string>;
  loading: boolean;
  onNoteChange: (key: string, value: string) => void;
  onOperate: (action: "move" | "copy" | "remove", item: KnowledgeSpaceItem) => void;
  onResync: (item: KnowledgeSpaceItem) => void;
  onSaveNote: (item: KnowledgeSpaceItem) => void;
  targetSpaceId: string;
}) {
  if (loading) {
    return <div className="min-h-0 flex-1 py-16 text-center text-sm text-muted-foreground">加载中...</div>;
  }
  if (items.length === 0) {
    return <div className="min-h-0 flex-1 rounded-lg border border-border bg-card p-10 text-center text-sm text-muted-foreground">当前知识库没有内容。</div>;
  }

  return (
    <div className="min-h-0 flex-1 space-y-2 overflow-auto pr-1">
      {items.map((item) => {
        const keyBase = `${item.space_id}:${item.item_kind}:${item.item_id}`;
        return (
          <article key={keyBase} className="rounded-lg border border-border bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap gap-1.5 text-xs">
                  <span className="chip chip-muted">{labelFor("itemKind", item.item_kind)}</span>
                  <span className="chip chip-muted">{labelFor("sourceType", item.source_type || "unknown")}</span>
                  <span className="chip chip-muted">{labelFor("syncStatus", item.sync_status)}</span>
                  {item.run_mode && <span className="chip chip-muted">{labelFor("readingMode", item.run_mode)}</span>}
                  {item.run_status && <span className="chip chip-muted">{labelFor("runStatus", item.run_status)}</span>}
                </div>
                <h2 className="break-words text-base font-semibold">{itemTitle(item)}</h2>
                <p className="mt-1 break-all text-xs text-muted-foreground">
                  条目 ID：{item.item_id}
                  {item.paper_id && `；论文 ID：${item.paper_id}`}
                  {item.run_id && `；运行 ID：${item.run_id}`}
                  {item.dify_document_id && `；Dify: ${item.dify_document_id}`}
                </p>
                <div className="mt-3 flex max-w-3xl flex-wrap gap-2">
                  <input
                    value={itemNotes[keyBase] ?? item.note}
                    onChange={(event) => onNoteChange(keyBase, event.target.value)}
                    placeholder="备注"
                    className="min-w-[16rem] flex-1 field"
                  />
                  <button
                    onClick={() => onSaveNote(item)}
                    disabled={Boolean(acting)}
                    className="btn btn-outline btn-sm"
                  >
                    {acting === `note:${keyBase}` ? "保存中" : "保存备注"}
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {item.paper_id && (
                  <Link href={`/papers#paper-${item.paper_id}`} className="btn btn-outline btn-sm">
                    论文
                  </Link>
                )}
                {item.paper_id && item.run_id && (
                  <Link href={`/paper/${item.paper_id}/run/${item.run_id}`} className="btn btn-outline btn-sm">
                    解读
                  </Link>
                )}
                <button
                  onClick={() => onOperate("copy", item)}
                  disabled={!targetSpaceId || Boolean(acting)}
                  className="btn btn-outline btn-sm"
                >
                  {acting === `copy:${keyBase}` ? "复制中" : "复制"}
                </button>
                {(item.item_kind === "paper" || item.item_kind === "run") && (
                  <button
                    onClick={() => onResync(item)}
                    disabled={Boolean(acting)}
                    className="btn btn-outline btn-sm"
                  >
                    {acting === `resync:${keyBase}` ? "同步中" : "重试同步"}
                  </button>
                )}
                <button
                  onClick={() => onOperate("move", item)}
                  disabled={!targetSpaceId || Boolean(acting)}
                  className="btn btn-outline btn-sm"
                >
                  {acting === `move:${keyBase}` ? "移动中" : "移动"}
                </button>
                <button
                  onClick={() => onOperate("remove", item)}
                  disabled={Boolean(acting)}
                  className="btn btn-outline-danger btn-sm"
                >
                  {acting === `remove:${keyBase}` ? "移除中" : "移除关联"}
                </button>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function DifyPanel({
  acting,
  currentDatasetId,
  datasetName,
  difyDocs,
  difyLoading,
  difyPage,
  difyTotal,
  docContent,
  docLoading,
  onCreateDataset,
  onDatasetNameChange,
  onExpandPreview,
  onPageChange,
  onSelectDocument,
  selectedDocId,
  selectedDocName,
}: {
  acting: string;
  currentDatasetId: string;
  datasetName: string;
  difyDocs: LibraryDocument[];
  difyLoading: boolean;
  difyPage: number;
  difyTotal: number;
  docContent: string;
  docLoading: boolean;
  onCreateDataset: () => void;
  onDatasetNameChange: (value: string) => void;
  onExpandPreview: () => void;
  onPageChange: (page: number) => void;
  onSelectDocument: (doc: LibraryDocument) => void;
  selectedDocId: string;
  selectedDocName: string;
}) {
  if (!currentDatasetId) {
    return (
      <div className="min-h-0 flex-1 rounded-lg border border-border bg-card p-5">
        <p className="text-sm text-muted-foreground">
          当前知识库尚未绑定 Dify 数据集。绑定后，本地论文原文和解读才能同步到对应的 Dify 知识库。
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <input
            value={datasetName}
            onChange={(event) => onDatasetNameChange(event.target.value)}
            placeholder="新建 Dify 数据集名称"
            className="min-w-[16rem] flex-1 field"
          />
          <button
            onClick={onCreateDataset}
            disabled={Boolean(acting)}
            className="btn btn-primary"
          >
            {acting.startsWith("dataset:") ? "创建中" : "创建 Dify 数据集并绑定"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-border bg-card">
      <SplitPane
        defaultLeftWidth={38}
        left={
          <div className="h-full min-h-0 overflow-auto p-3">
            <div className="mb-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>共 {difyTotal} 个文档</span>
              <span>第 {difyPage} 页</span>
            </div>
            {difyLoading ? (
              <p className="py-10 text-center text-sm text-muted-foreground">加载中...</p>
            ) : difyDocs.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">当前 Dify 数据集没有文档。</p>
            ) : (
              <div className="space-y-2">
                {difyDocs.map((doc) => {
                  const docId = String(doc.id || "");
                  return (
                    <button
                      key={docId}
                      onClick={() => onSelectDocument(doc)}
                      className={`w-full rounded-lg border px-3 py-2 text-left text-sm hover:bg-muted ${
                        selectedDocId === docId ? "border-primary bg-primary/10" : "border-border"
                      }`}
                    >
                      <span className="block truncate font-medium">{doc.name || docId}</span>
                      <span className="mt-1 block truncate text-xs text-muted-foreground">
                        {labelFor("difyDocumentStatus", doc.indexing_status || doc.display_status || "unknown")}
                        {typeof doc.word_count === "number" ? ` · ${doc.word_count} 词` : ""}
                      </span>
                      {fmtTime(doc.created_at) && (
                        <span className="mt-0.5 block text-xs text-muted-foreground">{fmtTime(doc.created_at)}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
            <div className="mt-3 flex justify-between gap-2">
              <button
                onClick={() => onPageChange(Math.max(1, difyPage - 1))}
                disabled={difyPage <= 1 || difyLoading}
                className="btn btn-outline btn-sm"
              >
                上一页
              </button>
              <button
                onClick={() => onPageChange(difyPage + 1)}
                disabled={difyLoading || (difyDocs.length < 20 && difyTotal <= difyPage * 20)}
                className="btn btn-outline btn-sm"
              >
                下一页
              </button>
            </div>
          </div>
        }
        right={
          <div className="flex h-full min-h-0 flex-col overflow-hidden">
            <div className="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-border px-3">
              <p className="min-w-0 truncate text-xs text-muted-foreground">{selectedDocName || "未选择文档"}</p>
              <button
                onClick={onExpandPreview}
                disabled={!docContent}
                className="btn btn-outline btn-sm"
              >
                放大查看
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
            {docLoading ? (
              <p className="py-16 text-center text-sm text-muted-foreground">文档加载中...</p>
            ) : docContent ? (
              <LibraryDocumentPreview content={docContent} title={selectedDocName} />
            ) : (
              <p className="flex h-full items-center justify-center px-6 text-center text-sm text-muted-foreground">
                选择左侧 Dify 文档后预览原始 Markdown。
              </p>
            )}
            </div>
          </div>
        }
      />
    </div>
  );
}
