from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import date
from typing import Any

from app.config import get_settings
from app.db import database as db
from app.services import dify_client
from app.services.daily_recommendations import _download_pdf
from app.services.external_note_matching import refresh_matches
from app.services.external_note_parser import parse_external_note
from app.services.external_note_utility import refresh_utility_score
from app.services.knowledge_assets import create_card
from app.services.knowledge_spaces import EXTERNAL_NOTES_SPACE_ID, add_item_to_space, get_space, update_item
from app.services.paper_collections import assign_paper_to_collection, ensure_default_collection
from app.services.paper_notes_client import PaperNotesClient

SOURCE_ID = "paper_notes"
VALID_STATUSES = {"new", "useful", "later", "ignored", "irrelevant", "promoted", "linked", "stale"}
PAPER_NOTES_COLLECTION_ID = "paper_notes_external"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Any, default: Any) -> Any:
    try:
        parsed = json.loads(str(value or ""))
    except Exception:
        return default
    return parsed if parsed is not None else default


async def ensure_default_source() -> dict[str, Any]:
    settings = get_settings()
    await db.execute(
        """
        INSERT INTO external_sources (
            source_id, name, source_type, repo_owner, repo_name, branch, docs_path,
            homepage_url, license_name, license_url, enabled, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(source_id) DO UPDATE SET
            repo_owner = excluded.repo_owner,
            repo_name = excluded.repo_name,
            branch = excluded.branch,
            docs_path = excluded.docs_path,
            homepage_url = excluded.homepage_url,
            license_name = excluded.license_name,
            license_url = excluded.license_url,
            enabled = excluded.enabled,
            updated_at = datetime('now')
        """,
        (
            SOURCE_ID,
            "Paper-Notes",
            "github_paper_notes",
            settings.paper_notes_repo_owner,
            settings.paper_notes_repo_name,
            settings.paper_notes_branch,
            settings.paper_notes_docs_path,
            "https://papernotes.org/",
            "CC BY-NC-SA 4.0",
            "https://creativecommons.org/licenses/by-nc-sa/4.0/",
            1 if settings.paper_notes_enabled else 0,
        ),
    )
    row = await db.fetch_one("SELECT * FROM external_sources WHERE source_id = ?", (SOURCE_ID,))
    return row or {}


async def list_sources() -> list[dict[str, Any]]:
    await ensure_default_source()
    return await db.fetch_all("SELECT * FROM external_sources ORDER BY name ASC")


async def list_facets() -> dict[str, Any]:
    await ensure_default_source()
    conferences = await db.fetch_all(
        """
        SELECT conference AS value, COUNT(*) AS count
          FROM external_paper_notes
         WHERE conference != ''
         GROUP BY conference
         ORDER BY conference ASC
        """
    )
    years = await db.fetch_all(
        """
        SELECT year AS value, COUNT(*) AS count
          FROM external_paper_notes
         WHERE year > 0
         GROUP BY year
         ORDER BY year DESC
        """
    )
    domains = await db.fetch_all(
        """
        SELECT domain AS value, COUNT(*) AS count
          FROM external_paper_notes
         WHERE domain != ''
         GROUP BY domain
         ORDER BY domain ASC
        """
    )
    return {
        "conferences": [{"value": str(row.get("value") or ""), "count": int(row.get("count") or 0)} for row in conferences],
        "years": [{"value": int(row.get("value") or 0), "count": int(row.get("count") or 0)} for row in years],
        "domains": [{"value": str(row.get("value") or ""), "count": int(row.get("count") or 0)} for row in domains],
    }


