from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PaperSource:
    paper_id: str
    title: str
    paper_ir_path: Path | None


class AI4SecReader:
    def __init__(self, data_dir: Path, app_db: Path) -> None:
        self.data_dir = data_dir
        self.app_db = app_db

    def list_ready_papers(self) -> list[PaperSource]:
        by_id: dict[str, PaperSource] = {}
        for source in self._list_from_paper_ir_files():
            by_id[source.paper_id] = source
        for source in self._list_from_db():
            current = by_id.get(source.paper_id)
            if current is None:
                by_id[source.paper_id] = source
            elif source.title and not current.title:
                by_id[source.paper_id] = PaperSource(
                    paper_id=current.paper_id,
                    title=source.title,
                    paper_ir_path=current.paper_ir_path,
                )
        return sorted(by_id.values(), key=lambda item: item.paper_id)

    def read_title_from_db(self, paper_id: str) -> str:
        if not self.app_db.exists():
            return ""
        try:
            with self._connect_ro() as db:
                row = db.execute(
                    "SELECT title FROM papers WHERE paper_id = ?",
                    (paper_id,),
                ).fetchone()
        except sqlite3.Error:
            return ""
        return str(row["title"] or "").strip() if row else ""

    def read_blocks_from_db(self, paper_id: str) -> list[dict[str, Any]]:
        if not self.app_db.exists():
            return []
        try:
            with self._connect_ro() as db:
                rows = db.execute(
                    """
                    SELECT type, sub_type, page_idx, text, section_path, order_idx
                    FROM blocks
                    WHERE paper_id = ?
                    ORDER BY order_idx ASC
                    """,
                    (paper_id,),
                ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(row) for row in rows]

    def _list_from_paper_ir_files(self) -> list[PaperSource]:
        papers_dir = self.data_dir / "papers"
        if not papers_dir.exists():
            return []
        sources: list[PaperSource] = []
        for ir_path in papers_dir.glob("*/mineru/raw/normalized/paper_ir.json"):
            try:
                payload = json.loads(ir_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            paper_id = str(payload.get("paper_id") or ir_path.parents[3].name).strip()
            if not paper_id:
                continue
            title = str(payload.get("title") or "").strip()
            sources.append(PaperSource(paper_id=paper_id, title=title, paper_ir_path=ir_path))
        return sources

    def _list_from_db(self) -> list[PaperSource]:
        if not self.app_db.exists():
            return []
        try:
            with self._connect_ro() as db:
                rows = db.execute(
                    """
                    SELECT p.paper_id, p.title
                    FROM papers p
                    JOIN mineru_parses m ON m.paper_id = p.paper_id
                    WHERE m.status = 'done'
                    GROUP BY p.paper_id
                    ORDER BY max(m.created_at) DESC
                    """
                ).fetchall()
        except sqlite3.Error:
            return []
        sources: list[PaperSource] = []
        for row in rows:
            paper_id = str(row["paper_id"] or "").strip()
            if not paper_id:
                continue
            ir_path = self.data_dir / "papers" / paper_id / "mineru" / "raw" / "normalized" / "paper_ir.json"
            pdf_path = self.data_dir / "papers" / paper_id / "original.pdf"
            if not ir_path.exists() and not pdf_path.exists():
                continue
            sources.append(
                PaperSource(
                    paper_id=paper_id,
                    title=str(row["title"] or "").strip(),
                    paper_ir_path=ir_path if ir_path.exists() else None,
                )
            )
        return sources

    def _connect_ro(self) -> sqlite3.Connection:
        uri = f"file:{self.app_db}?mode=ro&immutable=1"
        db = sqlite3.connect(uri, uri=True)
        db.row_factory = sqlite3.Row
        return db
