from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --- Request models ---

class RunCreate(BaseModel):
    paper_id: str
    mode: Literal["snap", "lens", "sphere", "auto"] = "snap"
    llm_model: str = ""
    language: str = "en"        # en | zh
    question: str = ""          # required (non-empty) when mode == "auto"
    owner_token: str = ""       # per-browser token; scopes which runs the client sees


SearchMethod = Literal["keyword_search", "full_text_search", "semantic_search", "hybrid_search"]
ReadingStatus = Literal["unread", "skimmed", "reading", "read", "archived"]
PaperPriority = Literal["high", "medium", "low"]
ReadingDecision = Literal["must_read", "useful", "background", "discard", ""]
AnnotationType = Literal["highlight", "note", "question", "correction"]
KnowledgeCardType = Literal["claim", "method", "dataset", "metric", "result", "limitation", "question", "idea"]
KnowledgeCardStatus = Literal["draft", "verified", "rejected", "merged"]
CreatedBy = Literal["user", "ai"]
AiReviewStatus = Literal["trusted", "pending", "error", "valuable"]
SectionHint = Literal["related_work", "method", "experiment", "limitation", "idea_brief"]
LocalSearchMode = Literal["papers", "fragments", "cards", "relations", "writing"]
KnowledgeAssetLevel = Literal["evidence", "synthesis", "action"]
KnowledgePriority = Literal["high", "medium", "low"]


class LibrarySearchRequest(BaseModel):
    query: str
    top_k: int = 10
    score_threshold: float | None = None
    search_method: SearchMethod | None = None   # defaults to DIFY_SEARCH_METHOD
    dataset_id: str = ""                          # empty → project/proxy default dataset


class LibraryAskRequest(BaseModel):
    question: str
    top_k: int = 10
    search_method: SearchMethod | None = None   # defaults to DIFY_SEARCH_METHOD
    language: str = "en"        # en | zh
    llm_model: str = ""
    dataset_id: str = ""
    dataset_ids: list[str] = []
    graph_only: bool = False
    force_refresh: bool = False


class TranslatorRequest(BaseModel):
    text: str = Field(default="", max_length=120_000)
    source_lang: str = "auto"
    target_lang: str = "zh"
    model_type: Literal["latency_optimized", "quality_optimized", "prefer_quality_optimized", ""] = ""


class PaperLifecycleUpdateRequest(BaseModel):
    reading_status: ReadingStatus | None = None
    priority: PaperPriority | None = None
    decision: ReadingDecision | None = None
    personal_rating: int | None = None
    read_progress: float | None = None
    last_read_at: str | None = None


class PaperBulkLifecycleUpdateRequest(BaseModel):
    paper_ids: list[str]
    reading_status: ReadingStatus | None = None
    priority: PaperPriority | None = None
    decision: ReadingDecision | None = None


class PaperAnnotationCreateRequest(BaseModel):
    paper_id: str = ""
    page: int = 0
    quote: str = ""
    note: str = ""
    annotation_type: AnnotationType = "highlight"
    color: str = "yellow"
    bbox_json: str = "[]"


class PaperAnnotationUpdateRequest(BaseModel):
    page: int | None = None
    quote: str | None = None
    note: str | None = None
    annotation_type: AnnotationType | None = None
    color: str | None = None
    bbox_json: str | None = None


class PaperNoteUpdateRequest(BaseModel):
    summary_user: str = ""
    key_takeaways: str = ""
    open_questions: str = ""
    reading_decision: str = ""


class AiReviewMarkCreateRequest(BaseModel):
    paper_id: str
    run_id: str = ""
    source_ref: str = ""
    quote: str = ""
    status: AiReviewStatus = "pending"
    note: str = ""


class AiReviewMarkUpdateRequest(BaseModel):
    status: AiReviewStatus | None = None
    note: str | None = None


class KnowledgeCardCreateRequest(BaseModel):
    card_type: KnowledgeCardType = "claim"
    title: str
    content: str = ""
    paper_id: str = ""
    source_page: int = 0
    source_quote: str = ""
    confidence: float = 0.0
    status: KnowledgeCardStatus = "draft"
    tags: str = ""
    created_by: CreatedBy = "user"
    evidence_ids: list[str] = []
    run_id: str = ""
    source_kind: str = ""
    source_ref: str = ""
    normalized_key: str = ""
    quality_flags: list[str] = []
    prompt_version: str = ""
    extractor_version: str = ""
    asset_level: KnowledgeAssetLevel = "evidence"
    synthesis_type: str = ""
    action_type: str = ""
    why_useful: str = ""
    use_case: str = ""
    next_action: str = ""
    expected_output: str = ""
    risk_or_caveat: str = ""
    priority: KnowledgePriority = "medium"
    supporting_card_ids: list[str] = []
    supporting_paper_ids: list[str] = []
    evidence_strength: str = ""