async def sync_paper_notes(*, force: bool = False, max_files: int = 0) -> dict[str, Any]:
    source = await ensure_default_source()
    if not int(source.get("enabled") or 0):
        raise ValueError("Paper-Notes source is disabled")
    settings = get_settings()
    sync_id = uuid.uuid4().hex[:16]
    started = _now()
    await db.execute(
        """
        INSERT INTO external_note_sync_runs (sync_id, source_id, status, started_at)
        VALUES (?, ?, 'running', ?)
        """,
        (sync_id, SOURCE_ID, started),
    )
    client = PaperNotesClient(
        owner=str(source.get("repo_owner") or ""),
        repo=str(source.get("repo_name") or ""),
        branch=str(source.get("branch") or ""),
        docs_path=str(source.get("docs_path") or ""),
    )
    errors: list[dict[str, str]] = []
    scanned = fetched = inserted = updated = unchanged = failed = 0
    commit_sha = ""
    try:
        commit_sha = await client.latest_commit_sha()
        configured_limit = max_files if max_files > 0 else settings.paper_notes_max_files_per_sync
        files = await client.list_markdown_files(max_files=max(0, int(configured_limit)))
        scanned = len(files)
        semaphore = asyncio.Semaphore(max(1, min(settings.paper_notes_fetch_concurrency, 16)))

        async def handle_file(file: Any) -> str:
            nonlocal fetched, inserted, updated, unchanged, failed
            try:
                current = await db.fetch_one(
                    "SELECT note_id, content_hash, commit_sha FROM external_paper_notes WHERE source_id = ? AND source_path = ?",
                    (SOURCE_ID, file.path),
                )
                if current and not force and str(current.get("commit_sha") or "") == commit_sha:
                    unchanged += 1
                    return str(current.get("note_id") or "")
                async with semaphore:
                    markdown = await client.fetch_markdown(file.raw_url)
                fetched += 1
                ir = parse_external_note(file.path, markdown)
                is_update = bool(current)
                if current and str(current.get("content_hash") or "") == ir.content_hash and not force:
                    await db.execute(
                        """
                        UPDATE external_paper_notes
                           SET source_url = ?, raw_url = ?, commit_sha = ?, updated_at = datetime('now')
                         WHERE note_id = ?
                        """,
                        (file.html_url, file.raw_url, commit_sha, str(current["note_id"])),
                    )
                    unchanged += 1
                    return str(current["note_id"])
                note_id = await _upsert_note(ir, source_url=file.html_url, raw_url=file.raw_url, commit_sha=commit_sha)
                await _insert_version(note_id, ir, commit_sha)
                await refresh_matches(note_id)
                await refresh_utility_score(note_id)
                if is_update:
                    updated += 1
                else:
                    inserted += 1
                return note_id
            except Exception as exc:
                failed += 1
                errors.append({"path": str(getattr(file, "path", "")), "error": str(exc)[:500]})
                return ""

        await asyncio.gather(*(handle_file(file) for file in files))
        status = "done" if failed == 0 else "partial"
        await db.execute(
            """
            UPDATE external_sources
               SET last_commit_sha = ?, last_synced_at = ?, updated_at = datetime('now')
             WHERE source_id = ?
            """,
            (commit_sha, _now(), SOURCE_ID),
        )
    except Exception as exc:
        status = "failed"
        errors.append({"path": "", "error": str(exc)[:500]})
    await db.execute(
        """
        UPDATE external_note_sync_runs
           SET status = ?, commit_sha = ?, scanned = ?, fetched = ?, inserted = ?,
               updated = ?, unchanged = ?, failed = ?, error_json = ?, finished_at = ?
         WHERE sync_id = ?
        """,
        (
            status,
            commit_sha,
            scanned,
            fetched,
            inserted,
            updated,
            unchanged,
            failed,
            _json_dumps(errors[-100:]),
            _now(),
            sync_id,
        ),
    )
    row = await db.fetch_one("SELECT * FROM external_note_sync_runs WHERE sync_id = ?", (sync_id,))
    return _sync_row(row or {})


async def get_sync_run(sync_id: str) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM external_note_sync_runs WHERE sync_id = ?", (sync_id,))
    if not row:
        raise KeyError("Sync run not found")
    return _sync_row(row)


async def latest_sync_run() -> dict[str, Any] | None:
    row = await db.fetch_one(
        "SELECT * FROM external_note_sync_runs WHERE source_id = ? ORDER BY created_at DESC LIMIT 1",
        (SOURCE_ID,),
    )
    return _sync_row(row) if row else None


