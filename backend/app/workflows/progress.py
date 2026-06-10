from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from app.db import database as db

logger = logging.getLogger("scholar.progress")


async def persist_run_event(run_id: str, event_type: str, data: dict[str, Any]) -> int:
    """Persist one resumable run event and return its monotonically increasing seq."""
    if not run_id:
        return 0
    payload = json.dumps(data, ensure_ascii=False)
    event_type = (event_type or "progress").strip() or "progress"
    try:
        async with aiosqlite.connect(db.get_db_path()) as conn:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM run_progress_events WHERE run_id = ?",
                (run_id,),
            )
            row = await cursor.fetchone()
            seq = int(row[0] if row else 1)
            await conn.execute(
                "INSERT INTO run_progress_events (run_id, seq, event_type, data_json) VALUES (?, ?, ?, ?)",
                (run_id, seq, event_type, payload),
            )
            await conn.commit()
            return seq
    except Exception as e:
        logger.debug("persist_run_event failed run=%s event=%s: %s", run_id, event_type, e)
        return 0


async def emit_progress(run_id: str, step: str, status: str, **extra: Any) -> None:
    """Single source of truth for per-step progress.

    1. Push to the in-memory SSE queue (live clients receive it instantly).
    2. Persist to `runs.current_step` + append to `runs.progress_json`.
       The DB write lets a client that reconnected after navigating away
       (queue already popped, status still `running`) recover the step list.

    Both legs are best-effort: failures are logged but never raised.
    """
    if not run_id:
        return

    payload: dict[str, Any] = {"step": step, "status": status}
    if extra:
        payload.update(extra)
    seq = await persist_run_event(run_id, "progress", payload)

    # Leg 1: in-memory queue for live SSE consumers.
    try:
        from app.api.runs import _run_queues

        subscribers = _run_queues.get(run_id)
        if subscribers:
            message = {"event": "progress", "data": payload, "seq": seq}
            if hasattr(subscribers, "put"):
                await subscribers.put(message)
            else:
                for queue in list(subscribers):
                    await queue.put(message)
    except Exception as e:
        logger.debug("emit_progress: queue push failed run=%s step=%s: %s", run_id, step, e)

    # Leg 2: persist so reloads / late polls can see what happened.
    try:
        await db.execute(
            """
            UPDATE runs
               SET current_step = ?,
                   progress_json = json_insert(
                       COALESCE(NULLIF(progress_json, ''), '[]'),
                       '$[#]',
                       json(?)
                   )
             WHERE run_id = ?
            """,
            (step, json.dumps(payload, ensure_ascii=False), run_id),
        )
    except Exception as e:
        logger.debug("emit_progress: DB persist failed run=%s step=%s: %s", run_id, step, e)
