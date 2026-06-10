import type {
  ModelListResponse,
  PaperResponse,
  PaperUploadResponse,
  PaperCollection,
  PaperCollectionAssignRequest,
  PaperCollectionConfirmRequest,
  PaperCollectionConfirmResponse,
  PaperCollectionCreateRequest,
  PaperCollectionsResponse,
  PaperCollectionSuggestResponse,
  PaperCollectionUpdateRequest,
  PaperUpdateRequest,
  RecentRunResponse,
  PaperLibraryItem,
  PaperSyncStatusResponse,
  DifySyncStatus,
  DiscoveryRelationStatusRequest,
  PapersDiscovery,
  RunCreate,
  RunResponse,
  RunOutputResponse,
  LibraryStatusResponse,
  LibraryDatasetsResponse,
  LibraryDocumentsResponse,
  LibraryMarkdownResponse,
  LibrarySearchRequest,
  LibrarySearchResponse,
  LibraryAskRequest,
  LibraryAskResponse,
  ListPapersOptions,
  PaperLifecycleUpdateRequest,
  PaperBulkLifecycleUpdateRequest,
  PaperAnnotation,
  PaperAnnotationCreateRequest,
  PaperAnnotationUpdateRequest,
  PaperNote,
  PaperNoteUpdateRequest,
  AiReviewMark,
  AiReviewMarkCreateRequest,
  AiReviewMarkUpdateRequest,
  KnowledgeCard,
  KnowledgeCardBatchMergeRequest,
  KnowledgeCardBatchStatusRequest,
  KnowledgeCardCreateRequest,
  KnowledgeCardGenerateRequest,
  KnowledgeCardGeneration,
  KnowledgeCardUpdateRequest,
  KnowledgeSpaceItem,
  KnowledgeSpaceItemCopyRequest,
  KnowledgeSpaceItemMoveRequest,
  KnowledgeSpaceItemRemoveRequest,
  KnowledgeSpaceItemResyncRequest,
  KnowledgeSpaceItemUpdateRequest,
  KnowledgeSpaceItemsResponse,
  KnowledgeSpaceUpdateRequest,
  KnowledgeSpacesResponse,
  WritingSnippet,
  WritingSnippetCreateRequest,
  WritingSnippetUpdateRequest,
  LocalSearchMode,
  LocalSearchResponse,
  KnowledgeHealth,
  ExportResponse,
  ReferenceImportRequest,
  ImportResponse,
  LLMConnectionTestRequest,
  LLMConnectionTestResponse,
  LLMSettingsResponse,
  LLMSettingsUpdateRequest,
  DuplicateCandidatesResponse,
  HealthFixRequest,
  HealthFixResponse,
  TranslatorRequest,
  TranslatorResponse,
  DailyRecommendationFeedbackRequest,
  DailyRecommendationIngestRequest,
  DailyRecommendationIngestResponse,
  DailyRecommendationItem,
  DailyRecommendationListResponse,
  DailyRecommendationPromoteRequest,
  DailyRecommendationRefreshRequest,
  DailyRecommendationRefreshResponse,
  DailyRecommendationTopic,
  KnowledgeSpaceDifyDatasetCreateRequest,
  KnowledgeSpaceDifyDatasetResponse,
  KnowledgeSpaceDifyDocumentsResponse,
  KnowledgeSpaceDifyMarkdownResponse,
} from "./types";
import { getOwnerToken } from "./owner";

const API_BASE = "/api";

// SSE/EventSource must connect directly to backend — Next.js rewrite proxy
// buffers streaming responses, preventing real-time SSE delivery.
const BACKEND_SSE_BASE = process.env.NEXT_PUBLIC_BACKEND_URL;
if (!BACKEND_SSE_BASE) {
  throw new Error("NEXT_PUBLIC_BACKEND_URL is not configured; set it in ../.env");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return requestFromBase(API_BASE, path, init);
}

