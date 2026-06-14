from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

logger = logging.getLogger("scholar.db")

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_db_path: Path | None = None
_conn: aiosqlite.Connection | None = None
_read_pool: list[aiosqlite.Connection] = []
_read_pool_next = 0
_READ_POOL_SIZE = 4
_write_lock = asyncio.Lock()


def _is_duplicate_column_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "duplicate column name" in str(exc).lower()


def set_db_path(path: Path) -> None:
    global _db_path
    if _conn is not None or _read_pool:
        raise RuntimeError("Cannot change database path while connections are open")
    _db_path = path


def _get_db_path() -> Path:
    if _db_path is None:
        raise RuntimeError("Database path not initialized. Call set_db_path() first.")
    return _db_path


def get_db_path() -> Path:
    return _get_db_path()


async def _configure_connection(conn: aiosqlite.Connection) -> None:
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA synchronous=NORMAL")


async def _connect() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(_get_db_path())
    await _configure_connection(conn)
    return conn


async def _connect_readonly() -> aiosqlite.Connection:
    path = _get_db_path().resolve()
    conn = await aiosqlite.connect(f"file:{path}?mode=ro&immutable=0", uri=True)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def _get_read_conn() -> aiosqlite.Connection:
    global _read_pool_next
    if not _read_pool:
        return await _connect_readonly()
    conn = _read_pool[_read_pool_next % len(_read_pool)]
    _read_pool_next += 1
    return conn


async def _ensure_analysis_dify_syncs_multi_dataset(conn: aiosqlite.Connection) -> None:
    table = await conn.execute_fetchall("PRAGMA table_info(analysis_dify_syncs)")
    if not table:
        return
    pk_cols = [str(row[1]) for row in table if int(row[5] or 0) > 0]
    if pk_cols == ["run_id", "dataset_id"]:
        return
    await conn.execute("ALTER TABLE analysis_dify_syncs RENAME TO analysis_dify_syncs_legacy")
    await conn.execute(
        """
        CREATE TABLE analysis_dify_syncs (
            run_id           TEXT NOT NULL REFERENCES runs(run_id),
            paper_id         TEXT NOT NULL REFERENCES papers(paper_id),
            dataset_id       TEXT NOT NULL DEFAULT '',
            dify_document_id TEXT DEFAULT '',
            source_hash      TEXT NOT NULL DEFAULT '',
            status           TEXT NOT NULL DEFAULT 'pending',
            attempts         INTEGER NOT NULL DEFAULT 0,
            error_msg        TEXT DEFAULT '',
            updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (run_id, dataset_id)
        )
        """
    )
    await conn.execute(
        """
        INSERT OR IGNORE INTO analysis_dify_syncs (
            run_id, paper_id, dataset_id, dify_document_id, source_hash,
            status, attempts, error_msg, updated_at
        )
        SELECT
            run_id, paper_id, COALESCE(dataset_id, ''), dify_document_id,
            source_hash, status, attempts, error_msg, updated_at
          FROM analysis_dify_syncs_legacy
        """
    )
    await conn.execute("DROP TABLE analysis_dify_syncs_legacy")


