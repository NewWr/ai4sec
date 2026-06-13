from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS dify_syncs (
  paper_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dify_document_id TEXT DEFAULT '',
  source_hash TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  error_msg TEXT DEFAULT '',
  attempts INTEGER DEFAULT 0,
  last_synced_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (paper_id, dataset_id)
);

CREATE INDEX IF NOT EXISTS idx_dify_syncs_status
ON dify_syncs(status, updated_at DESC);
"""


@dataclass(frozen=True)
class SyncState:
    paper_id: str
    dataset_id: str
    dify_document_id: str
    source_hash: str
    status: str
    error_msg: str
    attempts: int
    last_synced_at: str
    created_at: str
    updated_at: str


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def get(self, paper_id: str, dataset_id: str) -> SyncState | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM dify_syncs WHERE paper_id = ? AND dataset_id = ?",
                (paper_id, dataset_id),
            ).fetchone()
        return _state(row) if row else None

    def list(self, paper_id: str = "", status: str = "", limit: int = 50) -> list[SyncState]:
        where: list[str] = []
        params: list[object] = []
        if paper_id:
            where.append("paper_id = ?")
            params.append(paper_id)
        if status:
            where.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM dify_syncs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        return [_state(row) for row in rows]

    def mark_pending(self, paper_id: str, dataset_id: str, source_hash: str, reset: bool = False) -> None:
        attempts_expr = "0" if reset else "attempts"
        with self.connect() as db:
            db.execute(
                f"""
                INSERT INTO dify_syncs (paper_id, dataset_id, source_hash, status, updated_at)
                VALUES (?, ?, ?, 'pending', datetime('now'))
                ON CONFLICT(paper_id, dataset_id) DO UPDATE SET
                  source_hash = excluded.source_hash,
                  status = 'pending',
                  error_msg = '',
                  attempts = {attempts_expr},
                  updated_at = datetime('now')
                """,
                (paper_id, dataset_id, source_hash),
            )

    def mark_running(self, paper_id: str, dataset_id: str, source_hash: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO dify_syncs
                  (paper_id, dataset_id, source_hash, status, attempts, updated_at)
                VALUES (?, ?, ?, 'running', 1, datetime('now'))
                ON CONFLICT(paper_id, dataset_id) DO UPDATE SET
                  source_hash = excluded.source_hash,
                  status = 'running',
                  error_msg = '',
                  attempts = attempts + 1,
                  updated_at = datetime('now')
                """,
                (paper_id, dataset_id, source_hash),
            )

    def mark_synced(
        self,
        paper_id: str,
        dataset_id: str,
        source_hash: str,
        dify_document_id: str,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO dify_syncs
                  (paper_id, dataset_id, dify_document_id, source_hash, status,
                   last_synced_at, updated_at)
                VALUES (?, ?, ?, ?, 'synced', datetime('now'), datetime('now'))
                ON CONFLICT(paper_id, dataset_id) DO UPDATE SET
                  dify_document_id = excluded.dify_document_id,
                  source_hash = excluded.source_hash,
                  status = 'synced',
                  error_msg = '',
                  last_synced_at = datetime('now'),
                  updated_at = datetime('now')
                """,
                (paper_id, dataset_id, dify_document_id, source_hash),
            )

    def mark_skipped(self, paper_id: str, dataset_id: str, source_hash: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE dify_syncs
                SET status = 'skipped',
                    source_hash = ?,
                    error_msg = '',
                    updated_at = datetime('now')
                WHERE paper_id = ? AND dataset_id = ?
                """,
                (source_hash, paper_id, dataset_id),
            )

    def mark_failed(
        self,
        paper_id: str,
        dataset_id: str,
        source_hash: str,
        error_msg: str,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO dify_syncs
                  (paper_id, dataset_id, source_hash, status, error_msg, attempts, updated_at)
                VALUES (?, ?, ?, 'failed', ?, 1, datetime('now'))
                ON CONFLICT(paper_id, dataset_id) DO UPDATE SET
                  source_hash = excluded.source_hash,
                  status = 'failed',
                  error_msg = excluded.error_msg,
                  updated_at = datetime('now')
                """,
                (paper_id, dataset_id, source_hash, error_msg[:2000]),
            )

    def reset_failed(self, paper_id: str = "") -> int:
        sql = """
            UPDATE dify_syncs
            SET status = 'pending', error_msg = '', updated_at = datetime('now')
            WHERE status = 'failed'
        """
        params: tuple[object, ...] = ()
        if paper_id:
            sql += " AND paper_id = ?"
            params = (paper_id,)
        with self.connect() as db:
            cur = db.execute(sql, params)
            return cur.rowcount


def _state(row: sqlite3.Row) -> SyncState:
    return SyncState(
        paper_id=str(row["paper_id"] or ""),
        dataset_id=str(row["dataset_id"] or ""),
        dify_document_id=str(row["dify_document_id"] or ""),
        source_hash=str(row["source_hash"] or ""),
        status=str(row["status"] or ""),
        error_msg=str(row["error_msg"] or ""),
        attempts=int(row["attempts"] or 0),
        last_synced_at=str(row["last_synced_at"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )
