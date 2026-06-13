export interface PaperResponse {
  paper_id: string;
  title: string;
  doi: string;
  venue: string;
  year: number;
  sci_rank: string;
  ccf_rank: string;
  citation_key: string;
  reading_status: ReadingStatus;
  priority: PaperPriority;
  decision: ReadingDecision;
  personal_rating: number;
  read_progress: number;
  last_read_at: string;
  created_at: string;
}

export interface PaperUploadResponse {
  paper_id: string;
  message: string;
}

export interface PaperDisplay {
  title_zh: string;
  summary_en: string;
  summary_zh: string;
  translation_status: string;
  updated_at: string;
}

export interface PaperCollection {
  collection_id: string;
  parent_id: string;
  name: string;
  name_zh: string;
  description: string;
  description_zh: string;
  sort_order: number;
  paper_count: number;
  created_at: string;
  updated_at: string;
}

export interface PaperCollectionItem {
  collection_id: string;
  paper_id: string;
  is_primary: boolean;
  note: string;
  note_zh: string;
  sort_order: number;
  updated_at: string;
}

export interface PaperCollectionsResponse {
  collections: PaperCollection[];
  items: PaperCollectionItem[];
}

export interface PaperCollectionCreateRequest {
  name: string;
  name_zh?: string;
  description?: string;
  description_zh?: string;
  parent_id?: string;
}

export interface PaperCollectionUpdateRequest {
  name?: string;
  name_zh?: string;
  description?: string;
  description_zh?: string;
  parent_id?: string;
}

export interface PaperUpdateRequest {
  title?: string;
  title_zh?: string;
  summary_zh?: string;
  doi?: string;
  venue?: string;
  year?: number;
  sci_rank?: string;
  ccf_rank?: string;
  citation_key?: string;
}

export interface PaperCollectionSuggestion {
  mode: "existing" | "new";
  collection_id: string;
  new_name: string;
  new_name_zh: string;
  new_description: string;
  new_description_zh: string;
  confidence: number;
  reason: string;
}

export interface PaperCollectionSuggestResponse {
  paper_id: string;
  paper_title: string;
  paper_title_zh: string;
  summary_zh: string;
  summary_en: string;
  suggestion: PaperCollectionSuggestion;
  collections: PaperCollection[];
}

export interface PaperCollectionConfirmRequest {
  collection_id?: string;
  new_name?: string;
  new_name_zh?: string;
  new_description?: string;
  new_description_zh?: string;
  parent_id?: string;
  note?: string;
}

export interface PaperCollectionConfirmResponse {
  collection: PaperCollection;
  item: PaperCollectionItem;
}

export interface PaperCollectionAssignRequest {
  collection_id: string;
  is_primary?: boolean;
  note?: string;
}

export type DiscoveryRelationStatus = "confirmed" | "verified" | "needs_more_evidence" | "rejected" | "unverified";

export interface DiscoveryRelationStatusRequest {
  status: DiscoveryRelationStatus;
}

export interface DiscoveryGapStatusRequest {
  status:
    | "kept"
    | "candidate"
    | "reviewing"
    | "pursue"
    | "experiment_planned"
    | "needs_more_evidence"
    | "promoted_to_idea"
    | "rejected"
    | "covered";
  rejection_reason?: string;
  research_question?: string;
  target_task?: string;
  constraints_json?: string[];
  baseline_plan?: string;
  contribution?: string;
  target_venue?: string;
  minimum_experiment?: string;
}

export interface ModelListResponse {
  models: string[];
  default: string;
}

export interface LLMSettingsResponse {
  base_url: string;
  thinking_model: string;
  models: string[];
  default: string;
  reasoning_effort: string;
  reasoning_efforts: string[];
  api_key_configured: boolean;
  api_key_suffix: string;
  source: string;
}

export interface LLMSettingsUpdateRequest {
  base_url: string;
  thinking_model: string;
  reasoning_effort: string;
  api_key?: string;
  clear_api_key?: boolean;
}

export interface LLMConnectionTestRequest extends LLMSettingsUpdateRequest {
  use_saved_api_key?: boolean;
}

export interface LLMConnectionTestResponse {
  ok: boolean;
  base_url: string;
  model: string;
  endpoint: string;
  status_code: number;
  elapsed_ms: number;
  message: string;
  error: string;
}