async def _ensure_research_construction_tables(conn: aiosqlite.Connection) -> None:
    await conn.executescript(
        """
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
        CREATE INDEX IF NOT EXISTS idx_construction_jobs_status
            ON construction_jobs(status, updated_at DESC);

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
        CREATE INDEX IF NOT EXISTS idx_canonical_entities_type
            ON canonical_entities(entity_type, canonical_name);

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
        CREATE INDEX IF NOT EXISTS idx_card_embeddings_model
            ON card_embeddings(model_name, updated_at DESC);

        CREATE TABLE IF NOT EXISTS node_embeddings (
            node_id TEXT PRIMARY KEY REFERENCES paper_nodes(node_id) ON DELETE CASCADE,
            paper_id TEXT NOT NULL DEFAULT '',
            embedding_json TEXT NOT NULL DEFAULT '[]',
            text_hash TEXT NOT NULL DEFAULT '',
            model_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_node_embeddings_paper
            ON node_embeddings(paper_id, model_name);

        CREATE TABLE IF NOT EXISTS idea_feedback (
            feedback_id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL DEFAULT '',
            item_type TEXT NOT NULL DEFAULT 'gap',
            verdict TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_idea_feedback_item
            ON idea_feedback(item_type, item_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_idea_feedback_verdict
            ON idea_feedback(verdict, created_at DESC);

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
        """
    )
    for col, col_def in [
        ("llm_model", "TEXT NOT NULL DEFAULT ''"),
        ("llm_rationale", "TEXT NOT NULL DEFAULT ''"),
        ("novelty_basis", "TEXT NOT NULL DEFAULT ''"),
        ("novelty_evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("construction_batch_id", "TEXT NOT NULL DEFAULT ''"),
        ("source_fingerprint", "TEXT NOT NULL DEFAULT ''"),
        ("scored_by", "TEXT NOT NULL DEFAULT 'heuristic'"),
        ("critique_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("lineage_parent_id", "TEXT NOT NULL DEFAULT ''"),
    ]:
        try:
            await conn.execute(f"ALTER TABLE research_gaps ADD COLUMN {col} {col_def}")
        except Exception as exc:
            if _is_duplicate_column_error(exc):
                logger.debug("research_gaps.%s column already exists", col)
            else:
                logger.warning("Failed to add research_gaps.%s column: %s", col, exc)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_gaps_batch "
        "ON research_gaps(construction_batch_id, status)"
    )


async def _ensure_research_evidence_cards_cascade(conn: aiosqlite.Connection) -> None:
    table = await conn.execute_fetchall("PRAGMA table_info(research_evidence_cards)")
    if not table:
        return
    foreign_keys = await conn.execute_fetchall("PRAGMA foreign_key_list(research_evidence_cards)")
    cascade_by_column = {str(row[3]): str(row[6]).upper() for row in foreign_keys}
    if cascade_by_column.get("evidence_id") == "CASCADE" and cascade_by_column.get("card_id") == "CASCADE":
        return

    await conn.commit()
    await conn.execute("PRAGMA foreign_keys=OFF")
    try:
        await conn.execute("ALTER TABLE research_evidence_cards RENAME TO research_evidence_cards_legacy")
        await conn.execute(
            """
            CREATE TABLE research_evidence_cards (
                evidence_id TEXT NOT NULL REFERENCES research_evidence_items(evidence_id) ON DELETE CASCADE,
                card_id     TEXT NOT NULL REFERENCES knowledge_cards(card_id) ON DELETE CASCADE,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (evidence_id, card_id)
            )
            """
        )
        await conn.execute(
            """
            INSERT OR IGNORE INTO research_evidence_cards (evidence_id, card_id, created_at)
            SELECT rec.evidence_id, rec.card_id, rec.created_at
              FROM research_evidence_cards_legacy rec
              JOIN research_evidence_items rei ON rei.evidence_id = rec.evidence_id
              JOIN knowledge_cards kc ON kc.card_id = rec.card_id
            """
        )
        await conn.execute("DROP TABLE research_evidence_cards_legacy")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_evidence_cards_card "
            "ON research_evidence_cards(card_id)"
        )
        await conn.commit()
    finally:
        await conn.execute("PRAGMA foreign_keys=ON")


async def open_db() -> None:
    """Open the process-level SQLite connection used by the FastAPI app."""
    global _conn, _read_pool
    if _conn is not None:
        return
    _conn = await _connect()
    _read_pool = [await _connect_readonly() for _ in range(_READ_POOL_SIZE)]


async def close_db() -> None:
    """Close the process-level SQLite connection if it is open."""
    global _conn, _read_pool, _read_pool_next
    for conn in _read_pool:
        await conn.close()
    _read_pool = []
    _read_pool_next = 0
    if _conn is not None:
        await _conn.close()
    _conn = None


