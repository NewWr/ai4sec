-- Scholar Platform Database Schema

CREATE TABLE IF NOT EXISTS papers (
    paper_id   TEXT PRIMARY KEY,             -- sha1(pdf_bytes)
    file_path  TEXT NOT NULL,                -- relative to data_dir
    original_filename TEXT DEFAULT '',
    title      TEXT DEFAULT '',
    doi        TEXT DEFAULT '',
    venue      TEXT DEFAULT '',              -- journal/conference name from Crossref
    year       INTEGER DEFAULT 0,            -- publication year
    sci_rank   TEXT DEFAULT '',              -- SCI tier: Q1/Q2/Q3/Q4
    ccf_rank   TEXT DEFAULT '',              -- CCF rating: A/B/C
    citation_key TEXT NOT NULL DEFAULT '',
    reading_status TEXT NOT NULL DEFAULT 'unread', -- unread | skimmed | reading | read | archived
    priority   TEXT NOT NULL DEFAULT 'medium',     -- high | medium | low
    decision   TEXT NOT NULL DEFAULT '',           -- must_read | useful | background | discard
    personal_rating INTEGER NOT NULL DEFAULT 0,
    read_progress REAL NOT NULL DEFAULT 0.0,
    last_read_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS translation_cache (
    text_hash       TEXT NOT NULL,
    source_lang     TEXT NOT NULL DEFAULT 'auto',
    target_lang     TEXT NOT NULL DEFAULT 'zh',
    provider        TEXT NOT NULL DEFAULT 'deeplx',
    source_text     TEXT NOT NULL DEFAULT '',
    translated_text TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'done', -- done | skipped | failed
    error_msg       TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (text_hash, source_lang, target_lang, provider)
);
CREATE INDEX IF NOT EXISTS idx_translation_cache_target ON translation_cache(target_lang, provider, updated_at DESC);

CREATE TABLE IF NOT EXISTS daily_recommendation_topics (
    topic_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    name_zh TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_recommendation_items (
    item_id TEXT PRIMARY KEY,
    arxiv_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    title_en TEXT NOT NULL DEFAULT '',
    title_zh TEXT NOT NULL DEFAULT '',
    abstract_en TEXT NOT NULL DEFAULT '',
    abstract_zh TEXT NOT NULL DEFAULT '',
    authors_json TEXT NOT NULL DEFAULT '[]',
    primary_category TEXT NOT NULL DEFAULT '',
    categories_json TEXT NOT NULL DEFAULT '[]',
    published_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    arxiv_url TEXT NOT NULL DEFAULT '',
    pdf_url TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0.0,
    score_detail_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    title_translation_status TEXT NOT NULL DEFAULT 'pending',
    abstract_translation_status TEXT NOT NULL DEFAULT 'pending',
    llm_review_status TEXT NOT NULL DEFAULT 'not_needed',
    llm_review_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'candidate',
    linked_paper_id TEXT NOT NULL DEFAULT '',
    linked_run_id TEXT NOT NULL DEFAULT '',
    error_msg TEXT NOT NULL DEFAULT '',
    fetched_date TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(arxiv_id, topic_id, fetched_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_items_date_topic
    ON daily_recommendation_items(fetched_date, topic_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_daily_items_status
    ON daily_recommendation_items(status, fetched_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_items_arxiv
    ON daily_recommendation_items(arxiv_id, fetched_date DESC);

CREATE TABLE IF NOT EXISTS daily_recommendation_feedback (
    feedback_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES daily_recommendation_items(item_id),
    arxiv_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_daily_feedback_topic_action
    ON daily_recommendation_feedback(topic_id, action, created_at DESC);

CREATE TABLE IF NOT EXISTS external_sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '',
    repo_owner TEXT NOT NULL DEFAULT '',
    repo_name TEXT NOT NULL DEFAULT '',
    branch TEXT NOT NULL DEFAULT 'main',
    docs_path TEXT NOT NULL DEFAULT 'docs',
    homepage_url TEXT NOT NULL DEFAULT '',
    license_name TEXT NOT NULL DEFAULT '',
    license_url TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    last_commit_sha TEXT NOT NULL DEFAULT '',
    last_synced_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS external_paper_notes (
    note_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL DEFAULT 'paper_notes',
    source_path TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    raw_url TEXT NOT NULL DEFAULT '',
    commit_sha TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    conference TEXT NOT NULL DEFAULT '',
    year INTEGER NOT NULL DEFAULT 0,
    domain TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    title_zh TEXT NOT NULL DEFAULT '',
    arxiv_id TEXT NOT NULL DEFAULT '',
    arxiv_url TEXT NOT NULL DEFAULT '',
    pdf_url TEXT NOT NULL DEFAULT '',
    code_url TEXT NOT NULL DEFAULT '',
    project_url TEXT NOT NULL DEFAULT '',
    authors_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    experiments TEXT NOT NULL DEFAULT '',
    limitations TEXT NOT NULL DEFAULT '',
    related_papers_json TEXT NOT NULL DEFAULT '[]',
    markdown TEXT NOT NULL DEFAULT '',
    parsed_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'new',
    utility_score REAL NOT NULL DEFAULT 0.0,
    utility_reason TEXT NOT NULL DEFAULT '',
    linked_paper_id TEXT NOT NULL DEFAULT '',
    linked_daily_item_id TEXT NOT NULL DEFAULT '',
    linked_run_id TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'not_synced',
    dify_document_id TEXT NOT NULL DEFAULT '',
    error_msg TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, source_path)
);
CREATE INDEX IF NOT EXISTS idx_external_notes_score
    ON external_paper_notes(utility_score DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_external_notes_filters
    ON external_paper_notes(conference, year, domain, status);
CREATE INDEX IF NOT EXISTS idx_external_notes_arxiv
    ON external_paper_notes(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_external_notes_linked_paper
    ON external_paper_notes(linked_paper_id);

CREATE TABLE IF NOT EXISTS external_note_versions (
    version_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES external_paper_notes(note_id),
    source_id TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    commit_sha TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    markdown TEXT NOT NULL DEFAULT '',
    parsed_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(note_id, content_hash)
);

CREATE TABLE IF NOT EXISTS external_note_sync_runs (
    sync_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    commit_sha TEXT NOT NULL DEFAULT '',
    scanned INTEGER NOT NULL DEFAULT 0,
    fetched INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    error_json TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_external_sync_runs_source_created
    ON external_note_sync_runs(source_id, created_at DESC);

CREATE TABLE IF NOT EXISTS external_note_matches (
    match_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES external_paper_notes(note_id),
    target_kind TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    match_type TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(note_id, target_kind, target_id, match_type)
);
CREATE INDEX IF NOT EXISTS idx_external_matches_note
    ON external_note_matches(note_id, target_kind);
CREATE INDEX IF NOT EXISTS idx_external_matches_target
    ON external_note_matches(target_kind, target_id);

CREATE TABLE IF NOT EXISTS paper_display_cache (
    paper_id           TEXT PRIMARY KEY REFERENCES papers(paper_id),
    title_zh           TEXT NOT NULL DEFAULT '',
    summary_source     TEXT NOT NULL DEFAULT '',
    summary_en         TEXT NOT NULL DEFAULT '',
    summary_zh         TEXT NOT NULL DEFAULT '',
    source_hash        TEXT NOT NULL DEFAULT '',
    translation_status TEXT NOT NULL DEFAULT 'pending',
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS paper_collections (
    collection_id  TEXT PRIMARY KEY,
    parent_id      TEXT NOT NULL DEFAULT '',
    name           TEXT NOT NULL DEFAULT '',
    name_zh        TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    description_zh TEXT NOT NULL DEFAULT '',
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_paper_collections_parent ON paper_collections(parent_id, sort_order, name);

CREATE TABLE IF NOT EXISTS paper_collection_items (
    collection_id TEXT NOT NULL REFERENCES paper_collections(collection_id),
    paper_id      TEXT NOT NULL REFERENCES papers(paper_id),
    is_primary    INTEGER NOT NULL DEFAULT 0,
    note          TEXT NOT NULL DEFAULT '',
    note_zh       TEXT NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collection_id, paper_id)
);
CREATE INDEX IF NOT EXISTS idx_paper_collection_items_paper ON paper_collection_items(paper_id, is_primary DESC);
CREATE INDEX IF NOT EXISTS idx_paper_collection_items_collection ON paper_collection_items(collection_id, paper_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_collection_items_primary
    ON paper_collection_items(paper_id)
    WHERE is_primary = 1;

CREATE TABLE IF NOT EXISTS mineru_parses (
    parse_id   TEXT PRIMARY KEY,
    paper_id   TEXT NOT NULL REFERENCES papers(paper_id),
    backend    TEXT NOT NULL DEFAULT 'vlm',  -- vlm | pipeline
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
    output_dir TEXT DEFAULT '',
    error_msg  TEXT DEFAULT '',
    remote_batch_id TEXT DEFAULT '',
    poll_count INTEGER DEFAULT 0,
    last_state_counts TEXT DEFAULT '',
    last_poll_at TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mineru_parses_paper ON mineru_parses(paper_id);
CREATE INDEX IF NOT EXISTS idx_mineru_parses_paper_created ON mineru_parses(paper_id, created_at DESC);

CREATE TABLE IF NOT EXISTS blocks (
    block_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
    type         TEXT NOT NULL DEFAULT '',    -- text | title | table | image | equation | code | list | ref_text ...
    sub_type     TEXT DEFAULT '',
    page_idx     INTEGER DEFAULT 0,
    bbox_json    TEXT DEFAULT '[]',           -- [x0, y0, x1, y1]
    text         TEXT DEFAULT '',
    section_path TEXT DEFAULT '',             -- e.g. "2.Method/2.1 Model"
    order_idx    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_blocks_paper ON blocks(paper_id);
CREATE INDEX IF NOT EXISTS idx_blocks_type  ON blocks(paper_id, type);
CREATE INDEX IF NOT EXISTS idx_blocks_paper_order ON blocks(paper_id, order_idx);

CREATE TABLE IF NOT EXISTS paper_nodes (
    node_id         TEXT PRIMARY KEY,
    paper_id        TEXT NOT NULL REFERENCES papers(paper_id),
    parent_id       TEXT DEFAULT '',
    depth           INTEGER DEFAULT 0,
    node_type       TEXT NOT NULL DEFAULT '',    -- paper | section | chunk
    block_type      TEXT DEFAULT '',             -- original block type for chunk nodes
    sub_type        TEXT DEFAULT '',
    title           TEXT DEFAULT '',
    title_path      TEXT DEFAULT '',
    page_start      INTEGER DEFAULT 0,
    page_end        INTEGER DEFAULT 0,
    block_start     INTEGER DEFAULT 0,
    block_end       INTEGER DEFAULT 0,
    text            TEXT DEFAULT '',
    text_for_search TEXT DEFAULT '',
    order_idx       INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_paper_nodes_paper ON paper_nodes(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_nodes_parent ON paper_nodes(paper_id, parent_id);
CREATE INDEX IF NOT EXISTS idx_paper_nodes_type ON paper_nodes(paper_id, node_type);

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    paper_id        TEXT NOT NULL REFERENCES papers(paper_id),
    mode            TEXT NOT NULL DEFAULT 'snap', -- snap | lens | sphere | auto | qa
    llm_model       TEXT DEFAULT '',
    language        TEXT NOT NULL DEFAULT 'en',   -- en | zh
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
    error_msg       TEXT DEFAULT '',
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT DEFAULT NULL,
    user_question   TEXT DEFAULT '',
    detected_intent TEXT DEFAULT '',
    current_step    TEXT DEFAULT '',              -- last step name pushed via progress (for resume UI)
    progress_json   TEXT DEFAULT '[]',            -- JSON array of {step,status,...} events emitted so far
    owner_token     TEXT DEFAULT ''               -- per-browser owner token, scopes recent-runs listing
);
CREATE INDEX IF NOT EXISTS idx_runs_status_started ON runs(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_paper ON runs(paper_id);
-- NOTE: idx_runs_owner_started is created in database.py AFTER the owner_token
-- column migration. It must not live here: on legacy DBs the runs table already
-- exists without owner_token, so this script runs before the column is added and
-- an inline index on owner_token would raise "no such column" and abort init.

CREATE TABLE IF NOT EXISTS run_outputs (
    run_id   TEXT PRIMARY KEY REFERENCES runs(run_id),
    markdown TEXT DEFAULT '',
    json_data TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_progress_events (
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    seq        INTEGER NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'progress',
    data_json  TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_run_progress_events_run_seq
    ON run_progress_events(run_id, seq);

CREATE TABLE IF NOT EXISTS dify_syncs (
    paper_id         TEXT NOT NULL REFERENCES papers(paper_id),
    dataset_id       TEXT NOT NULL DEFAULT '',
    dify_document_id TEXT DEFAULT '',
    source_hash      TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'pending', -- pending | running | synced | failed | skipped
    attempts         INTEGER NOT NULL DEFAULT 0,
    error_msg        TEXT DEFAULT '',
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (paper_id, dataset_id)
);
CREATE INDEX IF NOT EXISTS idx_dify_syncs_status ON dify_syncs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_dify_syncs_paper_updated ON dify_syncs(paper_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS analysis_dify_syncs (
    run_id           TEXT NOT NULL REFERENCES runs(run_id),
    paper_id         TEXT NOT NULL REFERENCES papers(paper_id),
    dataset_id       TEXT NOT NULL DEFAULT '',
    dify_document_id TEXT DEFAULT '',
    source_hash      TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'pending', -- pending | running | synced | failed | skipped
    attempts         INTEGER NOT NULL DEFAULT 0,
    error_msg        TEXT DEFAULT '',
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, dataset_id)
);
CREATE INDEX IF NOT EXISTS idx_analysis_dify_syncs_status ON analysis_dify_syncs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_dify_syncs_paper ON analysis_dify_syncs(paper_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_spaces (
    space_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    name_zh         TEXT NOT NULL DEFAULT '',
    space_type      TEXT NOT NULL DEFAULT '', -- main_source | main_analysis | daily_source | daily_analysis | custom
    description     TEXT NOT NULL DEFAULT '',
    description_zh  TEXT NOT NULL DEFAULT '',
    research_profile TEXT NOT NULL DEFAULT '', -- research questions / focus method families / writing topics; injected into card extraction & critique prompts
    dify_dataset_id TEXT NOT NULL DEFAULT '',
    is_system       INTEGER NOT NULL DEFAULT 0,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_knowledge_spaces_type ON knowledge_spaces(space_type, sort_order);

CREATE TABLE IF NOT EXISTS knowledge_space_items (
    space_id         TEXT NOT NULL REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
    item_kind        TEXT NOT NULL DEFAULT '', -- paper | run | dify_document | card | snippet
    item_id          TEXT NOT NULL DEFAULT '',
    paper_id         TEXT NOT NULL DEFAULT '',
    run_id           TEXT NOT NULL DEFAULT '',
    source_type      TEXT NOT NULL DEFAULT '', -- upload | daily | manual | generated
    sync_status      TEXT NOT NULL DEFAULT 'pending',
    dify_document_id TEXT NOT NULL DEFAULT '',
    note             TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (space_id, item_kind, item_id)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_space_items_paper ON knowledge_space_items(paper_id, item_kind);
CREATE INDEX IF NOT EXISTS idx_knowledge_space_items_run ON knowledge_space_items(run_id, item_kind);
CREATE INDEX IF NOT EXISTS idx_knowledge_space_items_kind ON knowledge_space_items(item_kind, updated_at DESC);

CREATE TABLE IF NOT EXISTS research_evidence_items (
    evidence_id       TEXT PRIMARY KEY,
    evidence_type     TEXT NOT NULL DEFAULT '', -- claim | limitation | dataset | metric | method | result | problem | constraint
    paper_id          TEXT NOT NULL REFERENCES papers(paper_id),
    block_id          INTEGER DEFAULT 0,
    page              INTEGER DEFAULT 0,
    quote             TEXT NOT NULL DEFAULT '',
    normalized_label  TEXT NOT NULL DEFAULT '',
    taxonomy_path     TEXT NOT NULL DEFAULT '',
    confidence        REAL NOT NULL DEFAULT 0.0,
    extractor         TEXT NOT NULL DEFAULT 'rule_v1',
    model_version     TEXT NOT NULL DEFAULT '',
    prompt_version    TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'unverified', -- unverified | verified | revised | rejected
    revision_history  TEXT NOT NULL DEFAULT '[]',
    source_hash       TEXT NOT NULL DEFAULT '',
    source_run_id     TEXT NOT NULL DEFAULT '', -- which deep-read run produced this evidence (reuse Lens output)
    evidence_version  INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_research_evidence_paper ON research_evidence_items(paper_id, evidence_type);
CREATE INDEX IF NOT EXISTS idx_research_evidence_label ON research_evidence_items(evidence_type, normalized_label);

CREATE TABLE IF NOT EXISTS research_relation_edges (
    relation_id          TEXT PRIMARY KEY,
    relation_type        TEXT NOT NULL DEFAULT '', -- same_problem | method_variant | uses_same_dataset | conflicting_claim | transferable_method
    source_paper_id      TEXT NOT NULL REFERENCES papers(paper_id),
    target_paper_id      TEXT NOT NULL REFERENCES papers(paper_id),
    source_evidence_ids  TEXT NOT NULL DEFAULT '[]',
    target_evidence_ids  TEXT NOT NULL DEFAULT '[]',
    rule_id              TEXT NOT NULL DEFAULT '',
    positive_checks      TEXT NOT NULL DEFAULT '[]',
    negative_checks      TEXT NOT NULL DEFAULT '[]',
    counter_evidence_ids TEXT NOT NULL DEFAULT '[]',
    comparability_json   TEXT NOT NULL DEFAULT '{}',
    confidence           REAL NOT NULL DEFAULT 0.0,
    status               TEXT NOT NULL DEFAULT 'unverified',
    verifier_version     TEXT NOT NULL DEFAULT '',
    relation_version     INTEGER NOT NULL DEFAULT 1,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_research_relation_source ON research_relation_edges(source_paper_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_research_relation_target ON research_relation_edges(target_paper_id, relation_type);

CREATE TABLE IF NOT EXISTS research_gaps (
    gap_id                TEXT PRIMARY KEY,
    title                 TEXT NOT NULL DEFAULT '',
    hypothesis            TEXT NOT NULL DEFAULT '',
    description           TEXT NOT NULL DEFAULT '',
    support_evidence_ids  TEXT NOT NULL DEFAULT '[]',
    counter_evidence_ids  TEXT NOT NULL DEFAULT '[]',
    coverage_status       TEXT NOT NULL DEFAULT 'unknown', -- uncovered | partially_covered | covered | insufficient_corpus
    novelty_score         REAL NOT NULL DEFAULT 0.0,
    feasibility_score     REAL NOT NULL DEFAULT 0.0,
    evidence_strength     REAL NOT NULL DEFAULT 0.0,
    risk_score            REAL NOT NULL DEFAULT 0.0,
    experiment_cost       REAL NOT NULL DEFAULT 0.0,
    domain_value          REAL NOT NULL DEFAULT 0.0,
    status                TEXT NOT NULL DEFAULT 'candidate', -- candidate | needs_more_evidence | rejected | promoted_to_idea
    rejection_reason      TEXT NOT NULL DEFAULT '',
    minimum_experiment    TEXT NOT NULL DEFAULT '',
    hit_by_paper_ids      TEXT NOT NULL DEFAULT '[]',
    related_synthesis_card_ids TEXT NOT NULL DEFAULT '[]',
    related_card_ids      TEXT NOT NULL DEFAULT '[]',
    research_question     TEXT NOT NULL DEFAULT '',
    target_task           TEXT NOT NULL DEFAULT '',
    constraints_json      TEXT NOT NULL DEFAULT '[]',
    baseline_plan         TEXT NOT NULL DEFAULT '',
    contribution          TEXT NOT NULL DEFAULT '',
    target_venue          TEXT NOT NULL DEFAULT '',
    history_json          TEXT NOT NULL DEFAULT '[]',
    llm_model             TEXT NOT NULL DEFAULT '',
    llm_rationale         TEXT NOT NULL DEFAULT '',
    novelty_basis         TEXT NOT NULL DEFAULT '',
    novelty_evidence_json TEXT NOT NULL DEFAULT '{}',
    construction_batch_id TEXT NOT NULL DEFAULT '',
    source_fingerprint    TEXT NOT NULL DEFAULT '',
    scored_by             TEXT NOT NULL DEFAULT 'heuristic',
    critique_json         TEXT NOT NULL DEFAULT '{}',
    lineage_parent_id     TEXT NOT NULL DEFAULT '',
    gap_version           INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_research_gaps_status ON research_gaps(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS construction_state (
    state_key TEXT PRIMARY KEY,
    state_json TEXT NOT NULL DEFAULT '{}',
    last_construction_at TEXT NOT NULL DEFAULT '',
    last_paper_count INTEGER NOT NULL DEFAULT 0,
    last_evidence_count INTEGER NOT NULL DEFAULT 0,
    last_card_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS construction_jobs (
    job_id TEXT PRIMARY KEY,
    trigger_source TEXT NOT NULL DEFAULT 'manual',
    dry_run INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    progress_json TEXT NOT NULL DEFAULT '{}',
    estimate_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error_msg TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_construction_jobs_status ON construction_jobs(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS canonical_entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL DEFAULT '',
    canonical_name TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    definition TEXT NOT NULL DEFAULT '',
    centroid_json TEXT NOT NULL DEFAULT '[]',
    mention_count INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT 'rule',
    model_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_canonical_entities_type ON canonical_entities(entity_type, canonical_name);

CREATE TABLE IF NOT EXISTS entity_mentions (
    mention_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    card_id TEXT NOT NULL DEFAULT '',
    paper_id TEXT NOT NULL DEFAULT '',
    mention_text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(entity_id, card_id)
);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_card ON entity_mentions(card_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_paper ON entity_mentions(paper_id);

CREATE TABLE IF NOT EXISTS card_embeddings (
    card_id TEXT PRIMARY KEY REFERENCES knowledge_cards(card_id) ON DELETE CASCADE,
    embedding_json TEXT NOT NULL DEFAULT '[]',
    text_hash TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_card_embeddings_model ON card_embeddings(model_name, updated_at DESC);

CREATE TABLE IF NOT EXISTS node_embeddings (
    node_id TEXT PRIMARY KEY REFERENCES paper_nodes(node_id) ON DELETE CASCADE,
    paper_id TEXT NOT NULL DEFAULT '',
    embedding_json TEXT NOT NULL DEFAULT '[]',
    text_hash TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_paper ON node_embeddings(paper_id, model_name);

CREATE TABLE IF NOT EXISTS idea_feedback (
    feedback_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL DEFAULT '',
    item_type TEXT NOT NULL DEFAULT 'gap',
    verdict TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_idea_feedback_item ON idea_feedback(item_type, item_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_idea_feedback_verdict ON idea_feedback(verdict, created_at DESC);

CREATE TABLE IF NOT EXISTS research_profile (
    profile_id TEXT PRIMARY KEY,
    profile_scope TEXT NOT NULL DEFAULT 'global',
    profile_text TEXT NOT NULL DEFAULT '',
    topic_weights_json TEXT NOT NULL DEFAULT '{}',
    source_counts_json TEXT NOT NULL DEFAULT '{}',
    built_at TEXT NOT NULL DEFAULT (datetime('now')),
    model_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_asset_events (
    event_id    TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL DEFAULT '',
    asset_type  TEXT NOT NULL DEFAULT '',
    asset_id    TEXT NOT NULL DEFAULT '',
    paper_id    TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_research_asset_events_asset ON research_asset_events(asset_type, asset_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_asset_events_type ON research_asset_events(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS library_qa_events (
    qa_id            TEXT PRIMARY KEY,
    question         TEXT NOT NULL DEFAULT '',
    answer_chars     INTEGER NOT NULL DEFAULT 0,
    source_types     TEXT NOT NULL DEFAULT '[]',
    graph_sources    INTEGER NOT NULL DEFAULT 0,
    dify_sources     INTEGER NOT NULL DEFAULT 0,
    snippet_sources  INTEGER NOT NULL DEFAULT 0,
    relation_sources INTEGER NOT NULL DEFAULT 0,
    search_method    TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_library_qa_events_created ON library_qa_events(created_at DESC);

CREATE TABLE IF NOT EXISTS library_qa_records (
    qa_id                   TEXT PRIMARY KEY,
    question                TEXT NOT NULL DEFAULT '',
    normalized_question     TEXT NOT NULL DEFAULT '',
    qa_signature            TEXT NOT NULL DEFAULT '',
    answer_markdown         TEXT NOT NULL DEFAULT '',
    answer_preview          TEXT NOT NULL DEFAULT '',
    sources_json            TEXT NOT NULL DEFAULT '[]',
    dataset_ids_json        TEXT NOT NULL DEFAULT '[]',
    search_method           TEXT NOT NULL DEFAULT '',
    effective_search_method TEXT NOT NULL DEFAULT '',
    language                TEXT NOT NULL DEFAULT 'en',
    llm_model               TEXT NOT NULL DEFAULT '',
    top_k                   INTEGER NOT NULL DEFAULT 10,
    graph_only              INTEGER NOT NULL DEFAULT 0,
    blocks_used             INTEGER NOT NULL DEFAULT 0,
    answer_chars            INTEGER NOT NULL DEFAULT 0,
    duration_ms             INTEGER NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'done',
    error_msg               TEXT NOT NULL DEFAULT '',
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_library_qa_records_signature ON library_qa_records(qa_signature, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_library_qa_records_created ON library_qa_records(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_library_qa_records_question ON library_qa_records(normalized_question, created_at DESC);

CREATE TABLE IF NOT EXISTS paper_annotations (
    annotation_id   TEXT PRIMARY KEY,
    paper_id        TEXT NOT NULL REFERENCES papers(paper_id),
    page            INTEGER NOT NULL DEFAULT 0,
    quote           TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT '',
    annotation_type TEXT NOT NULL DEFAULT 'highlight', -- highlight | note | question | correction
    color           TEXT NOT NULL DEFAULT 'yellow',
    bbox_json       TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_paper_annotations_paper ON paper_annotations(paper_id, page, updated_at DESC);

CREATE TABLE IF NOT EXISTS paper_notes (
    paper_id         TEXT PRIMARY KEY REFERENCES papers(paper_id),
    summary_user     TEXT NOT NULL DEFAULT '',
    key_takeaways    TEXT NOT NULL DEFAULT '',
    open_questions   TEXT NOT NULL DEFAULT '',
    reading_decision TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ai_review_marks (
    mark_id     TEXT PRIMARY KEY,
    paper_id    TEXT NOT NULL REFERENCES papers(paper_id),
    run_id      TEXT NOT NULL DEFAULT '',
    source_ref  TEXT NOT NULL DEFAULT '',
    quote       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending', -- trusted | pending | error | valuable
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_review_marks_paper ON ai_review_marks(paper_id, run_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_cards (
    card_id        TEXT PRIMARY KEY,
    card_type      TEXT NOT NULL DEFAULT 'claim', -- claim | method | dataset | metric | result | limitation | question | idea
    title          TEXT NOT NULL DEFAULT '',
    content        TEXT NOT NULL DEFAULT '',
    paper_id       TEXT NOT NULL DEFAULT '' REFERENCES papers(paper_id),
    source_page    INTEGER NOT NULL DEFAULT 0,
    source_quote   TEXT NOT NULL DEFAULT '',
    confidence     REAL NOT NULL DEFAULT 0.0,
    status         TEXT NOT NULL DEFAULT 'draft', -- draft | verified | rejected | merged
    tags           TEXT NOT NULL DEFAULT '',
    created_by     TEXT NOT NULL DEFAULT 'user', -- user | ai
    merged_into_id TEXT NOT NULL DEFAULT '',
    run_id         TEXT NOT NULL DEFAULT '',
    source_kind    TEXT NOT NULL DEFAULT '',
    source_ref     TEXT NOT NULL DEFAULT '',
    normalized_key TEXT NOT NULL DEFAULT '',
    quality_flags  TEXT NOT NULL DEFAULT '[]',
    prompt_version TEXT NOT NULL DEFAULT '',
    extractor_version TEXT NOT NULL DEFAULT '',
    asset_level    TEXT NOT NULL DEFAULT 'evidence',
    synthesis_type TEXT NOT NULL DEFAULT '',
    action_type    TEXT NOT NULL DEFAULT '',
    why_useful     TEXT NOT NULL DEFAULT '',
    use_case       TEXT NOT NULL DEFAULT '',
    next_action    TEXT NOT NULL DEFAULT '',
    expected_output TEXT NOT NULL DEFAULT '',
    risk_or_caveat TEXT NOT NULL DEFAULT '',
    priority       TEXT NOT NULL DEFAULT 'medium',
    supporting_card_ids TEXT NOT NULL DEFAULT '[]',
    supporting_paper_ids TEXT NOT NULL DEFAULT '[]',
    evidence_strength TEXT NOT NULL DEFAULT '',
    card_version   INTEGER NOT NULL DEFAULT 1,
    revision_history TEXT NOT NULL DEFAULT '[]', -- audit trail of status/content transitions
    reviewed_at    TEXT NOT NULL DEFAULT '',
    reviewed_by    TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_lookup ON knowledge_cards(status, card_type, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_paper ON knowledge_cards(paper_id, status);

CREATE TABLE IF NOT EXISTS knowledge_card_generations (
    generation_id     TEXT PRIMARY KEY,
    paper_id          TEXT NOT NULL REFERENCES papers(paper_id),
    run_id            TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'pending', -- pending | running | done | failed | skipped
    trigger_source    TEXT NOT NULL DEFAULT 'run_completed',
    llm_model         TEXT NOT NULL DEFAULT '',
    prompt_version    TEXT NOT NULL DEFAULT '',
    extractor_version TEXT NOT NULL DEFAULT '',
    source_hash       TEXT NOT NULL DEFAULT '',
    cards_created     INTEGER NOT NULL DEFAULT 0,
    cards_skipped     INTEGER NOT NULL DEFAULT 0,
    duplicate_count   INTEGER NOT NULL DEFAULT 0,
    critique_summary_json TEXT NOT NULL DEFAULT '{}',
    error_msg         TEXT NOT NULL DEFAULT '',
    raw_output_json   TEXT NOT NULL DEFAULT '[]',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_knowledge_card_generations_paper ON knowledge_card_generations(paper_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_card_generations_run ON knowledge_card_generations(run_id, status);

CREATE TABLE IF NOT EXISTS research_evidence_cards (
    evidence_id TEXT NOT NULL REFERENCES research_evidence_items(evidence_id) ON DELETE CASCADE,
    card_id     TEXT NOT NULL REFERENCES knowledge_cards(card_id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (evidence_id, card_id)
);
CREATE INDEX IF NOT EXISTS idx_research_evidence_cards_card ON research_evidence_cards(card_id);

CREATE TABLE IF NOT EXISTS writing_snippets (
    snippet_id     TEXT PRIMARY KEY,
    content        TEXT NOT NULL DEFAULT '',
    source_card_id TEXT NOT NULL DEFAULT '' REFERENCES knowledge_cards(card_id),
    paper_id       TEXT NOT NULL DEFAULT '' REFERENCES papers(paper_id),
    citation_key   TEXT NOT NULL DEFAULT '',
    source_page    INTEGER NOT NULL DEFAULT 0,
    source_quote   TEXT NOT NULL DEFAULT '',
    section_hint   TEXT NOT NULL DEFAULT 'related_work', -- related_work | method | experiment | limitation
    source_card_ids TEXT NOT NULL DEFAULT '[]',
    evidence_ids    TEXT NOT NULL DEFAULT '[]',
    paragraph_plan_json TEXT NOT NULL DEFAULT '{}',
    trace_mode      TEXT NOT NULL DEFAULT 'traceable',
    usage_count     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_writing_snippets_section ON writing_snippets(section_hint, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_writing_snippets_paper ON writing_snippets(paper_id);

CREATE TABLE IF NOT EXISTS sphere_nodes (
    node_id TEXT NOT NULL,
    run_id  TEXT NOT NULL REFERENCES runs(run_id),
    doi     TEXT DEFAULT '',
    arxiv_id TEXT DEFAULT '',
    openalex_id TEXT DEFAULT '',
    s2_paper_id TEXT DEFAULT '',
    title   TEXT DEFAULT '',
    year    INTEGER DEFAULT 0,
    venue   TEXT DEFAULT '',
    authors TEXT DEFAULT '',
    abstract_text TEXT DEFAULT '',
    cited_by_count INTEGER DEFAULT 0,
    pdf_path TEXT DEFAULT '',
    mineru_parsed INTEGER DEFAULT 0,
    source  TEXT DEFAULT 'seed_ref',
    score_total REAL DEFAULT 0.0,
    layer   INTEGER DEFAULT 0,
    cluster_id INTEGER DEFAULT -1,
    PRIMARY KEY (node_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_sphere_nodes_run ON sphere_nodes(run_id);

CREATE TABLE IF NOT EXISTS sphere_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'cites',
    weight REAL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_sphere_edges_run ON sphere_edges(run_id);