class KnowledgeCardUpdateRequest(BaseModel):
    card_type: KnowledgeCardType | None = None
    title: str | None = None
    content: str | None = None
    paper_id: str | None = None
    source_page: int | None = None
    source_quote: str | None = None
    confidence: float | None = None
    status: KnowledgeCardStatus | None = None
    tags: str | None = None
    merged_into_id: str | None = None
    run_id: str | None = None
    source_kind: str | None = None
    source_ref: str | None = None
    normalized_key: str | None = None
    quality_flags: list[str] | None = None
    prompt_version: str | None = None
    extractor_version: str | None = None
    asset_level: KnowledgeAssetLevel | None = None
    synthesis_type: str | None = None
    action_type: str | None = None
    why_useful: str | None = None
    use_case: str | None = None
    next_action: str | None = None
    expected_output: str | None = None
    risk_or_caveat: str | None = None
    priority: KnowledgePriority | None = None
    supporting_card_ids: list[str] | None = None
    supporting_paper_ids: list[str] | None = None
    evidence_strength: str | None = None
    reviewed_by: str | None = None
    allow_untraceable: bool | None = None


class KnowledgeCardMergeRequest(BaseModel):
    target_card_id: str


class KnowledgeCardGenerateRequest(BaseModel):
    run_id: str = ""
    paper_id: str = ""
    force: bool = False
    max_cards: int = 12
    model: str = ""


class KnowledgeCardBatchStatusRequest(BaseModel):
    card_ids: list[str]
    status: KnowledgeCardStatus
    allow_untraceable: bool = False
    reviewed_by: str = ""


class KnowledgeCardBatchMergeRequest(BaseModel):
    target_card_id: str
    source_card_ids: list[str]


class WritingSnippetCreateRequest(BaseModel):
    content: str
    source_card_id: str = ""
    source_card_ids: list[str] = []
    evidence_ids: list[str] = []
    paragraph_plan_json: dict[str, Any] = {}
    trace_mode: Literal["traceable", "clean"] = "traceable"
    paper_id: str = ""
    citation_key: str = ""
    source_page: int = 0
    source_quote: str = ""
    section_hint: SectionHint = "related_work"


class WritingSnippetUpdateRequest(BaseModel):
    content: str | None = None
    source_card_id: str | None = None
    source_card_ids: list[str] | None = None
    evidence_ids: list[str] | None = None
    paragraph_plan_json: dict[str, Any] | None = None
    trace_mode: Literal["traceable", "clean"] | None = None
    paper_id: str | None = None
    citation_key: str | None = None
    source_page: int | None = None
    source_quote: str | None = None
    section_hint: SectionHint | None = None


class ComparisonTableRequest(BaseModel):
    paper_ids: list[str]


class RelatedWorkComposeRequest(BaseModel):
    card_ids: list[str]
    section_hint: SectionHint = "related_work"
    trace_mode: Literal["traceable", "clean"] = "traceable"


class ReferenceImportRequest(BaseModel):
    content: str
    format: Literal["bibtex", "ris"] = "bibtex"


class HealthFixRequest(BaseModel):
    issue_type: str
    paper_ids: list[str] = []


class DailyRecommendationRefreshRequest(BaseModel):
    date: str = ""
    topic_id: str = ""
    force: bool = False


class DailyRecommendationFeedbackRequest(BaseModel):
    action: Literal["interested", "irrelevant", "dismissed"]
    note: str = ""


class DailyRecommendationIngestRequest(BaseModel):
    mode: Literal["snap", "lens", "sphere", "auto"] = "lens"
    parse_mode: Literal["snap", "lens", "sphere", "auto"] | None = None
    language: str = "zh"
    llm_model: str = ""
    collection_id: str = ""
    source_space_id: str = "daily_source"
    analysis_space_id: str = "daily_analysis"
    sync_to_dify: bool = True
    ingest_source_only: bool = False
    start_run: bool = True
    owner_token: str = ""