async def list_items(
    *,
    conference: str = "",
    year: int = 0,
    domain: str = "",
    status: str = "",
    q: str = "",
    has_arxiv: bool | None = None,
    linked: bool | None = None,
    min_score: float = 0.0,
    sort: str = "utility",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    await ensure_default_source()
    clauses = ["1 = 1"]
    params: list[Any] = []
    if conference:
        clauses.append("conference = ?")
        params.append(conference.strip().upper())
    if year:
        clauses.append("year = ?")
        params.append(int(year))
    if domain:
        clauses.append("lower(domain) LIKE ?")
        params.append(f"%{domain.strip().lower()}%")
    if status:
        clauses.append("status = ?")
        params.append(status.strip())
    if q:
        needle = f"%{q.strip().lower()}%"
        clauses.append(
            "(lower(title) LIKE ? OR lower(title_zh) LIKE ? OR lower(summary) LIKE ? OR lower(method) LIKE ? OR lower(arxiv_id) LIKE ? OR lower(code_url) LIKE ?)"
        )
        params.extend([needle] * 6)
    if has_arxiv is not None:
        clauses.append("arxiv_id != ''" if has_arxiv else "arxiv_id = ''")
    if linked is not None:
        clauses.append("linked_paper_id != ''" if linked else "linked_paper_id = ''")
    if min_score:
        clauses.append("utility_score >= ?")
        params.append(float(min_score))
    order_sql = {
        "utility": "utility_score DESC, updated_at DESC",
        "updated": "updated_at DESC",
        "conference": "conference ASC, year DESC, title ASC",
        "year": "year DESC, conference ASC, title ASC",
    }.get(sort, "utility_score DESC, updated_at DESC")
    where = " AND ".join(clauses)
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    total_row = await db.fetch_one(f"SELECT COUNT(*) AS n FROM external_paper_notes WHERE {where}", tuple(params))
    rows = await db.fetch_all(
        f"""
        SELECT * FROM external_paper_notes
         WHERE {where}
         ORDER BY {order_sql}
         LIMIT ? OFFSET ?
        """,
        tuple(params + [safe_limit, safe_offset]),
    )
    return {
        "items": [_note_row(row, include_markdown=False) for row in rows],
        "total": int((total_row or {}).get("n") or 0),
        "limit": safe_limit,
        "offset": safe_offset,
        "has_more": safe_offset + len(rows) < int((total_row or {}).get("n") or 0),
        "latest_sync": await latest_sync_run(),
    }


async def get_item(note_id: str) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM external_paper_notes WHERE note_id = ?", (note_id,))
    if not row:
        raise KeyError("External note not found")
    matches = await db.fetch_all(
        "SELECT * FROM external_note_matches WHERE note_id = ? ORDER BY confidence DESC, created_at DESC",
        (note_id,),
    )
    data = _note_row(row, include_markdown=True)
    data["matches"] = matches
    return data


async def update_status(note_id: str, status: str, note: str = "") -> dict[str, Any]:
    status = (status or "").strip()
    if status not in VALID_STATUSES:
        raise ValueError("Invalid external note status")
    await _require_note(note_id)
    await db.execute(
        "UPDATE external_paper_notes SET status = ?, error_msg = ?, updated_at = datetime('now') WHERE note_id = ?",
        (status, note[:1000], note_id),
    )
    await refresh_utility_score(note_id)
    return await get_item(note_id)


async def link_paper(note_id: str, paper_id: str) -> dict[str, Any]:
    await _require_note(note_id)
    paper = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (paper_id,))
    if not paper:
        raise KeyError("Paper not found")
    await db.execute(
        """
        UPDATE external_paper_notes
           SET linked_paper_id = ?, status = 'linked', updated_at = datetime('now')
         WHERE note_id = ?
        """,
        (paper_id, note_id),
    )
    await refresh_matches(note_id)
    await refresh_utility_score(note_id)
    return await get_item(note_id)