export interface TranslatorRequest {
  text: string;
  source_lang: string;
  target_lang: string;
  model_type?: "latency_optimized" | "quality_optimized" | "prefer_quality_optimized" | "";
}

export interface TranslatorResponse {
  source_text: string;
  translated_text: string;
  source_lang: string;
  target_lang: string;
  status: string;
  provider: string;
  error_msg: string;
}

export interface DailyRecommendationTopic {
  topic_id: string;
  name: string;
  name_zh: string;
  enabled: boolean;
  sort_order: number;
  config: Record<string, unknown>;
}

export type DailyRecommendationStatus =
  | "candidate"
  | "interested"
  | "irrelevant"
  | "dismissed"
  | "ingesting"
  | "ingested"
  | "ingest_failed";

export interface DailyRecommendationGapMatch {
  gap_id: string;
  title: string;
  matched_terms: string[];
  score: number;
}

export interface DailyRecommendationScoreDetail {
  matched_behavior?: string[];
  behavior_score?: number;
  matched_gaps?: DailyRecommendationGapMatch[];
  gap_hit_count?: number;
  [key: string]: unknown;
}

export interface DailyRecommendationItem {
  item_id: string;
  arxiv_id: string;
  topic_id: string;
  title_en: string;
  title_zh: string;
  abstract_en: string;
  abstract_zh: string;
  authors: string[];
  primary_category: string;
  categories: string[];
  published_at: string;
  updated_at: string;
  arxiv_url: string;
  pdf_url: string;
  score: number;
  score_detail: DailyRecommendationScoreDetail;
  reason: string;
  title_translation_status: string;
  abstract_translation_status: string;
  llm_review_status: string;
  status: DailyRecommendationStatus;
  linked_paper_id: string;
  linked_run_id: string;
  error_msg: string;
  fetched_date: string;
  created_at: string;
}