class KnowledgeSpaceItemRef(BaseModel):
    space_id: str
    item_kind: Literal["paper", "run", "dify_document", "card", "snippet"]
    item_id: str


class KnowledgeSpaceItemMoveRequest(KnowledgeSpaceItemRef):
    target_space_id: str


class KnowledgeSpaceItemCopyRequest(KnowledgeSpaceItemRef):
    target_space_id: str


class KnowledgeSpaceItemRemoveRequest(KnowledgeSpaceItemRef):
    pass


class KnowledgeSpaceUpdateRequest(BaseModel):
    name: str | None = None
    name_zh: str | None = None
    description: str | None = None
    description_zh: str | None = None
    dify_dataset_id: str | None = None
    sort_order: int | None = None


class KnowledgeSpaceItemUpdateRequest(KnowledgeSpaceItemRef):
    note: str | None = None
    sync_status: Literal["pending", "running", "synced", "failed", "skipped"] | None = None
    dify_document_id: str | None = None


class KnowledgeSpaceItemResyncRequest(KnowledgeSpaceItemRef):
    force: bool = True


class KnowledgeSpaceDifyDatasetCreateRequest(BaseModel):
    name: str = ""
    indexing_technique: str = "economy"
    permission: str = "only_me"


class DailyRecommendationPromoteRequest(BaseModel):
    source_target_space_id: str = "main_source"
    analysis_target_space_id: str = "main_analysis"
    copy_item: bool = Field(default=True, alias="copy")


# --- Response models ---

class PaperResponse(BaseModel):
    paper_id: str
    title: str
    doi: str
    venue: str = ""
    year: int = 0
    sci_rank: str = ""
    ccf_rank: str = ""
    citation_key: str = ""
    reading_status: str = "unread"
    priority: str = "medium"
    decision: str = ""
    personal_rating: int = 0
    read_progress: float = 0.0
    last_read_at: str = ""
    created_at: str


class PaperUploadResponse(BaseModel):
    paper_id: str
    message: str


class PaperDisplayResponse(BaseModel):
    title_zh: str = ""
    summary_en: str = ""
    summary_zh: str = ""
    translation_status: str = "pending"
    updated_at: str = ""


class PaperCollectionResponse(BaseModel):
    collection_id: str
    parent_id: str = ""
    name: str
    name_zh: str = ""
    description: str = ""
    description_zh: str = ""
    sort_order: int = 0
    paper_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class PaperCollectionItemResponse(BaseModel):
    collection_id: str
    paper_id: str
    is_primary: bool = False
    note: str = ""
    note_zh: str = ""
    sort_order: int = 0
    updated_at: str = ""


class PaperCollectionsResponse(BaseModel):
    collections: list[PaperCollectionResponse] = []
    items: list[PaperCollectionItemResponse] = []


class PaperCollectionCreateRequest(BaseModel):
    name: str
    name_zh: str = ""
    description: str = ""
    description_zh: str = ""
    parent_id: str = ""


class PaperCollectionUpdateRequest(BaseModel):
    name: str | None = None
    name_zh: str | None = None
    description: str | None = None
    description_zh: str | None = None
    parent_id: str | None = None


class PaperCollectionAssignRequest(BaseModel):
    collection_id: str
    is_primary: bool = True
    note: str = ""


class PaperUpdateRequest(BaseModel):
    title: str | None = None
    title_zh: str | None = None
    summary_zh: str | None = None
    doi: str | None = None
    venue: str | None = None
    year: int | None = None
    sci_rank: str | None = None
    ccf_rank: str | None = None
    citation_key: str | None = None


class PaperCollectionSuggestion(BaseModel):
    mode: Literal["existing", "new"] = "new"
    collection_id: str = ""
    new_name: str = ""
    new_name_zh: str = ""
    new_description: str = ""
    new_description_zh: str = ""
    confidence: float = 0.0
    reason: str = ""


class PaperCollectionSuggestRequest(BaseModel):
    llm_model: str = ""


class PaperCollectionSuggestResponse(BaseModel):
    paper_id: str
    paper_title: str = ""
    paper_title_zh: str = ""
    summary_zh: str = ""
    summary_en: str = ""
    suggestion: PaperCollectionSuggestion
    collections: list[PaperCollectionResponse] = []