async def promote_note(note_id: str, *, collection_id: str = "") -> dict[str, Any]:
    note = await _require_note(note_id)
    linked = str(note.get("linked_paper_id") or "")
    if linked:
        return {"note_id": note_id, "paper_id": linked, "status": "already_promoted"}
    pdf_url = str(note.get("pdf_url") or "")
    arxiv_id = str(note.get("arxiv_id") or "")
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    if not pdf_url:
        raise ValueError("External note has no PDF or arXiv ID")
    settings = get_settings()
    tmp_dir = settings.data_dir / "paper-notes-downloads"
    tmp_path = tmp_dir / f"{note_id}.pdf"
    await _download_pdf(pdf_url, tmp_path)
    data = tmp_path.read_bytes()
    digest = hashlib.sha1(data).hexdigest()
    paper_dir = settings.data_dir / "papers" / digest
    paper_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = paper_dir / "original.pdf"
    if not pdf_path.exists():
        os.replace(tmp_path, pdf_path)
    else:
        tmp_path.unlink(missing_ok=True)
    rel_path = f"papers/{digest}/original.pdf"
    existing = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (digest,))
    if not existing:
        await db.execute(
            """
            INSERT INTO papers (
                paper_id, file_path, original_filename, title, venue, year,
                reading_status, priority, decision
            ) VALUES (?, ?, ?, ?, ?, ?, 'unread', 'medium', '')
            """,
            (
                digest,
                rel_path,
                f"paper-notes-{arxiv_id or note_id}.pdf",
                str(note.get("title") or ""),
                str(note.get("conference") or ""),
                int(note.get("year") or 0),
            ),
        )
        await db.execute(
            """
            INSERT INTO paper_display_cache (
                paper_id, title_zh, summary_source, summary_en, summary_zh,
                source_hash, translation_status, updated_at
            ) VALUES (?, ?, 'external_note', ?, '', ?, 'skipped', datetime('now'))
            ON CONFLICT(paper_id) DO UPDATE SET
                title_zh = excluded.title_zh,
                summary_en = excluded.summary_en,
                updated_at = datetime('now')
            """,
            (
                digest,
                str(note.get("title_zh") or ""),
                str(note.get("summary") or ""),
                hashlib.sha1(str(note.get("summary") or "").encode("utf-8")).hexdigest(),
            ),
        )
    await _ensure_paper_notes_collection()
    await assign_paper_to_collection(
        paper_id=digest,
        collection_id=collection_id or PAPER_NOTES_COLLECTION_ID,
        is_primary=True,
        note=f"Imported from Paper-Notes {str(note.get('source_url') or '')}".strip(),
    )
    await db.execute(
        """
        UPDATE external_paper_notes
           SET linked_paper_id = ?, status = 'promoted', updated_at = datetime('now'), error_msg = ''
         WHERE note_id = ?
        """,
        (digest, note_id),
    )
    await add_item_to_space(
        space_id=EXTERNAL_NOTES_SPACE_ID,
        item_kind="paper",
        item_id=digest,
        paper_id=digest,
        source_type="external_note",
        sync_status="pending",
        note=f"Promoted from external note {note_id}",
    )
    return {"note_id": note_id, "paper_id": digest, "status": "promoted"}


async def start_note_run(
    note_id: str,
    *,
    mode: str = "lens",
    llm_model: str = "",
    language: str = "zh",
    question: str = "",
    owner_token: str = "",
    auto_promote: bool = False,
) -> dict[str, Any]:
    note = await _require_note(note_id)
    paper_id = str(note.get("linked_paper_id") or "")
    if not paper_id:
        if not auto_promote:
            raise ValueError("External note must be promoted before starting a run")
        promoted = await promote_note(note_id)
        paper_id = str(promoted.get("paper_id") or "")
        note = await _require_note(note_id)
    from app.api.runs import start_background_run

    run = await start_background_run(
        paper_id=paper_id,
        mode=mode,
        llm_model=llm_model,
        language=language,
        question=question or "请结合 Paper-Notes 外部笔记和论文原文，分析问题、方法、实验、局限和对当前研究的价值。",
        owner_token=owner_token,
    )
    run_id = str(run.get("run_id") or "")
    await db.execute(
        """
        UPDATE external_paper_notes
           SET linked_paper_id = ?,
               linked_run_id = ?,
               status = CASE WHEN status = 'new' THEN 'promoted' ELSE status END,
               updated_at = datetime('now')
         WHERE note_id = ?
        """,
        (paper_id, run_id, note_id),
    )
    await add_item_to_space(
        space_id=EXTERNAL_NOTES_SPACE_ID,
        item_kind="run",
        item_id=run_id,
        paper_id=paper_id,
        run_id=run_id,
        source_type="external_note",
        sync_status="pending",
        note=f"Run started from external note {note_id}",
    )
    return {"note_id": note_id, "paper_id": paper_id, "run_id": run_id, "status": str(run.get("status") or "pending")}