async function requestFromBackend<T>(path: string, init?: RequestInit): Promise<T> {
  return requestFromBase(`${BACKEND_SSE_BASE}/api`, path, init);
}

async function requestFromBase<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, init);
  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      if (typeof parsed.detail === "string" && parsed.detail.trim()) {
        detail = parsed.detail;
      }
    } catch {
      // Keep the raw response body for non-JSON errors.
    }
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json();
}

export async function listModels(): Promise<ModelListResponse> {
  return request("/models");
}

export async function getLLMSettings(): Promise<LLMSettingsResponse> {
  return request("/settings/llm");
}

export async function updateLLMSettings(
  body: LLMSettingsUpdateRequest,
  adminToken = "",
): Promise<LLMSettingsResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (adminToken.trim()) headers["X-Admin-Token"] = adminToken.trim();
  return request("/settings/llm", {
    method: "PATCH",
    headers,
    body: JSON.stringify(body),
  });
}

export async function testLLMSettings(
  body: LLMConnectionTestRequest,
  adminToken = "",
): Promise<LLMConnectionTestResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (adminToken.trim()) headers["X-Admin-Token"] = adminToken.trim();
  return request("/settings/llm/test", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

export async function translateText(body: TranslatorRequest): Promise<TranslatorResponse> {
  return request("/translator/translate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listDailyTopics(): Promise<DailyRecommendationTopic[]> {
  return request("/daily/topics");
}

export async function listDailyRecommendations(opts: {
  date?: string;
  topic_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<DailyRecommendationListResponse> {
  const qs = new URLSearchParams();
  if (opts.date) qs.set("date", opts.date);
  if (opts.topic_id) qs.set("topic_id", opts.topic_id);
  if (opts.status) qs.set("status", opts.status);
  qs.set("limit", String(opts.limit ?? 20));
  qs.set("offset", String(opts.offset ?? 0));
  return request(`/daily/items?${qs.toString()}`);
}

export async function refreshDailyRecommendations(
  body: DailyRecommendationRefreshRequest,
): Promise<DailyRecommendationRefreshResponse> {
  return request("/daily/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateDailyRecommendationFeedback(
  itemId: string,
  body: DailyRecommendationFeedbackRequest,
): Promise<DailyRecommendationItem> {
  return request(`/daily/items/${itemId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function ingestDailyRecommendation(
  itemId: string,
  body: DailyRecommendationIngestRequest,
): Promise<DailyRecommendationIngestResponse> {
  return request(`/daily/items/${itemId}/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, owner_token: getOwnerToken() }),
  });
}

export async function promoteDailyRecommendation(
  itemId: string,
  body: DailyRecommendationPromoteRequest = {},
): Promise<{ item_id: string; paper_id: string; run_id: string }> {
  return request(`/daily/items/${itemId}/promote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listKnowledgeSpaces(): Promise<KnowledgeSpacesResponse> {
  return request("/knowledge-spaces");
}

export async function listKnowledgeSpaceItems(opts: {
  spaceId: string;
  itemKind?: string;
  limit?: number;
  offset?: number;
}): Promise<KnowledgeSpaceItemsResponse> {
  const qs = new URLSearchParams({
    limit: String(opts.limit ?? 100),
    offset: String(opts.offset ?? 0),
  });
  if (opts.itemKind) qs.set("item_kind", opts.itemKind);
  return request(`/knowledge-spaces/${opts.spaceId}/items?${qs.toString()}`);
}

export async function updateKnowledgeSpace(
  spaceId: string,
  body: KnowledgeSpaceUpdateRequest,
): Promise<KnowledgeSpacesResponse["spaces"][number]> {
  return request(`/knowledge-spaces/${spaceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function createKnowledgeSpaceDifyDataset(
  spaceId: string,
  body: KnowledgeSpaceDifyDatasetCreateRequest = {},
): Promise<KnowledgeSpaceDifyDatasetResponse> {
  return request(`/knowledge-spaces/${spaceId}/dify-dataset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listKnowledgeSpaceDifyDocuments(opts: {
  spaceId: string;
  page?: number;
  limit?: number;
}): Promise<KnowledgeSpaceDifyDocumentsResponse> {
  const qs = new URLSearchParams({
    page: String(opts.page ?? 1),
    limit: String(opts.limit ?? 20),
  });
  return request(`/knowledge-spaces/${opts.spaceId}/dify-documents?${qs.toString()}`);
}

export async function getKnowledgeSpaceDifyMarkdown(
  spaceId: string,
  documentId: string,
): Promise<KnowledgeSpaceDifyMarkdownResponse> {
  return request(
    `/knowledge-spaces/${spaceId}/dify-documents/${encodeURIComponent(documentId)}/markdown`,
  );
}

export async function moveKnowledgeSpaceItem(
  body: KnowledgeSpaceItemMoveRequest,
): Promise<KnowledgeSpaceItem> {
  return request("/knowledge-spaces/items/move", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function copyKnowledgeSpaceItem(
  body: KnowledgeSpaceItemCopyRequest,
): Promise<KnowledgeSpaceItem> {
  return request("/knowledge-spaces/items/copy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function removeKnowledgeSpaceItem(
  body: KnowledgeSpaceItemRemoveRequest,
): Promise<void> {
  const res = await fetch(`${API_BASE}/knowledge-spaces/items/remove`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
}

export async function updateKnowledgeSpaceItem(
  body: KnowledgeSpaceItemUpdateRequest,
): Promise<KnowledgeSpaceItem> {
  return request("/knowledge-spaces/items/update", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function resyncKnowledgeSpaceItem(
  body: KnowledgeSpaceItemResyncRequest,
): Promise<KnowledgeSpaceItem> {
  return request("/knowledge-spaces/items/resync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function uploadPaper(file: File): Promise<PaperUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return request("/papers/upload", { method: "POST", body: form });
}

export async function listPapers(
  limitOrOptions: number | ListPapersOptions = 100,
  offset = 0,
): Promise<PaperLibraryItem[]> {
  const opts: ListPapersOptions = typeof limitOrOptions === "number"
    ? { limit: limitOrOptions, offset }
    : limitOrOptions;
  const qs = new URLSearchParams({
    limit: String(opts.limit ?? 100),
    offset: String(opts.offset ?? 0),
  });
  if (opts.reading_status) qs.set("reading_status", opts.reading_status);
  if (opts.priority) qs.set("priority", opts.priority);
  if (opts.decision) qs.set("decision", opts.decision);
  if (opts.collection_id) qs.set("collection_id", opts.collection_id);
  if (opts.sync_status) qs.set("sync_status", opts.sync_status);
  return request(`/papers?${qs.toString()}`);
}

export async function getPapersDiscovery(limit = 200): Promise<PapersDiscovery> {
  const qs = new URLSearchParams({ limit: String(limit) });
  return request(`/papers/discovery?${qs.toString()}`);
}

export async function listPaperCollections(): Promise<PaperCollectionsResponse> {
  return request("/papers/collections");
}

export async function createPaperCollection(
  body: PaperCollectionCreateRequest,
): Promise<PaperCollection> {
  return request("/papers/collections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updatePaperCollection(
  collectionId: string,
  body: PaperCollectionUpdateRequest,
): Promise<PaperCollection> {
  return request(`/papers/collections/${collectionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deletePaperCollection(collectionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/papers/collections/${collectionId}`, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
}

export async function suggestPaperCollection(
  paperId: string,
  llmModel = "",
): Promise<PaperCollectionSuggestResponse> {
  return requestFromBackend(`/papers/${paperId}/collection-suggestion`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ llm_model: llmModel }),
  });
}

export async function confirmPaperCollection(
  paperId: string,
  body: PaperCollectionConfirmRequest,
): Promise<PaperCollectionConfirmResponse> {
  return request(`/papers/${paperId}/collection-confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function movePaperCollection(
  paperId: string,
  body: PaperCollectionAssignRequest,
): Promise<PaperCollectionConfirmResponse["item"]> {
  return request(`/papers/${paperId}/collection/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateDiscoveryRelationStatus(
  relationId: string,
  body: DiscoveryRelationStatusRequest,
): Promise<PapersDiscovery> {
  return request(`/papers/discovery/relations/${relationId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getPaper(paperId: string): Promise<PaperResponse> {
  return request(`/papers/${paperId}`);
}

export async function getPaperSyncStatus(paperId: string): Promise<PaperSyncStatusResponse> {
  return request(`/papers/${paperId}/sync-status`);
}

export async function retryPaperDifySync(paperId: string): Promise<DifySyncStatus> {
  return request(`/papers/${paperId}/sync-dify`, { method: "POST" });
}

export async function updatePaper(
  paperId: string,
  body: PaperUpdateRequest,
): Promise<PaperResponse> {
  return request(`/papers/${paperId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updatePaperLifecycle(
  paperId: string,
  body: PaperLifecycleUpdateRequest,
): Promise<PaperResponse> {
  return request(`/papers/${paperId}/lifecycle`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function bulkUpdatePaperLifecycle(
  body: PaperBulkLifecycleUpdateRequest,
): Promise<{ updated: number }> {
  return request("/papers/lifecycle/bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deletePaper(paperId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/papers/${paperId}`, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
}

export async function createRun(body: RunCreate): Promise<RunResponse> {
  return request("/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, owner_token: getOwnerToken() }),
  });
}

export async function getRun(runId: string): Promise<RunResponse> {
  return request(`/runs/${runId}`);
}

export async function getRunOutput(runId: string): Promise<RunOutputResponse> {
  return request(`/runs/${runId}/output`);
}

export async function listPaperRuns(paperId: string): Promise<RunResponse[]> {
  return request(`/papers/${paperId}/runs`);
}

export async function listRecentRuns(
  limit = 20,
  activeOnly = false,
): Promise<RecentRunResponse[]> {
  const qs = new URLSearchParams({
    limit: String(limit),
    active_only: activeOnly ? "true" : "false",
    owner_token: getOwnerToken(),
  });
  return request(`/runs/recent?${qs.toString()}`);
}

export async function dismissRun(runId: string): Promise<RunResponse> {
  const qs = new URLSearchParams({ owner_token: getOwnerToken() });
  return request(`/runs/${runId}/dismiss?${qs.toString()}`, { method: "POST" });
}

export function getPaperPdfUrl(paperId: string): string {
  return `${API_BASE}/papers/${paperId}/pdf`;
}

export function getRunStreamUrl(runId: string, sinceSeq = 0): string {
  const url = new URL(`${BACKEND_SSE_BASE}/api/runs/${runId}/stream`);
  if (sinceSeq > 0) {
    url.searchParams.set("since_seq", String(sinceSeq));
  }
  return url.toString();
}

// --- Local knowledge assets ---

export async function listPaperAnnotations(paperId: string): Promise<PaperAnnotation[]> {
  return request(`/papers/${paperId}/annotations`);
}

export async function createPaperAnnotation(
  paperId: string,
  body: PaperAnnotationCreateRequest,
): Promise<PaperAnnotation> {
  return request(`/papers/${paperId}/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updatePaperAnnotation(
  annotationId: string,
  body: PaperAnnotationUpdateRequest,
): Promise<PaperAnnotation> {
  return request(`/annotations/${annotationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deletePaperAnnotation(annotationId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/annotations/${annotationId}`, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
}

export async function getPaperNote(paperId: string): Promise<PaperNote> {
  return request(`/papers/${paperId}/note`);
}

export async function updatePaperNote(
  paperId: string,
  body: PaperNoteUpdateRequest,
): Promise<PaperNote> {
  return request(`/papers/${paperId}/note`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listReviewMarks(paperId: string, runId = ""): Promise<AiReviewMark[]> {
  const qs = new URLSearchParams();
  if (runId) qs.set("run_id", runId);
  return request(`/papers/${paperId}/review-marks${qs.toString() ? `?${qs}` : ""}`);
}

export async function createReviewMark(body: AiReviewMarkCreateRequest): Promise<AiReviewMark> {
  return request("/review-marks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateReviewMark(
  markId: string,
  body: AiReviewMarkUpdateRequest,
): Promise<AiReviewMark> {
  return request(`/review-marks/${markId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listKnowledgeCards(opts: {
  query?: string;
  cardType?: string;
  status?: string;
  paperId?: string;
  createdBy?: string;
  runId?: string;
  assetLevel?: string;
  actionType?: string;
  priority?: string;
  hasSource?: string;
  qualityFlag?: string;
  minConfidence?: number;
  limit?: number;
  offset?: number;
} = {}): Promise<KnowledgeCard[]> {
  const qs = new URLSearchParams({
    limit: String(opts.limit ?? 100),
    offset: String(opts.offset ?? 0),
  });
  if (opts.query) qs.set("query", opts.query);
  if (opts.cardType) qs.set("card_type", opts.cardType);
  if (opts.status) qs.set("status", opts.status);
  if (opts.paperId) qs.set("paper_id", opts.paperId);
  if (opts.createdBy) qs.set("created_by", opts.createdBy);
  if (opts.runId) qs.set("run_id", opts.runId);
  if (opts.assetLevel) qs.set("asset_level", opts.assetLevel);
  if (opts.actionType) qs.set("action_type", opts.actionType);
  if (opts.priority) qs.set("priority", opts.priority);
  if (opts.hasSource) qs.set("has_source", opts.hasSource);
  if (opts.qualityFlag) qs.set("quality_flag", opts.qualityFlag);
  if (opts.minConfidence !== undefined) qs.set("min_confidence", String(opts.minConfidence));
  return request(`/knowledge/cards?${qs.toString()}`);
}

export async function generateKnowledgeCards(
  body: KnowledgeCardGenerateRequest,
): Promise<KnowledgeCardGeneration> {
  return request("/knowledge/cards/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listKnowledgeCardGenerations(opts: {
  paperId?: string;
  runId?: string;
  limit?: number;
} = {}): Promise<KnowledgeCardGeneration[]> {
  const qs = new URLSearchParams({ limit: String(opts.limit ?? 50) });
  if (opts.paperId) qs.set("paper_id", opts.paperId);
  if (opts.runId) qs.set("run_id", opts.runId);
  return request(`/knowledge/cards/generations?${qs.toString()}`);
}

export async function batchUpdateKnowledgeCardStatus(
  body: KnowledgeCardBatchStatusRequest,
): Promise<KnowledgeCard[]> {
  return request("/knowledge/cards/batch-status", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function batchMergeKnowledgeCards(
  body: KnowledgeCardBatchMergeRequest,
): Promise<KnowledgeCard[]> {
  return request("/knowledge/cards/batch-merge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function createKnowledgeCard(body: KnowledgeCardCreateRequest): Promise<KnowledgeCard> {
  return request("/knowledge/cards", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateKnowledgeCard(
  cardId: string,
  body: KnowledgeCardUpdateRequest,
): Promise<KnowledgeCard> {
  return request(`/knowledge/cards/${cardId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function mergeKnowledgeCard(cardId: string, targetCardId: string): Promise<KnowledgeCard> {
  return request(`/knowledge/cards/${cardId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_card_id: targetCardId }),
  });
}

export async function deleteKnowledgeCard(cardId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/knowledge/cards/${cardId}`, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
}

export async function listWritingSnippets(opts: {
  sectionHint?: string;
  paperId?: string;
} = {}): Promise<WritingSnippet[]> {
  const qs = new URLSearchParams();
  if (opts.sectionHint) qs.set("section_hint", opts.sectionHint);
  if (opts.paperId) qs.set("paper_id", opts.paperId);
  return request(`/writing/snippets${qs.toString() ? `?${qs}` : ""}`);
}

export async function createWritingSnippet(body: WritingSnippetCreateRequest): Promise<WritingSnippet> {
  return request("/writing/snippets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateWritingSnippet(
  snippetId: string,
  body: WritingSnippetUpdateRequest,
): Promise<WritingSnippet> {
  return request(`/writing/snippets/${snippetId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteWritingSnippet(snippetId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/writing/snippets/${snippetId}`, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
}

export async function localLibrarySearch(
  mode: LocalSearchMode,
  query: string,
  limit = 20,
): Promise<LocalSearchResponse> {
  const qs = new URLSearchParams({ mode, query, limit: String(limit) });
  return request(`/library/local-search?${qs.toString()}`);
}

export async function getKnowledgeHealth(): Promise<KnowledgeHealth> {
  return request("/health/knowledge");
}

export async function fixKnowledgeHealthIssue(
  body: HealthFixRequest,
): Promise<HealthFixResponse> {
  return request("/health/knowledge/fix", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function exportWritingMarkdown(sectionHint = ""): Promise<ExportResponse> {
  const qs = new URLSearchParams();
  if (sectionHint) qs.set("section_hint", sectionHint);
  return request(`/writing/export/markdown${qs.toString() ? `?${qs}` : ""}`);
}

export async function exportPapersBibtex(collectionId = ""): Promise<ExportResponse> {
  const qs = new URLSearchParams();
  if (collectionId) qs.set("collection_id", collectionId);
  return request(`/papers/export/bibtex${qs.toString() ? `?${qs}` : ""}`);
}

export async function exportPapersRis(collectionId = ""): Promise<ExportResponse> {
  const qs = new URLSearchParams();
  if (collectionId) qs.set("collection_id", collectionId);
  return request(`/papers/export/ris${qs.toString() ? `?${qs}` : ""}`);
}

export async function importReferences(body: ReferenceImportRequest): Promise<ImportResponse> {
  return request("/papers/import-references", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listDuplicateCandidates(): Promise<DuplicateCandidatesResponse> {
  return request("/knowledge/duplicates");
}

// --- Knowledge base (Dify) ---

export async function getLibraryStatus(): Promise<LibraryStatusResponse> {
  return request("/library/status");
}

export async function listLibraryDatasets(
  page = 1,
  limit = 20,
): Promise<LibraryDatasetsResponse> {
  const qs = new URLSearchParams({ page: String(page), limit: String(limit) });
  return request(`/library/datasets?${qs.toString()}`);
}

export async function listLibraryDocuments(opts: {
  datasetId?: string;
  page?: number;
  limit?: number;
} = {}): Promise<LibraryDocumentsResponse> {
  const qs = new URLSearchParams({
    page: String(opts.page ?? 1),
    limit: String(opts.limit ?? 20),
  });
  if (opts.datasetId) qs.set("dataset_id", opts.datasetId);
  return request(`/library/documents?${qs.toString()}`);
}

export async function getLibraryMarkdown(
  documentId: string,
  datasetId?: string,
): Promise<LibraryMarkdownResponse> {
  const qs = new URLSearchParams();
  if (datasetId) qs.set("dataset_id", datasetId);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request(`/library/documents/${encodeURIComponent(documentId)}/markdown${suffix}`);
}

export async function searchLibrary(
  body: LibrarySearchRequest,
): Promise<LibrarySearchResponse> {
  return request("/library/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function askLibrary(
  body: LibraryAskRequest,
): Promise<LibraryAskResponse> {
  return request("/library/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