class PaperCollectionConfirmRequest(BaseModel):
    collection_id: str = ""
    new_name: str = ""
    new_name_zh: str = ""
    new_description: str = ""
    new_description_zh: str = ""
    parent_id: str = ""
    note: str = ""


class PaperCollectionConfirmResponse(BaseModel):
    collection: PaperCollectionResponse
    item: PaperCollectionItemResponse


class DiscoveryGapStatusRequest(BaseModel):
    status: Literal[
        "kept",
        "candidate",
        "reviewing",
        "pursue",
        "experiment_planned",
        "needs_more_evidence",
        "promoted_to_idea",
        "rejected",
        "covered",
    ]
    rejection_reason: str = ""
    research_question: str = ""
    target_task: str = ""
    constraints_json: list[str] = []
    baseline_plan: str = ""
    contribution: str = ""
    target_venue: str = ""
    minimum_experiment: str = ""


class DiscoveryRelationStatusRequest(BaseModel):
    status: Literal["confirmed", "verified", "needs_more_evidence", "rejected", "unverified"]


class ResearchConstructionRequest(BaseModel):
    force: bool = False
    dry_run: bool = False


class ResearchConstructionFeedbackRequest(BaseModel):
    verdict: Literal["up", "down", "accepted", "rejected"]
    reason: str = ""


class ResearchConstructionJobResponse(BaseModel):
    job_id: str
    trigger_source: str = "manual"
    dry_run: bool = False
    status: str = "pending"
    progress: dict[str, Any] = {}
    estimate: dict[str, Any] = {}
    result: dict[str, Any] = {}
    error_msg: str = ""
    started_at: str = ""
    finished_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class ModelListResponse(BaseModel):
    """Selectable LLM models offered to the frontend dropdown."""
    models: list[str]
    default: str


class LLMSettingsResponse(BaseModel):
    base_url: str = ""
    thinking_model: str = ""
    models: list[str] = []
    default: str = ""
    reasoning_effort: str = "medium"
    reasoning_efforts: list[str] = []
    api_key_configured: bool = False
    api_key_suffix: str = ""
    source: str = "env"


class LLMSettingsUpdateRequest(BaseModel):
    base_url: str
    thinking_model: str
    reasoning_effort: str = "medium"
    api_key: str = ""
    clear_api_key: bool = False


class LLMConnectionTestRequest(LLMSettingsUpdateRequest):
    use_saved_api_key: bool = True


class LLMConnectionTestResponse(BaseModel):
    ok: bool
    base_url: str = ""
    model: str = ""
    endpoint: str = ""
    status_code: int = 0
    elapsed_ms: int = 0
    message: str = ""
    error: str = ""


class TranslatorResponse(BaseModel):
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    status: str
    provider: str = "deeplx"
    error_msg: str = ""


class DailyRecommendationTopicResponse(BaseModel):
    topic_id: str
    name: str
    name_zh: str = ""
    enabled: bool = True
    sort_order: int = 0
    config: dict = {}


class DailyRecommendationItemResponse(BaseModel):
    item_id: str
    arxiv_id: str
    topic_id: str
    title_en: str
    title_zh: str = ""
    abstract_en: str
    abstract_zh: str = ""
    authors: list[str] = []
    primary_category: str = ""
    categories: list[str] = []
    published_at: str = ""
    updated_at: str = ""
    arxiv_url: str = ""
    pdf_url: str = ""
    score: float = 0.0
    score_detail: dict = {}
    reason: str = ""
    title_translation_status: str = "pending"
    abstract_translation_status: str = "pending"
    llm_review_status: str = "not_needed"
    status: str = "candidate"
    linked_paper_id: str = ""
    linked_run_id: str = ""
    error_msg: str = ""
    fetched_date: str = ""
    created_at: str = ""


class DailyRecommendationListResponse(BaseModel):
    date: str
    topics: list[DailyRecommendationTopicResponse] = []
    items: list[DailyRecommendationItemResponse] = []
    total: int = 0
    limit: int = 20
    offset: int = 0
    has_more: bool = False


class DailyRecommendationRefreshResponse(BaseModel):
    job_id: str = ""
    status: str = ""
    date: str
    fetched: int = 0
    inserted_or_updated: int = 0
    kept: int = 0
    skipped: int = 0
    message: str = ""
    errors: list[dict[str, str]] = []
    started_at: str = ""
    finished_at: str = ""