async def add_note_to_daily(note_id: str, *, topic_id: str = "") -> dict[str, Any]:
    note = await _require_note(note_id)
    arxiv_id = str(note.get("arxiv_id") or "")
    if not arxiv_id:
        raise ValueError("Only external notes with arXiv ID can be added to daily recommendations")
    fetched_date = date.today().isoformat()
    topic = (topic_id or f"paper_notes:{str(note.get('domain') or 'general').strip().lower().replace(' ', '_')}")[:120]
    item_id = hashlib.sha1(f"{arxiv_id}:{topic}:{fetched_date}".encode("utf-8")).hexdigest()[:24]
    await db.execute(
        """
        INSERT INTO daily_recommendation_topics (
            topic_id, name, name_zh, config_json, enabled, sort_order, updated_at
        ) VALUES (?, ?, ?, '{}', 1, 9000, datetime('now'))
        ON CONFLICT(topic_id) DO UPDATE SET enabled = 1, updated_at = datetime('now')
        """,
        (topic, "Paper-Notes", "顶会雷达",),
    )
    await db.execute(
        """
        INSERT INTO daily_recommendation_items (
            item_id, arxiv_id, topic_id, title_en, title_zh, abstract_en, abstract_zh,
            authors_json, primary_category, categories_json, published_at, updated_at,
            arxiv_url, pdf_url, score, score_detail_json, reason,
            title_translation_status, abstract_translation_status, status, fetched_date
        ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, '', ?, ?, ?, ?, ?, ?, 'skipped', 'skipped', 'candidate', ?)
        ON CONFLICT(arxiv_id, topic_id, fetched_date) DO UPDATE SET
            title_en = excluded.title_en,
            title_zh = excluded.title_zh,
            abstract_en = excluded.abstract_en,
            arxiv_url = excluded.arxiv_url,
            pdf_url = excluded.pdf_url,
            score = excluded.score,
            reason = excluded.reason
        """,
        (
            item_id,
            arxiv_id,
            topic,
            str(note.get("title") or ""),
            str(note.get("title_zh") or ""),
            str(note.get("summary") or ""),
            str(note.get("authors_json") or "[]"),
            str(note.get("domain") or ""),
            _json_dumps([str(note.get("domain") or "")] if str(note.get("domain") or "") else []),
            _now(),
            str(note.get("arxiv_url") or ""),
            str(note.get("pdf_url") or ""),
            float(note.get("utility_score") or 0.0),
            _json_dumps({"source": "paper_notes", "note_id": note_id}),
            f"Paper-Notes 外部笔记：{str(note.get('utility_reason') or '')}"[:1000],
            fetched_date,
        ),
    )
    await db.execute(
        "UPDATE external_paper_notes SET linked_daily_item_id = ?, updated_at = datetime('now') WHERE note_id = ?",
        (item_id, note_id),
    )
    return {"note_id": note_id, "item_id": item_id, "topic_id": topic, "status": "candidate"}


