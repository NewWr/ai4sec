from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.db import database as db
from app.models.paper_ir import Block, PaperIR, Section

MAIN_SOURCE_SPACE_ID = "main_source"
MAIN_ANALYSIS_SPACE_ID = "main_analysis"
DAILY_SOURCE_SPACE_ID = "daily_source"
DAILY_ANALYSIS_SPACE_ID = "daily_analysis"
DIFY_SYNC_SKIP_DATASET_ID = "__skip_dify_sync__"

VALID_ITEM_KINDS = {"paper", "run", "dify_document", "card", "snippet"}


@dataclass(frozen=True)
class DefaultSpace:
    space_id: str
    name: str
    name_zh: str
    space_type: str
    description: str
    description_zh: str
    dify_dataset_id: str
    sort_order: int


def default_spaces() -> list[DefaultSpace]:
    settings = get_settings()
    return [
        DefaultSpace(
            space_id=MAIN_SOURCE_SPACE_ID,
            name="Main Source Knowledge",
            name_zh="主研究原文知识库",
            space_type="main_source",
            description="User-uploaded and intentionally imported paper source text.",
            description_zh="用户主动上传或确认导入的论文原文解析结果。",
            dify_dataset_id=settings.dify_default_dataset_id.strip(),
            sort_order=10,
        ),
        DefaultSpace(
            space_id=MAIN_ANALYSIS_SPACE_ID,
            name="Main Analysis Knowledge",
            name_zh="主研究解读知识库",
            space_type="main_analysis",
            description="Analysis reports for papers in the main research library.",
            description_zh="主研究库论文的解读报告。",
            dify_dataset_id=settings.dify_analysis_dataset_id.strip(),
            sort_order=20,
        ),
        DefaultSpace(
            space_id=DAILY_SOURCE_SPACE_ID,
            name="Daily Recommendation Source Knowledge",
            name_zh="每日推荐原文知识库",
            space_type="daily_source",
            description="Source text for daily recommendation papers after explicit ingest.",
            description_zh="每日推荐论文经用户确认入库后的原文解析结果。",
            dify_dataset_id=getattr(settings, "daily_recommendation_source_dataset_id", "").strip(),
            sort_order=30,
        ),
        DefaultSpace(
            space_id=DAILY_ANALYSIS_SPACE_ID,
            name="Daily Recommendation Analysis Knowledge",
            name_zh="每日推荐解读知识库",
            space_type="daily_analysis",
            description="Analysis reports generated from daily recommendation papers.",
            description_zh="每日推荐论文生成的 Snap、Lens、Sphere 或 Auto 解读报告。",
            dify_dataset_id=getattr(settings, "daily_recommendation_analysis_dataset_id", "").strip(),
            sort_order=40,
        ),
    ]


async def ensure_default_spaces() -> None:
    for space in default_spaces():
        await db.execute(
            """
            INSERT INTO knowledge_spaces (
                space_id, name, name_zh, space_type, description, description_zh,
                dify_dataset_id, is_system, sort_order, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, datetime('now'))
            ON CONFLICT(space_id) DO UPDATE SET
                space_type = excluded.space_type,
                is_system = 1,
                updated_at = datetime('now')
            """,
            (
                space.space_id,
                space.name,
                space.name_zh,
                space.space_type,
                space.description,
                space.description_zh,
                space.dify_dataset_id,
                space.sort_order,
            ),
        )


async def list_spaces() -> list[dict[str, Any]]:
    await ensure_default_spaces()
    rows = await db.fetch_all(
        """
        SELECT
            ks.*,
            COUNT(ksi.item_id) AS item_count,
            SUM(CASE WHEN ksi.item_kind = 'paper' THEN 1 ELSE 0 END) AS paper_count,
            SUM(CASE WHEN ksi.item_kind = 'run' THEN 1 ELSE 0 END) AS run_count
          FROM knowledge_spaces ks
          LEFT JOIN knowledge_space_items ksi ON ksi.space_id = ks.space_id
         GROUP BY ks.space_id
         ORDER BY ks.sort_order ASC, ks.name ASC
        """
    )
    return [_space_row(row) for row in rows]