class DailyRecommendationIngestResponse(BaseModel):
    item_id: str
    paper_id: str
    run_id: str = ""
    status: str
    message: str = ""


class KnowledgeSpaceResponse(BaseModel):
    space_id: str
    name: str
    name_zh: str = ""
    space_type: str = ""
    description: str = ""
    description_zh: str = ""
    dify_dataset_id: str = ""
    is_system: bool = False
    sort_order: int = 0
    item_count: int = 0
    paper_count: int = 0
    run_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class KnowledgeSpaceItemResponse(BaseModel):
    space_id: str
    item_kind: str
    item_id: str
    paper_id: str = ""
    run_id: str = ""
    source_type: str = ""
    sync_status: str = "pending"
    dify_document_id: str = ""
    note: str = ""
    paper_title: str = ""
    paper_title_zh: str = ""
    original_filename: str = ""
    run_mode: str = ""
    run_status: str = ""
    run_started_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class KnowledgeSpacesResponse(BaseModel):
    spaces: list[KnowledgeSpaceResponse] = []


class KnowledgeSpaceItemsResponse(BaseModel):
    space: KnowledgeSpaceResponse
    items: list[KnowledgeSpaceItemResponse] = []


class KnowledgeSpaceDifyDatasetResponse(BaseModel):
    space: KnowledgeSpaceResponse
    dataset: dict = {}


class KnowledgeSpaceDifyDocumentsResponse(BaseModel):
    space: KnowledgeSpaceResponse
    data: list[dict] = []
    has_more: bool = False
    total: int = 0
    page: int = 1
    limit: int = 20


class KnowledgeSpaceDifyMarkdownResponse(BaseModel):
    space: KnowledgeSpaceResponse
    content: str = ""
    document_name: str = ""
    raw: dict = {}


class LibraryStatusResponse(BaseModel):
    enabled: bool
    search_method: str
    default_dataset_configured: bool


class RunResponse(BaseModel):
    run_id: str
    paper_id: str
    mode: str                          # post-classification mode (may be snap|lens|sphere|qa)
    llm_model: str
    language: str = "en"
    status: str
    error_msg: str
    started_at: str
    finished_at: str | None
    user_question: str = ""
    detected_intent: str = ""
    current_step: str = ""
    progress_json: str = "[]"


class RecentRunResponse(BaseModel):
    run_id: str
    paper_id: str
    paper_title: str = ""
    mode: str
    status: str
    started_at: str
    finished_at: str | None
    current_step: str = ""
    user_question: str = ""


class PaperRunSummary(BaseModel):
    run_id: str
    mode: str
    status: str
    started_at: str
    finished_at: str | None
    current_step: str = ""
    user_question: str = ""


class DifySyncStatusResponse(BaseModel):
    paper_id: str
    dataset_id: str = ""
    document_id: str = ""
    source_hash: str = ""
    status: str = "not_synced"
    attempts: int = 0
    error_msg: str = ""
    updated_at: str = ""


class AnalysisDifySyncStatusResponse(BaseModel):
    run_id: str
    paper_id: str
    dataset_id: str = ""
    document_id: str = ""
    source_hash: str = ""
    status: str = "not_synced"
    attempts: int = 0
    error_msg: str = ""
    updated_at: str = ""


class PaperLibraryItemResponse(BaseModel):
    paper_id: str
    title: str
    doi: str = ""
    venue: str = ""
    year: int = 0
    sci_rank: str = ""
    ccf_rank: str = ""
    citation_key: str = ""
    reading_status: str = "unread"
    priority: str = "medium"
    decision: str = ""
    personal_rating: int = 0
    read_progress: float = 0.0
    last_read_at: str = ""
    created_at: str
    parse_status: str = ""
    parse_updated_at: str = ""
    primary_collection_id: str = ""
    collection_ids: list[str] = []
    display: PaperDisplayResponse = Field(default_factory=PaperDisplayResponse)
    latest_run: PaperRunSummary | None = None
    runs: list[PaperRunSummary] = []
    dify_sync: DifySyncStatusResponse


class PaperSyncStatusResponse(BaseModel):
    paper: DifySyncStatusResponse
    analysis: list[AnalysisDifySyncStatusResponse] = []


class DiscoveryStatsResponse(BaseModel):
    total_papers: int
    parsed_papers: int
    analyzed_papers: int
    synced_papers: int
    year_range: str = ""
    evidence_items: int = 0
    relation_edges: int = 0
    gap_candidates: int = 0
    discovery_version: int = 1