async def sync_note_to_space(note_id: str, *, space_id: str = "") -> dict[str, Any]:
    note = await _require_note(note_id)
    target_space = space_id or EXTERNAL_NOTES_SPACE_ID
    item = await add_item_to_space(
        space_id=target_space,
        item_kind="external_note",
        item_id=note_id,
        paper_id=str(note.get("linked_paper_id") or ""),
        run_id=str(note.get("linked_run_id") or ""),
        source_type="external_note",
        sync_status="pending",
        note=f"Paper-Notes source: {str(note.get('source_url') or '')}",
    )
    space = await get_space(target_space)
    dataset_id = str(space.get("dify_dataset_id") or "").strip()
    if not dataset_id:
        await db.execute(
            "UPDATE external_paper_notes SET sync_status = 'skipped', updated_at = datetime('now') WHERE note_id = ?",
            (note_id,),
        )
        return {"item": item, "sync_status": "skipped", "dify_document_id": ""}
    text = _dify_markdown(note)
    try:
        data = await dify_client.create_document_by_text(
            f"Paper-Notes - {str(note.get('title') or note_id)[:120]}",
            text,
            dataset_id=dataset_id,
        )
        document_id = dify_client.extract_document_id(data)
        await update_item(
            space_id=target_space,
            item_kind="external_note",
            item_id=note_id,
            updates={"sync_status": "synced", "dify_document_id": document_id},
        )
        await db.execute(
            """
            UPDATE external_paper_notes
               SET sync_status = 'synced', dify_document_id = ?, updated_at = datetime('now')
             WHERE note_id = ?
            """,
            (document_id, note_id),
        )
        updated_item = await add_item_to_space(
            space_id=target_space,
            item_kind="external_note",
            item_id=note_id,
            paper_id=str(note.get("linked_paper_id") or ""),
            run_id=str(note.get("linked_run_id") or ""),
            source_type="external_note",
            sync_status="synced",
            dify_document_id=document_id,
            note=f"Paper-Notes source: {str(note.get('source_url') or '')}",
        )
        return {"item": updated_item, "sync_status": "synced", "dify_document_id": document_id}
    except Exception as exc:
        await db.execute(
            "UPDATE external_paper_notes SET sync_status = 'failed', error_msg = ?, updated_at = datetime('now') WHERE note_id = ?",
            (str(exc)[:1000], note_id),
        )
        raise


async def generate_note_cards(note_id: str, *, max_cards: int = 4) -> dict[str, Any]:
    note = await _require_note(note_id)
    chunks = [
        ("method", "方法", str(note.get("method") or "")),
        ("claim", "摘要", str(note.get("summary") or "")),
        ("result", "实验", str(note.get("experiments") or "")),
        ("limitation", "局限", str(note.get("limitations") or "")),
    ]
    card_ids: list[str] = []
    for card_type, label, content in chunks[: max(1, min(max_cards, 8))]:
        if not content:
            continue
        card = await create_card(
            {
                "card_type": card_type,
                "title": f"{str(note.get('title') or note_id)[:120]} - {label}",
                "content": content[:2000],
                "paper_id": str(note.get("linked_paper_id") or ""),
                "confidence": 0.6,
                "status": "draft",
                "created_by": "ai",
                "tags": "external_note,paper_notes",
                "source_kind": "external_note",
                "source_ref": note_id,
                "source_quote": str(note.get("source_url") or ""),
                "allow_untraceable": True,
            }
        )
        card_id = str(card.get("card_id") or "")
        if card_id:
            card_ids.append(card_id)
            await add_item_to_space(
                space_id=EXTERNAL_NOTES_SPACE_ID,
                item_kind="card",
                item_id=card_id,
                paper_id=str(note.get("linked_paper_id") or ""),
                source_type="external_note",
                sync_status="pending",
                note=f"Generated from external note {note_id}",
            )
    return {"note_id": note_id, "card_ids": card_ids, "cards_created": len(card_ids)}