async def init_db() -> None:
    path = _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        await db.executescript(schema)
        await db.commit()
        # Migrate existing tables: add new columns if missing
        for col, col_def in [
            ("original_filename", "TEXT DEFAULT ''"),
            ("venue", "TEXT DEFAULT ''"),
            ("year", "INTEGER DEFAULT 0"),
            ("sci_rank", "TEXT DEFAULT ''"),
            ("ccf_rank", "TEXT DEFAULT ''"),
            ("citation_key", "TEXT NOT NULL DEFAULT ''"),
            ("reading_status", "TEXT NOT NULL DEFAULT 'unread'"),
            ("priority", "TEXT NOT NULL DEFAULT 'medium'"),
            ("decision", "TEXT NOT NULL DEFAULT ''"),
            ("personal_rating", "INTEGER NOT NULL DEFAULT 0"),
            ("read_progress", "REAL NOT NULL DEFAULT 0.0"),
            ("last_read_at", "TEXT NOT NULL DEFAULT ''"),
        ]:
            try:
                await db.execute(f"ALTER TABLE papers ADD COLUMN {col} {col_def}")
                await db.commit()
            except sqlite3.OperationalError as exc:
                if "duplicate column name" in str(exc).lower():
                    logger.debug("papers.%s column already exists", col)
                else:
                    logger.warning("Failed to add papers.%s column: %s", col, exc)
            except Exception as exc:
                logger.warning("Failed to add papers.%s column: %s", col, exc)
        # Migrate runs table: add language column if missing
        try:
            await db.execute("ALTER TABLE runs ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")
            await db.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" in str(exc).lower():
                logger.debug("runs.language column already exists")
            else:
                logger.warning("Failed to add runs.language column: %s", exc)
        except Exception as exc:
            logger.warning("Failed to add runs.language column: %s", exc)
        # Migrate runs table: add user_question + detected_intent for Smart Q&A,
        # current_step + progress_json for resumable progress display.
        for col, col_def in [
            ("user_question", "TEXT DEFAULT ''"),
            ("detected_intent", "TEXT DEFAULT ''"),
            ("current_step", "TEXT DEFAULT ''"),
            ("progress_json", "TEXT DEFAULT '[]'"),
            ("owner_token", "TEXT DEFAULT ''"),
        ]:
            try:
                await db.execute(f"ALTER TABLE runs ADD COLUMN {col} {col_def}")
                await db.commit()
            except sqlite3.OperationalError as exc:
                if "duplicate column name" in str(exc).lower():
                    logger.debug("runs.%s column already exists", col)
                else:
                    logger.warning("Failed to add runs.%s column: %s", col, exc)
            except Exception as exc:
                logger.warning("Failed to add runs.%s column: %s", col, exc)
        for index_sql in (
            "CREATE INDEX IF NOT EXISTS idx_runs_status_started ON runs(status, started_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runs_owner_started ON runs(owner_token, started_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_blocks_paper_order ON blocks(paper_id, order_idx)",
            "CREATE INDEX IF NOT EXISTS idx_mineru_parses_paper_created ON mineru_parses(paper_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_dify_syncs_paper_updated ON dify_syncs(paper_id, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_paper_collection_items_collection ON paper_collection_items(collection_id, paper_id)",
        ):
            try:
                await db.execute(index_sql)
                await db.commit()
            except Exception:
                logger.exception("Failed to create runs index")
        # Reconcile abandoned runs: any run still pending/running at startup lost
        # its owning background task when the previous process exited, so it can
        # never finish. Mark them failed to avoid zombie "running" entries that
        # would otherwise linger in the recent-runs banner forever.
        try:
            cursor = await db.execute(
                "UPDATE runs SET status = 'failed', "
                "error_msg = 'Interrupted (server restarted)', "
                "finished_at = datetime('now') "
                "WHERE status IN ('pending', 'running')"
            )
            await db.commit()
            if cursor.rowcount:
                logger.info("Reconciled %d interrupted run(s) on startup", cursor.rowcount)
        except Exception:
            logger.exception("Failed to reconcile interrupted runs on startup")
        # Migrate mineru_parses table: add remote poll diagnostics.
        for col, col_def in [
            ("remote_batch_id", "TEXT DEFAULT ''"),
            ("poll_count", "INTEGER DEFAULT 0"),
            ("last_state_counts", "TEXT DEFAULT ''"),
            ("last_poll_at", "TEXT DEFAULT ''"),
        ]:
            try:
                await db.execute(f"ALTER TABLE mineru_parses ADD COLUMN {col} {col_def}")
                await db.commit()
            except Exception as exc:
                if _is_duplicate_column_error(exc):
                    logger.debug("mineru_parses.%s column already exists", col)
                else:
                    logger.warning("Failed to add mineru_parses.%s column: %s", col, exc)
        # Optional FTS index for Smart Q&A hierarchy nodes. The regular
        # paper_nodes table remains the source of truth if FTS5 is unavailable.
        try:
            await db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS paper_node_fts "
                "USING fts5(node_id UNINDEXED, paper_id UNINDEXED, title_path, text_for_search)"
            )
            await db.commit()
        except Exception as exc:
            logger.warning("FTS5 paper_node_fts unavailable or failed to initialize: %s", exc)
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS dify_syncs (
                    paper_id         TEXT NOT NULL REFERENCES papers(paper_id),
                    dataset_id       TEXT NOT NULL DEFAULT '',
                    dify_document_id TEXT DEFAULT '',
                    source_hash      TEXT NOT NULL DEFAULT '',
                    status           TEXT NOT NULL DEFAULT 'pending',
                    attempts         INTEGER NOT NULL DEFAULT 0,
                    error_msg        TEXT DEFAULT '',
                    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (paper_id, dataset_id)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_dify_syncs_status "
                "ON dify_syncs(status, updated_at DESC)"
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to create dify_syncs table")
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_dify_syncs (
                    run_id           TEXT NOT NULL REFERENCES runs(run_id),
                    paper_id         TEXT NOT NULL REFERENCES papers(paper_id),
                    dataset_id       TEXT NOT NULL DEFAULT '',
                    dify_document_id TEXT DEFAULT '',
                    source_hash      TEXT NOT NULL DEFAULT '',
                    status           TEXT NOT NULL DEFAULT 'pending',
                    attempts         INTEGER NOT NULL DEFAULT 0,
                    error_msg        TEXT DEFAULT '',
                    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (run_id, dataset_id)
                )
                """
            )
            await _ensure_analysis_dify_syncs_multi_dataset(db)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_dify_syncs_status "
                "ON analysis_dify_syncs(status, updated_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_dify_syncs_paper "
                "ON analysis_dify_syncs(paper_id, updated_at DESC)"
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to create analysis_dify_syncs table")
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS run_progress_events (
                    run_id     TEXT NOT NULL REFERENCES runs(run_id),
                    seq        INTEGER NOT NULL,
                    event_type TEXT NOT NULL DEFAULT 'progress',
                    data_json  TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (run_id, seq)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_progress_events_run_seq "
                "ON run_progress_events(run_id, seq)"
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to create run_progress_events table")
        try:
            cursor = await db.execute(
                "DELETE FROM run_progress_events WHERE created_at < datetime('now', '-7 days')"
            )
            await db.commit()
            if cursor.rowcount:
                logger.info("Cleaned %d old run_progress_events row(s)", cursor.rowcount)
        except Exception:
            logger.exception("Failed to clean old run_progress_events rows")
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_spaces (
                    space_id        TEXT PRIMARY KEY,
                    name            TEXT NOT NULL DEFAULT '',
                    name_zh         TEXT NOT NULL DEFAULT '',
                    space_type      TEXT NOT NULL DEFAULT '',
                    description     TEXT NOT NULL DEFAULT '',
                    description_zh  TEXT NOT NULL DEFAULT '',
                    research_profile TEXT NOT NULL DEFAULT '',
                    dify_dataset_id TEXT NOT NULL DEFAULT '',
                    is_system       INTEGER NOT NULL DEFAULT 0,
                    sort_order      INTEGER NOT NULL DEFAULT 0,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            for col, col_def in [
                ("research_profile", "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE knowledge_spaces ADD COLUMN {col} {col_def}")
                    await db.commit()
                except Exception as exc:
                    if _is_duplicate_column_error(exc):
                        logger.debug("knowledge_spaces.%s column already exists", col)
                    else:
                        logger.warning("Failed to add knowledge_spaces.%s column: %s", col, exc)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_spaces_type "
                "ON knowledge_spaces(space_type, sort_order)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_space_items (
                    space_id         TEXT NOT NULL REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
                    item_kind        TEXT NOT NULL DEFAULT '',
                    item_id          TEXT NOT NULL DEFAULT '',
                    paper_id         TEXT NOT NULL DEFAULT '',
                    run_id           TEXT NOT NULL DEFAULT '',
                    source_type      TEXT NOT NULL DEFAULT '',
                    sync_status      TEXT NOT NULL DEFAULT 'pending',
                    dify_document_id TEXT NOT NULL DEFAULT '',
                    note             TEXT NOT NULL DEFAULT '',
                    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (space_id, item_kind, item_id)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_space_items_paper "
                "ON knowledge_space_items(paper_id, item_kind)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_space_items_run "
                "ON knowledge_space_items(run_id, item_kind)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_space_items_kind "
                "ON knowledge_space_items(item_kind, updated_at DESC)"
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to create knowledge space tables")
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS research_evidence_items (
                    evidence_id       TEXT PRIMARY KEY,
                    evidence_type     TEXT NOT NULL DEFAULT '',
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
                    status            TEXT NOT NULL DEFAULT 'unverified',
                    revision_history  TEXT NOT NULL DEFAULT '[]',
                    source_hash       TEXT NOT NULL DEFAULT '',
                    source_run_id     TEXT NOT NULL DEFAULT '',
                    evidence_version  INTEGER NOT NULL DEFAULT 1,
                    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            for col, col_def in [
                ("source_run_id", "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE research_evidence_items ADD COLUMN {col} {col_def}")
                    await db.commit()
                except Exception as exc:
                    if _is_duplicate_column_error(exc):
                        logger.debug("research_evidence_items.%s column already exists", col)
                    else:
                        logger.warning("Failed to add research_evidence_items.%s column: %s", col, exc)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_evidence_paper "
                "ON research_evidence_items(paper_id, evidence_type)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_evidence_label "
                "ON research_evidence_items(evidence_type, normalized_label)"
            )
            await db.execute(
                """
                    CREATE TABLE IF NOT EXISTS research_relation_edges (
                        relation_id          TEXT PRIMARY KEY,
                        relation_type        TEXT NOT NULL DEFAULT '',
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
                )
                """
            )
            for col, col_def in [
                ("verifier_version", "TEXT NOT NULL DEFAULT ''"),
                ("comparability_json", "TEXT NOT NULL DEFAULT '{}'"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE research_relation_edges ADD COLUMN {col} {col_def}")
                    await db.commit()
                except Exception as exc:
                    if _is_duplicate_column_error(exc):
                        logger.debug("research_relation_edges.%s column already exists", col)
                    else:
                        logger.warning("Failed to add research_relation_edges.%s column: %s", col, exc)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_relation_source "
                "ON research_relation_edges(source_paper_id, relation_type)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_relation_target "
                "ON research_relation_edges(target_paper_id, relation_type)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS research_gaps (
                    gap_id                TEXT PRIMARY KEY,
                    title                 TEXT NOT NULL DEFAULT '',
                    hypothesis            TEXT NOT NULL DEFAULT '',
                    description           TEXT NOT NULL DEFAULT '',
                    support_evidence_ids  TEXT NOT NULL DEFAULT '[]',
                    counter_evidence_ids  TEXT NOT NULL DEFAULT '[]',
                    coverage_status       TEXT NOT NULL DEFAULT 'unknown',
                    novelty_score         REAL NOT NULL DEFAULT 0.0,
                    feasibility_score     REAL NOT NULL DEFAULT 0.0,
                    evidence_strength     REAL NOT NULL DEFAULT 0.0,
                    risk_score            REAL NOT NULL DEFAULT 0.0,
                    experiment_cost       REAL NOT NULL DEFAULT 0.0,
                    domain_value          REAL NOT NULL DEFAULT 0.0,
                    status                TEXT NOT NULL DEFAULT 'candidate',
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
                        gap_version           INTEGER NOT NULL DEFAULT 1,
                        created_at            TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            for col, col_def in [
                ("hit_by_paper_ids", "TEXT NOT NULL DEFAULT '[]'"),
                ("related_synthesis_card_ids", "TEXT NOT NULL DEFAULT '[]'"),
                ("related_card_ids", "TEXT NOT NULL DEFAULT '[]'"),
                ("research_question", "TEXT NOT NULL DEFAULT ''"),
                ("target_task", "TEXT NOT NULL DEFAULT ''"),
                ("constraints_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("baseline_plan", "TEXT NOT NULL DEFAULT ''"),
                ("contribution", "TEXT NOT NULL DEFAULT ''"),
                ("target_venue", "TEXT NOT NULL DEFAULT ''"),
                ("history_json", "TEXT NOT NULL DEFAULT '[]'"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE research_gaps ADD COLUMN {col} {col_def}")
                    await db.commit()
                except Exception as exc:
                    if _is_duplicate_column_error(exc):
                        logger.debug("research_gaps.%s column already exists", col)
                    else:
                        logger.warning("Failed to add research_gaps.%s column: %s", col, exc)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_gaps_status "
                "ON research_gaps(status, updated_at DESC)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS research_asset_events (
                    event_id    TEXT PRIMARY KEY,
                    event_type  TEXT NOT NULL DEFAULT '',
                    asset_type  TEXT NOT NULL DEFAULT '',
                    asset_id    TEXT NOT NULL DEFAULT '',
                    paper_id    TEXT NOT NULL DEFAULT '',
                    source      TEXT NOT NULL DEFAULT '',
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_asset_events_asset "
                "ON research_asset_events(asset_type, asset_id, created_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_asset_events_type "
                "ON research_asset_events(event_type, created_at DESC)"
            )
            await db.execute(
                """
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
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_library_qa_events_created "
                "ON library_qa_events(created_at DESC)"
            )
            await db.execute(
                """
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
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_library_qa_records_signature "
                "ON library_qa_records(qa_signature, created_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_library_qa_records_created "
                "ON library_qa_records(created_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_library_qa_records_question "
                "ON library_qa_records(normalized_question, created_at DESC)"
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to create research discovery tables")
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_cache (
                    text_hash       TEXT NOT NULL,
                    source_lang     TEXT NOT NULL DEFAULT 'auto',
                    target_lang     TEXT NOT NULL DEFAULT 'zh',
                    provider        TEXT NOT NULL DEFAULT 'deeplx',
                    source_text     TEXT NOT NULL DEFAULT '',
                    translated_text TEXT NOT NULL DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'done',
                    error_msg       TEXT NOT NULL DEFAULT '',
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (text_hash, source_lang, target_lang, provider)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_translation_cache_target "
                "ON translation_cache(target_lang, provider, updated_at DESC)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_recommendation_topics (
                    topic_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    name_zh TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                """
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
                )
                """
            )
            for col, col_def in [
                ("linked_run_id", "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE daily_recommendation_items ADD COLUMN {col} {col_def}")
                    await db.commit()
                except Exception as exc:
                    if _is_duplicate_column_error(exc):
                        logger.debug("daily_recommendation_items.%s column already exists", col)
                    else:
                        logger.warning("Failed to add daily_recommendation_items.%s column: %s", col, exc)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_items_date_topic "
                "ON daily_recommendation_items(fetched_date, topic_id, score DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_items_status "
                "ON daily_recommendation_items(status, fetched_date DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_items_arxiv "
                "ON daily_recommendation_items(arxiv_id, fetched_date DESC)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_recommendation_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL REFERENCES daily_recommendation_items(item_id),
                    arxiv_id TEXT NOT NULL DEFAULT '',
                    topic_id TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_feedback_topic_action "
                "ON daily_recommendation_feedback(topic_id, action, created_at DESC)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_display_cache (
                    paper_id           TEXT PRIMARY KEY REFERENCES papers(paper_id),
                    title_zh           TEXT NOT NULL DEFAULT '',
                    summary_source     TEXT NOT NULL DEFAULT '',
                    summary_en         TEXT NOT NULL DEFAULT '',
                    summary_zh         TEXT NOT NULL DEFAULT '',
                    source_hash        TEXT NOT NULL DEFAULT '',
                    translation_status TEXT NOT NULL DEFAULT 'pending',
                    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                """
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
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_paper_collections_parent "
                "ON paper_collections(parent_id, sort_order, name)"
            )
            await db.execute(
                """
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
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_paper_collection_items_paper "
                "ON paper_collection_items(paper_id, is_primary DESC)"
            )
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_collection_items_primary "
                "ON paper_collection_items(paper_id) WHERE is_primary = 1"
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to create paper organization tables")
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_annotations (
                    annotation_id   TEXT PRIMARY KEY,
                    paper_id        TEXT NOT NULL REFERENCES papers(paper_id),
                    page            INTEGER NOT NULL DEFAULT 0,
                    quote           TEXT NOT NULL DEFAULT '',
                    note            TEXT NOT NULL DEFAULT '',
                    annotation_type TEXT NOT NULL DEFAULT 'highlight',
                    color           TEXT NOT NULL DEFAULT 'yellow',
                    bbox_json       TEXT NOT NULL DEFAULT '[]',
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_paper_annotations_paper "
                "ON paper_annotations(paper_id, page, updated_at DESC)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_notes (
                    paper_id         TEXT PRIMARY KEY REFERENCES papers(paper_id),
                    summary_user     TEXT NOT NULL DEFAULT '',
                    key_takeaways    TEXT NOT NULL DEFAULT '',
                    open_questions   TEXT NOT NULL DEFAULT '',
                    reading_decision TEXT NOT NULL DEFAULT '',
                    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_review_marks (
                    mark_id     TEXT PRIMARY KEY,
                    paper_id    TEXT NOT NULL REFERENCES papers(paper_id),
                    run_id      TEXT NOT NULL DEFAULT '',
                    source_ref  TEXT NOT NULL DEFAULT '',
                    quote       TEXT NOT NULL DEFAULT '',
                    status      TEXT NOT NULL DEFAULT 'pending',
                    note        TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_review_marks_paper "
                "ON ai_review_marks(paper_id, run_id, updated_at DESC)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_cards (
                    card_id        TEXT PRIMARY KEY,
                    card_type      TEXT NOT NULL DEFAULT 'claim',
                    title          TEXT NOT NULL DEFAULT '',
                    content        TEXT NOT NULL DEFAULT '',
                    paper_id       TEXT NOT NULL DEFAULT '' REFERENCES papers(paper_id),
                    source_page    INTEGER NOT NULL DEFAULT 0,
                    source_quote   TEXT NOT NULL DEFAULT '',
                    confidence     REAL NOT NULL DEFAULT 0.0,
                    status         TEXT NOT NULL DEFAULT 'draft',
                    tags           TEXT NOT NULL DEFAULT '',
                    created_by     TEXT NOT NULL DEFAULT 'user',
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
                    revision_history TEXT NOT NULL DEFAULT '[]',
                    reviewed_at    TEXT NOT NULL DEFAULT '',
                    reviewed_by    TEXT NOT NULL DEFAULT '',
                    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_cards_lookup "
                "ON knowledge_cards(status, card_type, updated_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_cards_paper "
                "ON knowledge_cards(paper_id, status)"
            )
            for col, col_def in [
                ("run_id", "TEXT NOT NULL DEFAULT ''"),
                ("source_kind", "TEXT NOT NULL DEFAULT ''"),
                ("source_ref", "TEXT NOT NULL DEFAULT ''"),
                ("normalized_key", "TEXT NOT NULL DEFAULT ''"),
                ("quality_flags", "TEXT NOT NULL DEFAULT '[]'"),
                ("prompt_version", "TEXT NOT NULL DEFAULT ''"),
                ("extractor_version", "TEXT NOT NULL DEFAULT ''"),
                ("asset_level", "TEXT NOT NULL DEFAULT 'evidence'"),
                ("synthesis_type", "TEXT NOT NULL DEFAULT ''"),
                ("action_type", "TEXT NOT NULL DEFAULT ''"),
                ("why_useful", "TEXT NOT NULL DEFAULT ''"),
                ("use_case", "TEXT NOT NULL DEFAULT ''"),
                ("next_action", "TEXT NOT NULL DEFAULT ''"),
                ("expected_output", "TEXT NOT NULL DEFAULT ''"),
                ("risk_or_caveat", "TEXT NOT NULL DEFAULT ''"),
                ("priority", "TEXT NOT NULL DEFAULT 'medium'"),
                ("supporting_card_ids", "TEXT NOT NULL DEFAULT '[]'"),
                ("supporting_paper_ids", "TEXT NOT NULL DEFAULT '[]'"),
                ("evidence_strength", "TEXT NOT NULL DEFAULT ''"),
                ("card_version", "INTEGER NOT NULL DEFAULT 1"),
                ("revision_history", "TEXT NOT NULL DEFAULT '[]'"),
                ("reviewed_at", "TEXT NOT NULL DEFAULT ''"),
                ("reviewed_by", "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE knowledge_cards ADD COLUMN {col} {col_def}")
                    await db.commit()
                except Exception as exc:
                    if _is_duplicate_column_error(exc):
                        logger.debug("knowledge_cards.%s column already exists", col)
                    else:
                        logger.warning("Failed to add knowledge_cards.%s column: %s", col, exc)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_cards_run "
                "ON knowledge_cards(run_id, status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_cards_normalized "
                "ON knowledge_cards(normalized_key, status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_cards_ai_review "
                "ON knowledge_cards(created_by, status, confidence)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_cards_asset_level "
                "ON knowledge_cards(asset_level, status, updated_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_cards_action "
                "ON knowledge_cards(action_type, priority, status)"
            )
            await db.execute(
                """
                UPDATE knowledge_cards
                   SET asset_level = 'action',
                       action_type = CASE
                           WHEN card_type IN ('dataset', 'metric') THEN 'experiment'
                           WHEN card_type = 'method' THEN 'implementation'
                           WHEN card_type IN ('limitation', 'question', 'idea') THEN 'idea'
                           ELSE 'writing'
                       END,
                       use_case = CASE
                           WHEN card_type IN ('dataset', 'metric') THEN 'experiment'
                           WHEN card_type = 'method' THEN 'implementation'
                           WHEN card_type IN ('limitation', 'question', 'idea') THEN 'idea'
                           ELSE 'writing'
                       END,
                       why_useful = CASE
                           WHEN card_type = 'method' THEN 'Captures a reusable method mechanism that can inform implementation, comparison, or method design.'
                           WHEN card_type IN ('dataset', 'metric') THEN 'Identifies an evaluation element that can be reused when designing experiments or baselines.'
                           WHEN card_type = 'result' THEN 'Provides cited result evidence that can support related work, motivation, or comparison writing.'
                           WHEN card_type = 'limitation' THEN 'Records an applicability boundary that can motivate follow-up work or risk analysis.'
                           ELSE 'Provides traceable evidence that may support later research writing or decisions.'
                       END,
                       next_action = CASE
                           WHEN card_type = 'method' THEN 'Compare this mechanism with your target method and decide whether it should be a baseline, module, or ablation.'
                           WHEN card_type IN ('dataset', 'metric') THEN 'Check whether this evaluation element should be included in the next experiment matrix.'
                           WHEN card_type = 'result' THEN 'Use this as cited evidence in related work or as a comparison point in the experiment section.'
                           WHEN card_type = 'limitation' THEN 'Turn this limitation into a motivation, stress test, or follow-up hypothesis.'
                           ELSE 'Review the source and decide whether to promote this evidence into writing, experiment, or idea planning.'
                       END,
                       expected_output = 'A concrete research note that can be reused in later work.',
                       risk_or_caveat = 'Verify applicability before reusing this paper-specific evidence.',
                       priority = CASE
                           WHEN card_type IN ('method', 'result', 'limitation') AND confidence >= 0.85 THEN 'high'
                           WHEN confidence < 0.6 THEN 'low'
                           ELSE 'medium'
                       END,
                       supporting_paper_ids = CASE WHEN paper_id != '' THEN '["' || paper_id || '"]' ELSE '[]' END,
                       evidence_strength = CASE WHEN paper_id != '' THEN 'single-paper' ELSE '' END
                 WHERE created_by = 'ai'
                   AND status = 'draft'
                   AND asset_level = 'evidence'
                   AND why_useful = ''
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_card_generations (
                    generation_id     TEXT PRIMARY KEY,
                    paper_id          TEXT NOT NULL REFERENCES papers(paper_id),
                    run_id            TEXT NOT NULL DEFAULT '',
                    status            TEXT NOT NULL DEFAULT 'pending',
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
                )
                """
            )
            try:
                await db.execute("ALTER TABLE knowledge_card_generations ADD COLUMN critique_summary_json TEXT NOT NULL DEFAULT '{}'")
                await db.commit()
            except Exception as exc:
                if _is_duplicate_column_error(exc):
                    logger.debug("knowledge_card_generations.critique_summary_json column already exists")
                else:
                    logger.warning("Failed to add knowledge_card_generations.critique_summary_json column: %s", exc)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_card_generations_paper "
                "ON knowledge_card_generations(paper_id, created_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_card_generations_run "
                "ON knowledge_card_generations(run_id, status)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS research_evidence_cards (
                    evidence_id TEXT NOT NULL REFERENCES research_evidence_items(evidence_id) ON DELETE CASCADE,
                    card_id     TEXT NOT NULL REFERENCES knowledge_cards(card_id) ON DELETE CASCADE,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (evidence_id, card_id)
                )
                """
            )
            await _ensure_research_evidence_cards_cascade(db)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_evidence_cards_card "
                "ON research_evidence_cards(card_id)"
            )
            await db.execute(
                """
                    CREATE TABLE IF NOT EXISTS writing_snippets (
                        snippet_id     TEXT PRIMARY KEY,
                        content        TEXT NOT NULL DEFAULT '',
                        source_card_id TEXT NOT NULL DEFAULT '' REFERENCES knowledge_cards(card_id),
                        paper_id       TEXT NOT NULL DEFAULT '' REFERENCES papers(paper_id),
                        citation_key   TEXT NOT NULL DEFAULT '',
                        source_page    INTEGER NOT NULL DEFAULT 0,
                        source_quote   TEXT NOT NULL DEFAULT '',
                        section_hint   TEXT NOT NULL DEFAULT 'related_work',
                        source_card_ids TEXT NOT NULL DEFAULT '[]',
                        evidence_ids    TEXT NOT NULL DEFAULT '[]',
                        paragraph_plan_json TEXT NOT NULL DEFAULT '{}',
                        trace_mode      TEXT NOT NULL DEFAULT 'traceable',
                        usage_count     INTEGER NOT NULL DEFAULT 0,
                        created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_writing_snippets_section "
                "ON writing_snippets(section_hint, updated_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_writing_snippets_paper "
                "ON writing_snippets(paper_id)"
            )
            for col, col_def in [
                ("source_page", "INTEGER NOT NULL DEFAULT 0"),
                ("source_quote", "TEXT NOT NULL DEFAULT ''"),
                ("source_card_ids", "TEXT NOT NULL DEFAULT '[]'"),
                ("evidence_ids", "TEXT NOT NULL DEFAULT '[]'"),
                ("paragraph_plan_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("trace_mode", "TEXT NOT NULL DEFAULT 'traceable'"),
                ("usage_count", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE writing_snippets ADD COLUMN {col} {col_def}")
                    await db.commit()
                except Exception as exc:
                    if _is_duplicate_column_error(exc):
                        logger.debug("writing_snippets.%s column already exists", col)
                    else:
                        logger.warning("Failed to add writing_snippets.%s column: %s", col, exc)
            await db.commit()
        except Exception:
            logger.exception("Failed to create long-term knowledge asset tables")
        try:
            await _ensure_research_construction_tables(db)
            await db.commit()
        except Exception:
            logger.exception("Failed to create research construction tables")


async def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    if _conn is not None:
        async with _write_lock:
            await _conn.execute(sql, params)
            await _conn.commit()
        return
    async with _write_lock:
        db = await _connect()
        try:
            await db.execute(sql, params)
            await db.commit()
        finally:
            await db.close()


async def execute_many(sql: str, params_seq: list[tuple[Any, ...]]) -> None:
    if _conn is not None:
        async with _write_lock:
            await _conn.executemany(sql, params_seq)
            await _conn.commit()
        return
    async with _write_lock:
        db = await _connect()
        try:
            await db.executemany(sql, params_seq)
            await db.commit()
        finally:
            await db.close()


async def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    if _conn is not None and _read_pool:
        conn = await _get_read_conn()
        cursor = await conn.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)
    db = await _connect()
    try:
        cursor = await db.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        await db.close()


async def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if _conn is not None and _read_pool:
        conn = await _get_read_conn()
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    db = await _connect()
    try:
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@asynccontextmanager
async def transaction() -> AsyncIterator[aiosqlite.Connection]:
    """Run multiple write statements in one serialized SQLite transaction."""
    async with _write_lock:
        if _conn is not None:
            await _conn.execute("BEGIN")
            try:
                yield _conn
            except Exception:
                await _conn.rollback()
                raise
            else:
                await _conn.commit()
            return

        conn = await _connect()
        try:
            await conn.execute("BEGIN")
            try:
                yield conn
            except Exception:
                await conn.rollback()
                raise
            else:
                await conn.commit()
        finally:
            await conn.close()


async def persist_run_event(run_id: str, event_type: str, data_json: str) -> int:
    if not run_id:
        return 0
    event_type = (event_type or "progress").strip() or "progress"
    async with _write_lock:
        conn = _conn or await _connect()
        should_close = _conn is None
        try:
            await conn.execute("BEGIN")
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM run_progress_events WHERE run_id = ?",
                (run_id,),
            )
            row = await cursor.fetchone()
            seq = int(row[0] if row else 1)
            await conn.execute(
                "INSERT INTO run_progress_events (run_id, seq, event_type, data_json) VALUES (?, ?, ?, ?)",
                (run_id, seq, event_type, data_json),
            )
            await conn.commit()
            return seq
        except Exception:
            await conn.rollback()
            raise
        finally:
            if should_close:
                await conn.close()