class DiscoveryEvidenceResponse(BaseModel):
    evidence_id: str
    evidence_type: str
    paper_id: str
    block_id: int = 0
    page: int = 0
    quote: str
    normalized_label: str
    taxonomy_path: str
    confidence: float
    extractor: str = ""
    model_version: str = ""
    prompt_version: str = ""
    status: str = "unverified"
    revision_history: list[dict[str, Any]] = []
    evidence_version: int = 1


class DiscoveryThemeResponse(BaseModel):
    theme_id: str
    name: str
    paper_count: int
    keywords: list[str] = []
    paper_ids: list[str] = []
    taxonomy_path: str = ""


class DiscoveryNodeResponse(BaseModel):
    paper_id: str
    title: str
    year: int = 0
    venue: str = ""
    theme_ids: list[str] = []
    status: str = ""
    evidence_count: int = 0


class DiscoveryEdgeResponse(BaseModel):
    source: str
    target: str
    weight: float
    relation: str
    evidence: list[str] = []
    relation_id: str = ""
    source_evidence_ids: list[str] = []
    target_evidence_ids: list[str] = []
    rule_id: str = ""
    positive_checks: list[str] = []
    negative_checks: list[str] = []
    counter_evidence_ids: list[str] = []
    comparability_json: dict[str, Any] = {}
    confidence: float = 0.0
    status: str = "unverified"
    verifier_version: str = ""
    relation_version: int = 1


class DiscoveryScoreResponse(BaseModel):
    novelty: float = 0.0
    feasibility: float = 0.0
    evidence_strength: float = 0.0
    risk: float = 0.0
    experiment_cost: float = 0.0
    domain_value: float = 0.0


class DiscoveryGapResponse(BaseModel):
    gap_id: str
    title: str
    description: str
    full_description: str = ""
    score: float
    paper_ids: list[str] = []
    signals: list[str] = []
    question: str = ""
    hypothesis: str = ""
    support_evidence_ids: list[str] = []
    counter_evidence_ids: list[str] = []
    related_synthesis_card_ids: list[str] = []
    related_card_ids: list[str] = []
    research_question: str = ""
    target_task: str = ""
    constraints_json: list[str] = []
    baseline_plan: str = ""
    contribution: str = ""
    target_venue: str = ""
    history_json: list[dict[str, Any]] = []
    coverage_status: str = "unknown"
    scores: DiscoveryScoreResponse = Field(default_factory=DiscoveryScoreResponse)
    status: str = "candidate"
    rejection_reason: str = ""
    minimum_experiment: str = ""
    hit_by_paper_ids: list[str] = []
    gap_version: int = 1


class DiscoveryReadingPathResponse(BaseModel):
    path_id: str
    title: str
    description: str
    paper_ids: list[str] = []


class PapersDiscoveryResponse(BaseModel):
    stats: DiscoveryStatsResponse
    themes: list[DiscoveryThemeResponse] = []
    nodes: list[DiscoveryNodeResponse] = []
    edges: list[DiscoveryEdgeResponse] = []
    gaps: list[DiscoveryGapResponse] = []
    reading_paths: list[DiscoveryReadingPathResponse] = []
    evidence: list[DiscoveryEvidenceResponse] = []


class RunOutputResponse(BaseModel):
    run_id: str
    markdown: str
    json_data: str


class BlockResponse(BaseModel):
    block_id: int
    paper_id: str
    type: str
    sub_type: str
    page_idx: int
    bbox_json: str
    text: str
    section_path: str
    order_idx: int


class PaperAnnotationResponse(BaseModel):
    annotation_id: str
    paper_id: str
    page: int = 0
    quote: str = ""
    note: str = ""
    annotation_type: str = "highlight"
    color: str = "yellow"
    bbox_json: str = "[]"
    created_at: str = ""
    updated_at: str = ""


class PaperNoteResponse(BaseModel):
    paper_id: str
    summary_user: str = ""
    key_takeaways: str = ""
    open_questions: str = ""
    reading_decision: str = ""
    created_at: str = ""
    updated_at: str = ""


class AiReviewMarkResponse(BaseModel):
    mark_id: str
    paper_id: str
    run_id: str = ""
    source_ref: str = ""
    quote: str = ""
    status: str = "pending"
    note: str = ""
    created_at: str = ""
    updated_at: str = ""