async def _upsert_note(ir: Any, *, source_url: str, raw_url: str, commit_sha: str) -> str:
    payload = ir.db_payload()
    await db.execute(
        """
        INSERT INTO external_paper_notes (
            note_id, source_id, source_path, source_url, raw_url, commit_sha, content_hash,
            conference, year, domain, title, title_zh, arxiv_id, arxiv_url, pdf_url,
            code_url, project_url, authors_json, tags_json, keywords_json, summary,
            method, experiments, limitations, related_papers_json, markdown, parsed_json,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(source_id, source_path) DO UPDATE SET
            source_url = excluded.source_url,
            raw_url = excluded.raw_url,
            commit_sha = excluded.commit_sha,
            content_hash = excluded.content_hash,
            conference = excluded.conference,
            year = excluded.year,
            domain = excluded.domain,
            title = excluded.title,
            title_zh = excluded.title_zh,
            arxiv_id = excluded.arxiv_id,
            arxiv_url = excluded.arxiv_url,
            pdf_url = excluded.pdf_url,
            code_url = excluded.code_url,
            project_url = excluded.project_url,
            authors_json = excluded.authors_json,
            tags_json = excluded.tags_json,
            keywords_json = excluded.keywords_json,
            summary = excluded.summary,
            method = excluded.method,
            experiments = excluded.experiments,
            limitations = excluded.limitations,
            related_papers_json = excluded.related_papers_json,
            markdown = excluded.markdown,
            parsed_json = excluded.parsed_json,
            error_msg = '',
            updated_at = datetime('now')
        """,
        (
            payload["note_id"],
            SOURCE_ID,
            payload["source_path"],
            source_url,
            raw_url,
            commit_sha,
            payload["content_hash"],
            payload["conference"],
            payload["year"],
            payload["domain"],
            payload["title"],
            payload["title_zh"],
            payload["arxiv_id"],
            payload["arxiv_url"],
            payload["pdf_url"],
            payload["code_url"],
            payload["project_url"],
            payload["authors_json"],
            payload["tags_json"],
            payload["keywords_json"],
            payload["summary"],
            payload["method"],
            payload["experiments"],
            payload["limitations"],
            payload["related_papers_json"],
            payload["markdown"],
            payload["parsed_json"],
        ),
    )
    row = await db.fetch_one(
        "SELECT note_id FROM external_paper_notes WHERE source_id = ? AND source_path = ?",
        (SOURCE_ID, payload["source_path"]),
    )
    return str((row or {}).get("note_id") or payload["note_id"])


async def _insert_version(note_id: str, ir: Any, commit_sha: str) -> None:
    await db.execute(
        """
        INSERT OR IGNORE INTO external_note_versions (
            version_id, note_id, source_id, source_path, commit_sha, content_hash, markdown, parsed_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            hashlib.sha1(f"{note_id}:{ir.content_hash}".encode("utf-8")).hexdigest()[:24],
            note_id,
            SOURCE_ID,
            ir.source_path,
            commit_sha,
            ir.content_hash,
            ir.markdown,
            _json_dumps(ir.parsed),
        ),
    )


async def _require_note(note_id: str) -> dict[str, Any]:
    row = await db.fetch_one("SELECT * FROM external_paper_notes WHERE note_id = ?", (note_id,))
    if not row:
        raise KeyError("External note not found")
    return row


async def _ensure_paper_notes_collection() -> None:
    await ensure_default_collection()
    await db.execute(
        """
        INSERT INTO paper_collections (
            collection_id, parent_id, name, name_zh, description, description_zh, sort_order
        ) VALUES (?, '', ?, ?, ?, ?, 9010)
        ON CONFLICT(collection_id) DO UPDATE SET
            name = excluded.name,
            name_zh = excluded.name_zh,
            description = excluded.description,
            description_zh = excluded.description_zh,
            updated_at = datetime('now')
        """,
        (
            PAPER_NOTES_COLLECTION_ID,
            "Paper-Notes External Imports",
            "Paper-Notes 外部导入",
            "Papers promoted from external Paper-Notes assets.",
            "从 Paper-Notes 外部笔记确认导入的论文。",
        ),
    )


def _note_row(row: dict[str, Any], *, include_markdown: bool) -> dict[str, Any]:
    data = dict(row)
    data["authors"] = _json_loads(row.get("authors_json"), [])
    data["tags"] = _json_loads(row.get("tags_json"), [])
    data["keywords"] = _json_loads(row.get("keywords_json"), [])
    data["related_papers"] = _json_loads(row.get("related_papers_json"), [])
    data["parsed"] = _json_loads(row.get("parsed_json"), {})
    if not include_markdown:
        data.pop("markdown", None)
        data.pop("parsed_json", None)
    return data


def _sync_row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["errors"] = _json_loads(row.get("error_json"), [])
    return data


def _dify_markdown(note: dict[str, Any]) -> str:
    header = "\n".join(
        [
            "> Source: Paper-Notes",
            f"> URL: {str(note.get('source_url') or '')}",
            f"> GitHub path: {str(note.get('source_path') or '')}",
            f"> Synced commit: {str(note.get('commit_sha') or '')}",
            "> License: CC BY-NC-SA 4.0",
            "",
        ]
    )
    return f"{header}\n# {str(note.get('title') or note.get('note_id') or 'Paper-Notes')}\n\n{str(note.get('markdown') or '')}".strip()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