async def get_space(space_id: str) -> dict[str, Any]:
    await ensure_default_spaces()
    row = await db.fetch_one("SELECT * FROM knowledge_spaces WHERE space_id = ?", (_clean_id(space_id),))
    if not row:
        raise ValueError("Knowledge space not found")
    return _space_row(row)


async def update_space(space_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    space_id = _clean_id(space_id)
    current = await get_space(space_id)
    allowed = {"name", "name_zh", "description", "description_zh", "dify_dataset_id", "sort_order"}
    assignments: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key not in updates or updates[key] is None:
            continue
        if key == "sort_order":
            assignments.append("sort_order = ?")
            params.append(int(updates[key]))
        else:
            assignments.append(f"{key} = ?")
            params.append(str(updates[key]).strip()[:2000])
    if not assignments:
        return current
    params.append(space_id)
    await db.execute(
        f"""
        UPDATE knowledge_spaces
           SET {', '.join(assignments)}, updated_at = datetime('now')
         WHERE space_id = ?
        """,
        tuple(params),
    )
    return await get_space(space_id)


async def create_dify_dataset_for_space(
    space_id: str,
    *,
    name: str = "",
    indexing_technique: str = "economy",
    permission: str = "only_me",
) -> dict[str, Any]:
    space = await get_space(space_id)
    settings = get_settings()
    if not settings.dify_enabled:
        raise ValueError("Dify is not configured")
    dataset_name = (name or space.get("name_zh") or space.get("name") or space["space_id"]).strip()
    from app.services import dify_client

    dataset = await dify_client.create_dataset(
        dataset_name,
        indexing_technique=indexing_technique or "economy",
        permission=permission or "only_me",
    )
    dataset_id = _extract_dataset_id(dataset)
    if not dataset_id:
        raise ValueError("Dify response did not include dataset id")
    updated = await update_space(str(space["space_id"]), {"dify_dataset_id": dataset_id})
    await _mark_skipped_items_pending(str(space["space_id"]))
    return {"space": updated, "dataset": dataset}


async def list_space_dify_documents(space_id: str, *, page: int = 1, limit: int = 20) -> dict[str, Any]:
    space = await get_space(space_id)
    dataset_id = str(space.get("dify_dataset_id") or "").strip()
    if not dataset_id:
        raise ValueError("Knowledge space has no Dify dataset")
    from app.services import dify_client

    data = await dify_client.list_documents(dataset_id=dataset_id, page=page, limit=limit)
    return {"space": space, **_normalize_dify_page(data, page=page, limit=limit)}


async def get_space_dify_markdown(space_id: str, document_id: str) -> dict[str, Any]:
    space = await get_space(space_id)
    dataset_id = str(space.get("dify_dataset_id") or "").strip()
    if not dataset_id:
        raise ValueError("Knowledge space has no Dify dataset")
    from app.services import dify_client

    data = await dify_client.get_markdown(document_id, dataset_id=dataset_id)
    content = ""
    if isinstance(data, dict):
        content = str(data.get("content") or data.get("markdown") or "")
    return {
        "space": space,
        "content": content,
        "document_name": str((data or {}).get("document_name") or (data or {}).get("name") or ""),
        "raw": data if isinstance(data, dict) else {},
    }


async def list_space_items(space_id: str, *, item_kind: str = "", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    space_id = _clean_id(space_id)
    await get_space(space_id)
    clauses = ["ksi.space_id = ?"]
    params: list[Any] = [space_id]
    if item_kind:
        if item_kind not in VALID_ITEM_KINDS:
            raise ValueError("Invalid knowledge item kind")
        clauses.append("ksi.item_kind = ?")
        params.append(item_kind)
    rows = await db.fetch_all(
        f"""
        SELECT
            ksi.*,
            COALESCE(p.title, '') AS paper_title,
            COALESCE(p.original_filename, '') AS original_filename,
            COALESCE(pdc.title_zh, '') AS paper_title_zh,
            COALESCE(r.mode, '') AS run_mode,
            COALESCE(r.status, '') AS run_status,
            COALESCE(r.started_at, '') AS run_started_at
          FROM knowledge_space_items ksi
          LEFT JOIN papers p ON p.paper_id = ksi.paper_id
          LEFT JOIN paper_display_cache pdc ON pdc.paper_id = ksi.paper_id
          LEFT JOIN runs r ON r.run_id = ksi.run_id
         WHERE {' AND '.join(clauses)}
         ORDER BY ksi.updated_at DESC, ksi.created_at DESC
         LIMIT ? OFFSET ?
        """,
        tuple(params + [max(1, min(limit, 500)), max(0, offset)]),
    )
    return [_item_row(row) for row in rows]


async def add_item_to_space(
    *,
    space_id: str,
    item_kind: str,
    item_id: str,
    paper_id: str = "",
    run_id: str = "",
    source_type: str = "",
    sync_status: str = "pending",
    dify_document_id: str = "",
    note: str = "",
) -> dict[str, Any]:
    space_id = _clean_id(space_id)
    item_kind = _clean_id(item_kind)
    item_id = _clean_id(item_id)
    if item_kind not in VALID_ITEM_KINDS:
        raise ValueError("Invalid knowledge item kind")
    if not item_id:
        raise ValueError("Knowledge item id is required")
    await get_space(space_id)
    await db.execute(
        """
        INSERT INTO knowledge_space_items (
            space_id, item_kind, item_id, paper_id, run_id, source_type,
            sync_status, dify_document_id, note, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(space_id, item_kind, item_id) DO UPDATE SET
            paper_id = excluded.paper_id,
            run_id = excluded.run_id,
            source_type = excluded.source_type,
            sync_status = excluded.sync_status,
            dify_document_id = excluded.dify_document_id,
            note = excluded.note,
            updated_at = datetime('now')
        """,
        (
            space_id,
            item_kind,
            item_id,
            _clean_id(paper_id),
            _clean_id(run_id),
            _clean_id(source_type),
            _clean_id(sync_status) or "pending",
            _clean_id(dify_document_id),
            (note or "").strip()[:1000],
        ),
    )
    row = await _get_item(space_id=space_id, item_kind=item_kind, item_id=item_id)
    if not row:
        raise ValueError("Knowledge item was not saved")
    return _item_row(row)


async def move_item(*, space_id: str, item_kind: str, item_id: str, target_space_id: str) -> dict[str, Any]:
    source_space_id = _clean_id(space_id)
    target_space_id = _clean_id(target_space_id)
    item_kind = _clean_id(item_kind)
    item_id = _clean_id(item_id)
    row = await _require_item(space_id=source_space_id, item_kind=item_kind, item_id=item_id)
    await get_space(target_space_id)
    async with db.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO knowledge_space_items (
                space_id, item_kind, item_id, paper_id, run_id, source_type,
                sync_status, dify_document_id, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(space_id, item_kind, item_id) DO UPDATE SET
                paper_id = excluded.paper_id,
                run_id = excluded.run_id,
                source_type = excluded.source_type,
                sync_status = excluded.sync_status,
                dify_document_id = excluded.dify_document_id,
                note = excluded.note,
                updated_at = datetime('now')
            """,
            (
                target_space_id,
                item_kind,
                item_id,
                str(row.get("paper_id") or ""),
                str(row.get("run_id") or ""),
                str(row.get("source_type") or ""),
                str(row.get("sync_status") or "pending"),
                str(row.get("dify_document_id") or ""),
                str(row.get("note") or ""),
                str(row.get("created_at") or ""),
            ),
        )
        await conn.execute(
            "DELETE FROM knowledge_space_items WHERE space_id = ? AND item_kind = ? AND item_id = ?",
            (source_space_id, item_kind, item_id),
        )
    moved = await _get_item(space_id=target_space_id, item_kind=item_kind, item_id=item_id)
    if not moved:
        raise ValueError("Knowledge item move failed")
    return _item_row(moved)


async def copy_item(*, space_id: str, item_kind: str, item_id: str, target_space_id: str) -> dict[str, Any]:
    source_space_id = _clean_id(space_id)
    target_space_id = _clean_id(target_space_id)
    item_kind = _clean_id(item_kind)
    item_id = _clean_id(item_id)
    row = await _require_item(space_id=source_space_id, item_kind=item_kind, item_id=item_id)
    return await add_item_to_space(
        space_id=target_space_id,
        item_kind=item_kind,
        item_id=item_id,
        paper_id=str(row.get("paper_id") or ""),
        run_id=str(row.get("run_id") or ""),
        source_type=str(row.get("source_type") or ""),
        sync_status=str(row.get("sync_status") or "pending"),
        dify_document_id=str(row.get("dify_document_id") or ""),
        note=str(row.get("note") or ""),
    )


async def remove_item(*, space_id: str, item_kind: str, item_id: str) -> None:
    row = await _require_item(space_id=_clean_id(space_id), item_kind=_clean_id(item_kind), item_id=_clean_id(item_id))
    await db.execute(
        "DELETE FROM knowledge_space_items WHERE space_id = ? AND item_kind = ? AND item_id = ?",
        (str(row["space_id"]), str(row["item_kind"]), str(row["item_id"])),
    )


async def update_item(
    *,
    space_id: str,
    item_kind: str,
    item_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    row = await _require_item(space_id=_clean_id(space_id), item_kind=_clean_id(item_kind), item_id=_clean_id(item_id))
    allowed = {"note", "sync_status", "dify_document_id"}
    assignments: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key not in updates or updates[key] is None:
            continue
        assignments.append(f"{key} = ?")
        params.append(str(updates[key]).strip()[:1000])
    if not assignments:
        return _item_row(row)
    params.extend([str(row["space_id"]), str(row["item_kind"]), str(row["item_id"])])
    await db.execute(
        f"""
        UPDATE knowledge_space_items
           SET {', '.join(assignments)}, updated_at = datetime('now')
         WHERE space_id = ? AND item_kind = ? AND item_id = ?
        """,
        tuple(params),
    )
    updated = await _get_item(
        space_id=str(row["space_id"]),
        item_kind=str(row["item_kind"]),
        item_id=str(row["item_id"]),
    )
    if not updated:
        raise ValueError("Knowledge space item not found")
    return _item_row(updated)


async def promote_daily_item(
    item_id: str,
    *,
    source_target_space_id: str = MAIN_SOURCE_SPACE_ID,
    analysis_target_space_id: str = MAIN_ANALYSIS_SPACE_ID,
    copy: bool = True,
) -> dict[str, Any]:
    row = await db.fetch_one(
        "SELECT * FROM daily_recommendation_items WHERE item_id = ?",
        (_clean_id(item_id),),
    )
    if not row:
        raise ValueError("Daily recommendation item not found")
    paper_id = str(row.get("linked_paper_id") or "")
    run_id = str(row.get("linked_run_id") or "")
    if not paper_id:
        raise ValueError("Daily recommendation item has not been ingested")

    promoted: list[dict[str, Any]] = []
    source_row = await _get_item(space_id=DAILY_SOURCE_SPACE_ID, item_kind="paper", item_id=paper_id)
    if source_row:
        promoted.append(
            await (copy_item if copy else move_item)(
                space_id=DAILY_SOURCE_SPACE_ID,
                item_kind="paper",
                item_id=paper_id,
                target_space_id=source_target_space_id,
            )
        )
    else:
        promoted.append(
            await add_item_to_space(
                space_id=source_target_space_id,
                item_kind="paper",
                item_id=paper_id,
                paper_id=paper_id,
                source_type="daily_promoted",
                sync_status="pending",
                note=f"Promoted from daily recommendation {item_id}",
            )
        )

    if run_id:
        analysis_row = await _get_item(space_id=DAILY_ANALYSIS_SPACE_ID, item_kind="run", item_id=run_id)
        if analysis_row:
            promoted.append(
                await (copy_item if copy else move_item)(
                    space_id=DAILY_ANALYSIS_SPACE_ID,
                    item_kind="run",
                    item_id=run_id,
                    target_space_id=analysis_target_space_id,
                )
            )
        else:
            promoted.append(
                await add_item_to_space(
                    space_id=analysis_target_space_id,
                    item_kind="run",
                    item_id=run_id,
                    paper_id=paper_id,
                    run_id=run_id,
                    source_type="daily_promoted",
                    sync_status="pending",
                    note=f"Promoted from daily recommendation {item_id}",
                )
            )

    await db.execute(
        "UPDATE daily_recommendation_items SET status = 'interested', error_msg = '' WHERE item_id = ?",
        (_clean_id(item_id),),
    )
    return {
        "item_id": item_id,
        "paper_id": paper_id,
        "run_id": run_id,
        "promoted_items": promoted,
    }


async def resync_item(*, space_id: str, item_kind: str, item_id: str, force: bool = True) -> dict[str, Any]:
    item = await _require_item(space_id=_clean_id(space_id), item_kind=_clean_id(item_kind), item_id=_clean_id(item_id))
    space = await get_space(str(item["space_id"]))
    dataset_id = str(space.get("dify_dataset_id") or "").strip()
    if not dataset_id:
        return await update_item(
            space_id=str(item["space_id"]),
            item_kind=str(item["item_kind"]),
            item_id=str(item["item_id"]),
            updates={"sync_status": "skipped", "dify_document_id": ""},
        )
    if str(item["item_kind"]) == "paper":
        from app.services.dify_sync import sync_paper_ir_to_dify

        paper_id = str(item.get("paper_id") or item.get("item_id") or "")
        paper_ir = await _load_paper_ir_from_blocks(paper_id)
        result = await sync_paper_ir_to_dify(paper_id, paper_ir, dataset_id=dataset_id, force=force)
        return await update_item(
            space_id=str(item["space_id"]),
            item_kind=str(item["item_kind"]),
            item_id=str(item["item_id"]),
            updates={"sync_status": result.status, "dify_document_id": result.document_id},
        )
    if str(item["item_kind"]) == "run":
        from app.services.dify_sync import sync_analysis_to_dify

        run_id = str(item.get("run_id") or item.get("item_id") or "")
        run = await db.fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        output = await db.fetch_one("SELECT * FROM run_outputs WHERE run_id = ?", (run_id,))
        if not run or not output:
            raise ValueError("Run output not found")
        paper_id = str(run.get("paper_id") or item.get("paper_id") or "")
        paper = await db.fetch_one("SELECT title FROM papers WHERE paper_id = ?", (paper_id,))
        result = await sync_analysis_to_dify(
            run_id=run_id,
            paper_id=paper_id,
            markdown=str(output.get("markdown") or ""),
            mode=str(run.get("mode") or "analysis"),
            language=str(run.get("language") or "en"),
            title=str((paper or {}).get("title") or ""),
            dataset_id=dataset_id,
        )
        return await update_item(
            space_id=str(item["space_id"]),
            item_kind=str(item["item_kind"]),
            item_id=str(item["item_id"]),
            updates={"sync_status": result.status, "dify_document_id": result.document_id},
        )
    raise ValueError("Only paper and run items can be resynced")


async def source_dataset_for_paper(paper_id: str) -> str:
    row = await _first_space_for_paper(_clean_id(paper_id), item_kind="paper")
    if not row:
        return get_settings().dify_default_dataset_id.strip()
    dataset_id = str(row.get("dify_dataset_id") or "").strip()
    if str(row.get("space_id") or "") == DAILY_SOURCE_SPACE_ID and not dataset_id:
        return DIFY_SYNC_SKIP_DATASET_ID
    return dataset_id


async def analysis_dataset_for_run(run_id: str, paper_id: str = "") -> str:
    run_id = _clean_id(run_id)
    row = await _first_space_for_run(run_id)
    if row:
        dataset_id = str(row.get("dify_dataset_id") or "").strip()
        if str(row.get("space_id") or "") == DAILY_ANALYSIS_SPACE_ID and not dataset_id:
            return DIFY_SYNC_SKIP_DATASET_ID
        return dataset_id
    if paper_id:
        paper_row = await _first_space_for_paper(_clean_id(paper_id), item_kind="paper")
        if paper_row and str(paper_row.get("space_id") or "") == DAILY_SOURCE_SPACE_ID:
            daily_analysis = await get_space(DAILY_ANALYSIS_SPACE_ID)
            dataset_id = str(daily_analysis.get("dify_dataset_id") or "").strip()
            return dataset_id or DIFY_SYNC_SKIP_DATASET_ID
    return get_settings().dify_analysis_dataset_id.strip()


async def _first_space_for_paper(paper_id: str, *, item_kind: str) -> dict[str, Any] | None:
    await ensure_default_spaces()
    return await db.fetch_one(
        """
        SELECT ks.*
          FROM knowledge_space_items ksi
          JOIN knowledge_spaces ks ON ks.space_id = ksi.space_id
         WHERE ksi.paper_id = ? AND ksi.item_kind = ?
         ORDER BY
           CASE ksi.space_id
             WHEN 'daily_source' THEN 0
             WHEN 'main_source' THEN 1
             ELSE 2
           END,
           ks.sort_order ASC
         LIMIT 1
        """,
        (paper_id, item_kind),
    )


async def _first_space_for_run(run_id: str) -> dict[str, Any] | None:
    await ensure_default_spaces()
    return await db.fetch_one(
        """
        SELECT ks.*
          FROM knowledge_space_items ksi
          JOIN knowledge_spaces ks ON ks.space_id = ksi.space_id
         WHERE ksi.run_id = ? AND ksi.item_kind = 'run'
         ORDER BY
           CASE ksi.space_id
             WHEN 'daily_analysis' THEN 0
             WHEN 'main_analysis' THEN 1
             ELSE 2
           END,
           ks.sort_order ASC
         LIMIT 1
        """,
        (run_id,),
    )


async def _require_item(*, space_id: str, item_kind: str, item_id: str) -> dict[str, Any]:
    row = await _get_item(space_id=space_id, item_kind=item_kind, item_id=item_id)
    if not row:
        raise ValueError("Knowledge space item not found")
    return row


async def _get_item(*, space_id: str, item_kind: str, item_id: str) -> dict[str, Any] | None:
    return await db.fetch_one(
        """
        SELECT
            ksi.*,
            COALESCE(p.title, '') AS paper_title,
            COALESCE(p.original_filename, '') AS original_filename,
            COALESCE(pdc.title_zh, '') AS paper_title_zh,
            COALESCE(r.mode, '') AS run_mode,
            COALESCE(r.status, '') AS run_status,
            COALESCE(r.started_at, '') AS run_started_at
          FROM knowledge_space_items ksi
          LEFT JOIN papers p ON p.paper_id = ksi.paper_id
          LEFT JOIN paper_display_cache pdc ON pdc.paper_id = ksi.paper_id
          LEFT JOIN runs r ON r.run_id = ksi.run_id
         WHERE ksi.space_id = ? AND ksi.item_kind = ? AND ksi.item_id = ?
        """,
        (space_id, item_kind, item_id),
    )


def _space_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "space_id": str(row.get("space_id") or ""),
        "name": str(row.get("name") or ""),
        "name_zh": str(row.get("name_zh") or ""),
        "space_type": str(row.get("space_type") or ""),
        "description": str(row.get("description") or ""),
        "description_zh": str(row.get("description_zh") or ""),
        "dify_dataset_id": str(row.get("dify_dataset_id") or ""),
        "is_system": bool(row.get("is_system") or 0),
        "sort_order": int(row.get("sort_order") or 0),
        "item_count": int(row.get("item_count") or 0),
        "paper_count": int(row.get("paper_count") or 0),
        "run_count": int(row.get("run_count") or 0),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _item_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "space_id": str(row.get("space_id") or ""),
        "item_kind": str(row.get("item_kind") or ""),
        "item_id": str(row.get("item_id") or ""),
        "paper_id": str(row.get("paper_id") or ""),
        "run_id": str(row.get("run_id") or ""),
        "source_type": str(row.get("source_type") or ""),
        "sync_status": str(row.get("sync_status") or "pending"),
        "dify_document_id": str(row.get("dify_document_id") or ""),
        "note": str(row.get("note") or ""),
        "paper_title": str(row.get("paper_title") or ""),
        "paper_title_zh": str(row.get("paper_title_zh") or ""),
        "original_filename": str(row.get("original_filename") or ""),
        "run_mode": str(row.get("run_mode") or ""),
        "run_status": str(row.get("run_status") or ""),
        "run_started_at": str(row.get("run_started_at") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _extract_dataset_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    candidates: list[Any] = [data.get("id"), data.get("dataset_id")]
    nested = data.get("data")
    if isinstance(nested, dict):
        candidates.extend([nested.get("id"), nested.get("dataset_id")])
    dataset = data.get("dataset")
    if isinstance(dataset, dict):
        candidates.extend([dataset.get("id"), dataset.get("dataset_id")])
    for value in candidates:
        if value:
            return str(value)
    return ""


def _normalize_dify_page(data: Any, *, page: int, limit: int) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"data": [], "has_more": False, "total": 0, "page": page, "limit": limit}
    raw_items = data.get("data")
    if raw_items is None:
        raw_items = data.get("documents")
    items = raw_items if isinstance(raw_items, list) else []
    return {
        "data": items,
        "has_more": bool(data.get("has_more") or False),
        "total": int(data.get("total") or len(items)),
        "page": int(data.get("page") or page),
        "limit": int(data.get("limit") or limit),
    }


async def _mark_skipped_items_pending(space_id: str) -> None:
    await db.execute(
        """
        UPDATE knowledge_space_items
           SET sync_status = 'pending',
               updated_at = datetime('now')
         WHERE space_id = ?
           AND item_kind IN ('paper', 'run')
           AND sync_status = 'skipped'
        """,
        (space_id,),
    )


def _clean_id(value: str) -> str:
    return (value or "").strip()[:200]


async def _load_paper_ir_from_blocks(paper_id: str) -> PaperIR:
    rows = await db.fetch_all(
        "SELECT * FROM blocks WHERE paper_id = ? ORDER BY order_idx ASC",
        (paper_id,),
    )
    if not rows:
        raise ValueError("PaperIR blocks not found; run analysis first")

    blocks: list[Block] = []
    title = ""
    for row in rows:
        block = Block(
            type=str(row.get("type") or ""),
            sub_type=str(row.get("sub_type") or ""),
            page_idx=int(row.get("page_idx") or 0),
            bbox=[],
            text=str(row.get("text") or ""),
            section_path=str(row.get("section_path") or ""),
            order_idx=int(row.get("order_idx") or 0),
        )
        if not title and block.type == "title" and block.text.strip():
            title = block.text.strip()
        blocks.append(block)

    paper = await db.fetch_one("SELECT title FROM papers WHERE paper_id = ?", (paper_id,))
    title = str((paper or {}).get("title") or title or "")
    by_path: dict[str, list[Block]] = {}
    for block in blocks:
        by_path.setdefault(block.section_path or "", []).append(block)
    sections = [
        Section(path=path, title=path.split("/")[-1] if path else "", blocks=section_blocks)
        for path, section_blocks in by_path.items()
    ]
    return PaperIR(paper_id=paper_id, title=title, sections=sections, blocks=blocks)