class KnowledgeCardResponse(BaseModel):
    card_id: str
    card_type: str
    title: str
    content: str = ""
    paper_id: str = ""
    paper_title: str = ""
    source_page: int = 0
    source_quote: str = ""
    confidence: float = 0.0
    status: str = "draft"
    tags: str = ""
    created_by: str = "user"
    merged_into_id: str = ""
    evidence_ids: list[str] = []
    citation_key: str = ""
    run_id: str = ""
    source_kind: str = ""
    source_ref: str = ""
    normalized_key: str = ""
    quality_flags: list[str] = []
    prompt_version: str = ""
    extractor_version: str = ""
    asset_level: str = "evidence"
    synthesis_type: str = ""
    action_type: str = ""
    why_useful: str = ""
    use_case: str = ""
    next_action: str = ""
    expected_output: str = ""
    risk_or_caveat: str = ""
    priority: str = "medium"
    supporting_card_ids: list[str] = []
    supporting_paper_ids: list[str] = []
    evidence_strength: str = ""
    card_version: int = 1
    revision_history: str = "[]"
    reviewed_at: str = ""
    reviewed_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class KnowledgeCardGenerationResponse(BaseModel):
    generation_id: str
    paper_id: str = ""
    run_id: str = ""
    status: str = "pending"
    trigger_source: str = "run_completed"
    llm_model: str = ""
    prompt_version: str = ""
    extractor_version: str = ""
    source_hash: str = ""
    cards_created: int = 0
    cards_skipped: int = 0
    duplicate_count: int = 0
    critique_summary_json: str = "{}"
    error_msg: str = ""
    raw_output_json: str = "[]"
    card_ids: list[str] = []
    created_at: str = ""
    updated_at: str = ""


class WritingSnippetResponse(BaseModel):
    snippet_id: str
    content: str
    source_card_id: str = ""
    source_card_ids: list[str] = []
    evidence_ids: list[str] = []
    paragraph_plan_json: dict[str, Any] = {}
    trace_mode: str = "traceable"
    usage_count: int = 0
    source_card_title: str = ""
    paper_id: str = ""
    paper_title: str = ""
    citation_key: str = ""
    source_page: int = 0
    source_quote: str = ""
    section_hint: str = "related_work"
    created_at: str = ""
    updated_at: str = ""


class LocalSearchResultResponse(BaseModel):
    result_type: str
    id: str
    title: str
    snippet: str = ""
    paper_id: str = ""
    paper_title: str = ""
    page: int = 0
    score: float = 0.0
    metadata: dict[str, str | int | float] = {}


class LocalSearchResponse(BaseModel):
    mode: str
    query: str
    results: list[LocalSearchResultResponse] = []


class KnowledgeHealthIssueResponse(BaseModel):
    issue_type: str
    severity: str
    count: int
    label: str
    paper_ids: list[str] = []
    groups: list[dict[str, str | list[str]]] = []


class KnowledgeHealthResponse(BaseModel):
    total_papers: int = 0
    unresolved_issues: int = 0
    unparsed_papers: int = 0
    sync_failed_papers: int = 0
    missing_metadata_papers: int = 0
    duplicate_candidates: int = 0
    stale_index_documents: int = 0
    read_without_notes: int = 0
    reading_without_cards: int = 0
    pending_ai_cards: int = 0
    verified_cards_without_evidence: int = 0
    draft_backlog_count: int = 0
    draft_backlog_avg_age_days: float = 0.0
    low_quality_ai_candidate_ratio: float = 0.0
    weak_synthesis_cards: int = 0
    gaps_missing_support_or_experiment: int = 0
    writing_snippets_missing_trace: int = 0
    local_qa_graph_hit_ratio: float = 0.0
    export_citation_missing_rate: float = 0.0
    isolated_evidence_count: int = 0
    issues: list[KnowledgeHealthIssueResponse] = []


class ExportResponse(BaseModel):
    content: str


class ImportResponse(BaseModel):
    imported: int = 0
    skipped: int = 0
    paper_ids: list[str] = []


class DuplicateCandidateResponse(BaseModel):
    reason: str
    key: str
    paper_ids: list[str]
    titles: list[str] = []


class DuplicateCandidatesResponse(BaseModel):
    candidates: list[DuplicateCandidateResponse] = []


class HealthFixResponse(BaseModel):
    issue_type: str
    fixed: int = 0
    message: str = ""