export interface DailyRecommendationListResponse {
  date: string;
  topics: DailyRecommendationTopic[];
  items: DailyRecommendationItem[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface DailyRecommendationRefreshRequest {
  date?: string;
  topic_id?: string;
  force?: boolean;
}

export interface DailyRecommendationRefreshResponse {
  job_id: string;
  status: "started" | "running" | "done" | "failed" | string;
  date: string;
  fetched: number;
  inserted_or_updated: number;
  kept: number;
  skipped: number;
  message: string;
  errors?: Array<{ topic_id: string; topic: string; error: string }>;
  started_at?: string;
  finished_at?: string;
}

export interface DailyRecommendationFeedbackRequest {
  action: "interested" | "irrelevant" | "dismissed";
  note?: string;
}

export interface DailyRecommendationIngestRequest {
  mode?: ReadingMode;
  parse_mode?: ReadingMode;
  language?: "en" | "zh";
  llm_model?: string;
  collection_id?: string;
  source_space_id?: string;
  analysis_space_id?: string;
  sync_to_dify?: boolean;
  ingest_source_only?: boolean;
  start_run?: boolean;
  owner_token?: string;
}

export interface DailyRecommendationIngestResponse {
  item_id: string;
  paper_id: string;
  run_id: string;
  status: string;
  message: string;
}

export type KnowledgeSpaceItemKind = "paper" | "run" | "dify_document" | "card" | "snippet";

export interface KnowledgeSpace {
  space_id: string;
  name: string;
  name_zh: string;
  space_type: string;
  description: string;
  description_zh: string;
  dify_dataset_id: string;
  is_system: boolean;
  sort_order: number;
  item_count: number;
  paper_count: number;
  run_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSpaceItem {
  space_id: string;
  item_kind: KnowledgeSpaceItemKind;
  item_id: string;
  paper_id: string;
  run_id: string;
  source_type: string;
  sync_status: string;
  dify_document_id: string;
  note: string;
  paper_title: string;
  paper_title_zh: string;
  original_filename: string;
  run_mode: string;
  run_status: string;
  run_started_at: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSpacesResponse {
  spaces: KnowledgeSpace[];
}

export interface KnowledgeSpaceItemsResponse {
  space: KnowledgeSpace;
  items: KnowledgeSpaceItem[];
}

export interface KnowledgeSpaceDifyDatasetCreateRequest {
  name?: string;
  indexing_technique?: string;
  permission?: string;
}

export interface KnowledgeSpaceDifyDatasetResponse {
  space: KnowledgeSpace;
  dataset: Record<string, unknown>;
}

export interface KnowledgeSpaceDifyDocumentsResponse {
  space: KnowledgeSpace;
  data: LibraryDocument[];
  has_more?: boolean;
  total?: number;
  page?: number;
  limit?: number;
}

export interface KnowledgeSpaceDifyMarkdownResponse {
  space: KnowledgeSpace;
  content: string;
  document_name: string;
  raw?: Record<string, unknown>;
}

export interface KnowledgeSpaceItemMoveRequest {
  space_id: string;
  item_kind: KnowledgeSpaceItemKind;
  item_id: string;
  target_space_id: string;
}

export type KnowledgeSpaceItemCopyRequest = KnowledgeSpaceItemMoveRequest;

export interface KnowledgeSpaceItemRemoveRequest {
  space_id: string;
  item_kind: KnowledgeSpaceItemKind;
  item_id: string;
}

export interface KnowledgeSpaceUpdateRequest {
  name?: string;
  name_zh?: string;
  description?: string;
  description_zh?: string;
  dify_dataset_id?: string;
  sort_order?: number;
}

export interface KnowledgeSpaceItemUpdateRequest {
  space_id: string;
  item_kind: KnowledgeSpaceItemKind;
  item_id: string;
  note?: string;
  sync_status?: "pending" | "running" | "synced" | "failed" | "skipped";
  dify_document_id?: string;
}

export interface KnowledgeSpaceItemResyncRequest {
  space_id: string;
  item_kind: KnowledgeSpaceItemKind;
  item_id: string;
  force?: boolean;
}

export interface DailyRecommendationPromoteRequest {
  source_target_space_id?: string;
  analysis_target_space_id?: string;
  copy?: boolean;
}

export interface RunResponse {
  run_id: string;
  paper_id: string;
  mode: string;
  llm_model: string;
  status: string;
  error_msg: string;
  started_at: string;
  finished_at: string | null;
  user_question?: string;
  detected_intent?: string;
  current_step?: string;
  progress_json?: string;
}

export interface RecentRunResponse {
  run_id: string;
  paper_id: string;
  paper_title: string;
  mode: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  current_step: string;
  user_question: string;
}

export interface PaperRunSummary {
  run_id: string;
  mode: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  current_step: string;
  user_question: string;
}

export interface DifySyncStatus {
  paper_id: string;
  dataset_id: string;
  document_id: string;
  source_hash: string;
  status: string;
  attempts: number;
  error_msg: string;
  updated_at: string;
}

export interface AnalysisDifySyncStatus {
  run_id: string;
  paper_id: string;
  dataset_id: string;
  document_id: string;
  source_hash: string;
  status: string;
  attempts: number;
  error_msg: string;
  updated_at: string;
}

export interface PaperLibraryItem {
  paper_id: string;
  title: string;
  doi: string;
  venue: string;
  year: number;
  sci_rank: string;
  ccf_rank: string;
  citation_key: string;
  reading_status: ReadingStatus;
  priority: PaperPriority;
  decision: ReadingDecision;
  personal_rating: number;
  read_progress: number;
  last_read_at: string;
  created_at: string;
  parse_status: string;
  parse_updated_at: string;
  primary_collection_id: string;
  collection_ids: string[];
  display: PaperDisplay;
  latest_run: PaperRunSummary | null;
  runs: PaperRunSummary[];
  dify_sync: DifySyncStatus;
}

export interface PaperSyncStatusResponse {
  paper: DifySyncStatus;
  analysis: AnalysisDifySyncStatus[];
}

export interface DiscoveryStats {
  total_papers: number;
  parsed_papers: number;
  analyzed_papers: number;
  synced_papers: number;
  year_range: string;
  evidence_items: number;
  relation_edges: number;
  gap_candidates: number;
  discovery_version: number;
}

export interface DiscoveryEvidence {
  evidence_id: string;
  evidence_type: string;
  paper_id: string;
  block_id: number;
  page: number;
  quote: string;
  normalized_label: string;
  taxonomy_path: string;
  confidence: number;
  extractor: string;
  model_version: string;
  prompt_version: string;
  status: string;
  revision_history: Array<Record<string, unknown>>;
  evidence_version: number;
}

export interface DiscoveryTheme {
  theme_id: string;
  name: string;
  paper_count: number;
  keywords: string[];
  paper_ids: string[];
  taxonomy_path: string;
}

export interface DiscoveryNode {
  paper_id: string;
  title: string;
  year: number;
  venue: string;
  theme_ids: string[];
  status: string;
  evidence_count: number;
}

export interface DiscoveryEdge {
  source: string;
  target: string;
  weight: number;
  relation: string;
  evidence: string[];
  relation_id: string;
  source_evidence_ids: string[];
  target_evidence_ids: string[];
  rule_id: string;
  positive_checks: string[];
  negative_checks: string[];
  counter_evidence_ids: string[];
  comparability_json: Record<string, unknown>;
  confidence: number;
  status: string;
  verifier_version: string;
  relation_version: number;
}

export interface DiscoveryScore {
  novelty: number;
  feasibility: number;
  evidence_strength: number;
  risk: number;
  experiment_cost: number;
  domain_value: number;
}

export interface DiscoveryGap {
  gap_id: string;
  title: string;
  description: string;
  full_description: string;
  score: number;
  paper_ids: string[];
  signals: string[];
  question: string;
  hypothesis: string;
  support_evidence_ids: string[];
  counter_evidence_ids: string[];
  related_synthesis_card_ids: string[];
  related_card_ids: string[];
  research_question: string;
  target_task: string;
  constraints_json: string[];
  baseline_plan: string;
  contribution: string;
  target_venue: string;
  history_json: Array<Record<string, unknown>>;
  coverage_status: string;
  scores: DiscoveryScore;
  status: string;
  rejection_reason: string;
  minimum_experiment: string;
  hit_by_paper_ids: string[];
  gap_version: number;
}

export interface DiscoveryReadingPath {
  path_id: string;
  title: string;
  description: string;
  paper_ids: string[];
}

export interface PapersDiscovery {
  stats: DiscoveryStats;
  themes: DiscoveryTheme[];
  nodes: DiscoveryNode[];
  edges: DiscoveryEdge[];
  gaps: DiscoveryGap[];
  reading_paths: DiscoveryReadingPath[];
  evidence: DiscoveryEvidence[];
}

export interface ProgressEntry {
  step: string;
  status: string;
  [key: string]: unknown;
}

export interface RunOutputResponse {
  run_id: string;
  markdown: string;
  json_data: string;
}

export interface DocumentPartition {
  paper_id: string;
  part: "main_body" | "references" | "appendix" | "supplementary" | "unknown_tail";
  title: string;
  page_start: number;
  page_end: number;
  block_start: number;
  block_end: number;
  section_paths: string[];
  confidence: number;
  reason: string;
}

export interface SupplementaryIndexSection {
  title: string;
  part: string;
  page_start: number;
  page_end: number;
  summary: string;
  evidence_types: string[];
  use_when: string[];
}

export interface SupplementaryIndex {
  paper_id: string;
  sections: SupplementaryIndexSection[];
  total_chars: number;
  truncated: boolean;
}

export type EvidenceAnchorTopic =
  | "training"
  | "method"
  | "dataset"
  | "metric"
  | "result"
  | "limitation"
  | "motivation"
  | "other";

export type EvidenceAnchorStatus = "resolved" | "candidate" | "page_only" | "unresolved";

export interface EvidenceAnchor {
  schema_version?: number;
  anchor_id: string;
  paper_id: string;
  run_id: string;
  mode: string;
  citation_index: number;
  claim_text: string;
  source_page: number;
  source_quote: string;
  source_block_id?: number;
  source_bbox?: number[];
  section_path?: string;
  topics: EvidenceAnchorTopic[];
  confidence: number;
  status: EvidenceAnchorStatus;
  highlightable?: boolean;
  match_reason?: string;
}

export interface RunOutputJson {
  document_partitions?: DocumentPartition[];
  supplementary_index?: SupplementaryIndex;
  evidence_anchors?: EvidenceAnchor[];
  [key: string]: unknown;
}

export interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
  seq?: number;
}

export type ReadingMode = "snap" | "lens" | "sphere" | "auto";

export interface RunCreate {
  paper_id: string;
  mode: ReadingMode;
  llm_model: string;
  language?: string;  // "en" | "zh"
  question?: string;  // non-empty only when mode === "auto"
  owner_token?: string;  // injected by the API client; scopes recent-runs visibility
}

export type ReadingStatus = "unread" | "skimmed" | "reading" | "read" | "archived";
export type PaperPriority = "high" | "medium" | "low";
export type ReadingDecision = "must_read" | "useful" | "background" | "discard" | "";
export type AnnotationType = "highlight" | "note" | "question" | "correction";
export type KnowledgeCardType = "claim" | "method" | "dataset" | "metric" | "result" | "limitation" | "question" | "idea";
export type KnowledgeCardStatus = "draft" | "verified" | "rejected" | "merged";
export type KnowledgeAssetLevel = "evidence" | "synthesis" | "action";
export type AiReviewStatus = "trusted" | "pending" | "error" | "valuable";
export type SectionHint = "related_work" | "method" | "experiment" | "limitation";
export type LocalSearchMode = "papers" | "fragments" | "cards" | "relations" | "writing";

export interface ListPapersOptions {
  limit?: number;
  offset?: number;
  reading_status?: string;
  priority?: string;
  decision?: string;
  collection_id?: string;
  sync_status?: string;
}

export interface PaperLifecycleUpdateRequest {
  reading_status?: ReadingStatus;
  priority?: PaperPriority;
  decision?: ReadingDecision;
  personal_rating?: number;
  read_progress?: number;
  last_read_at?: string;
}

export interface PaperBulkLifecycleUpdateRequest {
  paper_ids: string[];
  reading_status?: ReadingStatus;
  priority?: PaperPriority;
  decision?: ReadingDecision;
}

export interface PaperAnnotation {
  annotation_id: string;
  paper_id: string;
  page: number;
  quote: string;
  note: string;
  annotation_type: AnnotationType;
  color: string;
  bbox_json: string;
  created_at: string;
  updated_at: string;
}

export interface PaperAnnotationCreateRequest {
  paper_id?: string;
  page?: number;
  quote?: string;
  note?: string;
  annotation_type?: AnnotationType;
  color?: string;
  bbox_json?: string;
}

export interface PaperAnnotationUpdateRequest {
  page?: number;
  quote?: string;
  note?: string;
  annotation_type?: AnnotationType;
  color?: string;
  bbox_json?: string;
}

export interface PdfSelectionRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PdfSelectionRange {
  page: number;
  quote: string;
  rects: PdfSelectionRect[];
}

export interface PdfTextSelection {
  selection_id: string;
  source: "pdf" | "ai";
  page: number;
  quote: string;
  ranges: PdfSelectionRange[];
  anchor_rect: {
    left: number;
    top: number;
    width: number;
    height: number;
  };
  created_at: number;
}

export type PdfSelectionAction = "replace" | "append" | "save" | "question" | "card" | "cancel";

export interface PdfHighlight {
  id: string;
  ranges: PdfSelectionRange[];
  color?: string;
  active?: boolean;
}

export interface PaperNote {
  paper_id: string;
  summary_user: string;
  key_takeaways: string;
  open_questions: string;
  reading_decision: string;
  created_at: string;
  updated_at: string;
}

export interface PaperNoteUpdateRequest {
  summary_user?: string;
  key_takeaways?: string;
  open_questions?: string;
  reading_decision?: string;
}

export interface AiReviewMark {
  mark_id: string;
  paper_id: string;
  run_id: string;
  source_ref: string;
  quote: string;
  status: AiReviewStatus;
  note: string;
  created_at: string;
  updated_at: string;
}

export interface AiReviewMarkCreateRequest {
  paper_id: string;
  run_id?: string;
  source_ref?: string;
  quote?: string;
  status?: AiReviewStatus;
  note?: string;
}

export interface AiReviewMarkUpdateRequest {
  status?: AiReviewStatus;
  note?: string;
}

export interface KnowledgeCard {
  card_id: string;
  card_type: KnowledgeCardType;
  title: string;
  content: string;
  paper_id: string;
  paper_title: string;
  source_page: number;
  source_quote: string;
  confidence: number;
  status: KnowledgeCardStatus;
  tags: string;
  created_by: "user" | "ai";
  merged_into_id: string;
  evidence_ids: string[];
  citation_key: string;
  run_id: string;
  source_kind: string;
  source_ref: string;
  normalized_key: string;
  quality_flags: string[];
  prompt_version: string;
  extractor_version: string;
  asset_level: KnowledgeAssetLevel;
  synthesis_type: string;
  action_type: string;
  why_useful: string;
  use_case: string;
  next_action: string;
  expected_output: string;
  risk_or_caveat: string;
  priority: "high" | "medium" | "low";
  supporting_card_ids: string[];
  supporting_paper_ids: string[];
  evidence_strength: string;
  reviewed_at: string;
  reviewed_by: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeCardCreateRequest {
  card_type?: KnowledgeCardType;
  title: string;
  content?: string;
  paper_id?: string;
  source_page?: number;
  source_quote?: string;
  confidence?: number;
  status?: KnowledgeCardStatus;
  tags?: string;
  created_by?: "user" | "ai";
  evidence_ids?: string[];
  run_id?: string;
  source_kind?: string;
  source_ref?: string;
  normalized_key?: string;
  quality_flags?: string[];
  prompt_version?: string;
  extractor_version?: string;
  asset_level?: KnowledgeAssetLevel;
  synthesis_type?: string;
  action_type?: string;
  why_useful?: string;
  use_case?: string;
  next_action?: string;
  expected_output?: string;
  risk_or_caveat?: string;
  priority?: "high" | "medium" | "low";
  supporting_card_ids?: string[];
  supporting_paper_ids?: string[];
  evidence_strength?: string;
}

export interface KnowledgeCardUpdateRequest {
  card_type?: KnowledgeCardType;
  title?: string;
  content?: string;
  paper_id?: string;
  source_page?: number;
  source_quote?: string;
  confidence?: number;
  status?: KnowledgeCardStatus;
  tags?: string;
  merged_into_id?: string;
  run_id?: string;
  source_kind?: string;
  source_ref?: string;
  normalized_key?: string;
  quality_flags?: string[];
  prompt_version?: string;
  extractor_version?: string;
  asset_level?: KnowledgeAssetLevel;
  synthesis_type?: string;
  action_type?: string;
  why_useful?: string;
  use_case?: string;
  next_action?: string;
  expected_output?: string;
  risk_or_caveat?: string;
  priority?: "high" | "medium" | "low";
  supporting_card_ids?: string[];
  supporting_paper_ids?: string[];
  evidence_strength?: string;
  reviewed_by?: string;
  allow_untraceable?: boolean;
}

export interface KnowledgeCardGenerateRequest {
  run_id?: string;
  paper_id?: string;
  force?: boolean;
  max_cards?: number;
  model?: string;
}

export interface KnowledgeCardGeneration {
  generation_id: string;
  paper_id: string;
  run_id: string;
  status: string;
  trigger_source: string;
  llm_model: string;
  prompt_version: string;
  extractor_version: string;
  source_hash: string;
  cards_created: number;
  cards_skipped: number;
  duplicate_count: number;
  critique_summary_json: string;
  error_msg: string;
  raw_output_json: string;
  card_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface KnowledgeCardBatchStatusRequest {
  card_ids: string[];
  status: KnowledgeCardStatus;
  allow_untraceable?: boolean;
  reviewed_by?: string;
}

export interface KnowledgeCardBatchMergeRequest {
  target_card_id: string;
  source_card_ids: string[];
}

export interface WritingSnippet {
  snippet_id: string;
  content: string;
  source_card_id: string;
  source_card_ids: string[];
  evidence_ids: string[];
  paragraph_plan_json: Record<string, unknown>;
  trace_mode: "traceable" | "clean" | string;
  usage_count: number;
  source_card_title: string;
  paper_id: string;
  paper_title: string;
  citation_key: string;
  source_page: number;
  source_quote: string;
  section_hint: SectionHint;
  created_at: string;
  updated_at: string;
}

export interface WritingSnippetCreateRequest {
  content: string;
  source_card_id?: string;
  source_card_ids?: string[];
  evidence_ids?: string[];
  paragraph_plan_json?: Record<string, unknown>;
  trace_mode?: "traceable" | "clean";
  paper_id?: string;
  citation_key?: string;
  source_page?: number;
  source_quote?: string;
  section_hint?: SectionHint;
}

export interface WritingSnippetUpdateRequest {
  content?: string;
  source_card_id?: string;
  source_card_ids?: string[];
  evidence_ids?: string[];
  paragraph_plan_json?: Record<string, unknown>;
  trace_mode?: "traceable" | "clean";
  paper_id?: string;
  citation_key?: string;
  source_page?: number;
  source_quote?: string;
  section_hint?: SectionHint;
}

export interface ComparisonTableRequest {
  paper_ids: string[];
}

export interface ComparisonTableRow {
  paper_id: string;
  title: string;
  citation_key: string;
  method: string;
  dataset: string;
  metric: string;
  result: string;
  limitation: string;
  conflicts?: string;
}

export interface ComparisonTableResponse {
  columns: string[];
  rows: ComparisonTableRow[];
}

export interface RelatedWorkComposeRequest {
  card_ids: string[];
  section_hint?: SectionHint;
  trace_mode?: "traceable" | "clean";
}

export interface LocalSearchResult {
  result_type: string;
  id: string;
  title: string;
  snippet: string;
  paper_id: string;
  paper_title: string;
  page: number;
  score: number;
  metadata: Record<string, string | number>;
}

export interface LocalSearchResponse {
  mode: LocalSearchMode;
  query: string;
  results: LocalSearchResult[];
}

export interface KnowledgeHealthIssue {
  issue_type: string;
  severity: string;
  count: number;
  label: string;
  paper_ids: string[];
  groups: DuplicateCandidate[];
}

export interface KnowledgeHealth {
  total_papers: number;
  unresolved_issues: number;
  unparsed_papers: number;
  sync_failed_papers: number;
  missing_metadata_papers: number;
  duplicate_candidates: number;
  stale_index_documents: number;
  read_without_notes: number;
  reading_without_cards: number;
  pending_ai_cards: number;
  verified_cards_without_evidence: number;
  draft_backlog_count: number;
  draft_backlog_avg_age_days: number;
  low_quality_ai_candidate_ratio: number;
  weak_synthesis_cards: number;
  gaps_missing_support_or_experiment: number;
  writing_snippets_missing_trace: number;
  local_qa_graph_hit_ratio: number;
  export_citation_missing_rate: number;
  isolated_evidence_count: number;
  issues: KnowledgeHealthIssue[];
}

export interface ExportResponse {
  content: string;
}

export interface ReferenceImportRequest {
  content: string;
  format: "bibtex" | "ris";
}

export interface ImportResponse {
  imported: number;
  skipped: number;
  paper_ids: string[];
}

export interface DuplicateCandidate {
  reason: string;
  key: string;
  paper_ids: string[];
  titles: string[];
}

export interface DuplicateCandidatesResponse {
  candidates: DuplicateCandidate[];
}

export interface HealthFixRequest {
  issue_type: string;
  paper_ids?: string[];
}

export interface HealthFixResponse {
  issue_type: string;
  fixed: number;
  message: string;
}

// --- Knowledge base (Dify) ---

export type SearchMethod = "keyword_search" | "full_text_search" | "semantic_search" | "hybrid_search";

export interface LibraryDataset {
  id: string;
  name: string;
  description?: string;
  document_count?: number;
  word_count?: number;
  created_at?: number;
  [key: string]: unknown;
}

export interface LibraryDatasetsResponse {
  data: LibraryDataset[];
  has_more?: boolean;
  total?: number;
  page?: number;
  limit?: number;
}

export interface LibraryStatusResponse {
  enabled: boolean;
  search_method: string;
  default_dataset_configured: boolean;
}

export interface LibraryDocument {
  id: string;
  name: string;
  word_count?: number;
  tokens?: number;
  indexing_status?: string;
  display_status?: string;
  enabled?: boolean;
  created_at?: number;
  [key: string]: unknown;
}

export interface LibraryDocumentsResponse {
  data: LibraryDocument[];
  has_more?: boolean;
  total?: number;
  page?: number;
  limit?: number;
}

export interface LibrarySearchRecord {
  document_id: string;
  document_name: string;
  segment_id: string;
  content: string;
  score: number | null;
  metadata?: unknown;
}

export interface LibrarySearchResponse {
  query: string;
  records: LibrarySearchRecord[];
}

export interface LibraryMarkdownResponse {
  document_id: string;
  document_name: string;
  markdown_file?: string;
  content: string;
}

export interface LibrarySource {
  idx: number;
  document_id: string;
  document_name: string;
  segment_id: string;
  score: number | null;
  source_type?: "dify" | "knowledge_graph" | string;
  card_id?: string;
  paper_id?: string;
  page?: number;
}

export interface LibraryAskResponse {
  markdown: string;
  sources: LibrarySource[];
  blocks_used: number;
  search_method: string;
  question: string;
}

export interface LibrarySearchRequest {
  query: string;
  top_k?: number;
  score_threshold?: number | null;
  search_method?: SearchMethod | null;
  dataset_id?: string;
}

export interface LibraryAskRequest {
  question: string;
  top_k?: number;
  search_method?: SearchMethod | null;
  language?: string;
  llm_model?: string;
  dataset_id?: string;
  graph_only?: boolean;
}
