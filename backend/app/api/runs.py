from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.graph.state import CompiledStateGraph

from app.db import database as db
from app.rate_limit import limiter
from app.models.schemas import RecentRunResponse, RunCreate, RunOutputResponse, RunResponse
from app.services.evidence_anchorer import ANCHOR_SCHEMA_VERSION, build_evidence_anchors
from app.services.llm_runtime_config import get_llm_runtime_config
from app.services.mineru_adapter import cancel_parse
from app.services.paper_collections import load_paper_ir_from_blocks
from app.workflows.main_graph import build_main_graph
from app.workflows.progress import emit_progress, persist_run_event
from app.workflows.state import MainGraphState

logger = logging.getLogger("scholar.runs")

router = APIRouter(tags=["runs"])

# In-memory SSE subscribers per run. Each connected browser gets its own queue.
_run_queues: dict[str, set[asyncio.Queue]] = {}

# Background tasks for active runs; used to cancel work when a run is dismissed.
_run_tasks: dict[str, asyncio.Task[None]] = {}

# Compiled graph (lazy init)
_compiled_graph: CompiledStateGraph | None = None

# Limit concurrent background run executions
_run_semaphore = asyncio.Semaphore(5)


def _get_graph() -> CompiledStateGraph:
    global _compiled_graph
    if _compiled_graph is None:
        graph = build_main_graph()
        _compiled_graph = graph.compile()
    return _compiled_graph


_VALID_INPUT_MODES = {"snap", "lens", "sphere", "auto"}
_MAX_QUESTION_LEN = 2000
_MAX_OWNER_TOKEN_LEN = 100

# A run still pending/running past this many seconds has lost its owning
# background task (the process restarted, or it hung well past the 30-min SSE
# window), so it can never finish on its own. It is reconciled to 'failed' on
# read so the recent-runs banner stops showing zombies. Comfortably beyond any
# legitimate run, which the SSE stream caps at 1800s.
_STALE_RUN_SECONDS = 3600

# Never surface runs older than this in the recent list — older history is not
# useful for recovery and only clutters the UI.
_RECENT_RUN_DAYS = 7
_STREAM_POLL_SECONDS = 2.0
_STREAM_TIMEOUT_SECONDS = 1800.0


def _terminal_event_from_status(run_id: str, row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("status") or "")
    if status == "done":
        return {"event": "done", "data": {"run_id": run_id, "status": "done"}}
    return {
        "event": "error",
        "data": {"error": str(row.get("error_msg") or "Run failed"), "status": status or "failed"},
    }


def _sse_frame(message: dict[str, Any]) -> str:
    seq = int(message.get("seq") or 0)
    payload = {
        "event": str(message.get("event") or "message"),
        "data": message.get("data") or {},
    }
    if seq > 0:
        payload["seq"] = seq
    prefix = f"id: {seq}\n" if seq > 0 else ""
    return f"{prefix}data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _parse_since_seq(request: Request, since_seq: int) -> int:
    last_event_id = request.headers.get("last-event-id", "").strip()
    raw = last_event_id or str(since_seq or 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


async def _fetch_run_event_messages(run_id: str, since_seq: int) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        """
        SELECT seq, event_type, data_json
          FROM run_progress_events
         WHERE run_id = ? AND seq > ?
         ORDER BY seq ASC
        """,
        (run_id, since_seq),
    )
    messages: list[dict[str, Any]] = []
    for row in rows:
        try:
            data = json.loads(str(row.get("data_json") or "{}"))
        except Exception:
            data = {}
        messages.append(
            {
                "seq": int(row.get("seq") or 0),
                "event": str(row.get("event_type") or "progress"),
                "data": data if isinstance(data, dict) else {},
            }
        )
    return messages


async def _publish_live_message(run_id: str, message: dict[str, Any]) -> None:
    subscribers = _run_queues.get(run_id)
    if not subscribers:
        return
    for queue in list(subscribers):
        await queue.put(message)


async def _publish_run_event(run_id: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
    seq = await persist_run_event(run_id, event, data)
    message = {"event": event, "data": data, "seq": seq}
    await _publish_live_message(run_id, message)
    return message


async def _close_live_streams(run_id: str) -> None:
    subscribers = _run_queues.pop(run_id, set())
    for queue in list(subscribers):
        await queue.put(None)


async def _reconcile_stale_runs() -> None:
    """Mark abandoned pending/running runs as failed (self-healing on read)."""
    await db.execute(
        "UPDATE runs SET status = 'failed', "
        "error_msg = 'Interrupted (task no longer running)', "
        "finished_at = datetime('now') "
        "WHERE status IN ('pending', 'running') "
        "AND started_at < datetime('now', ?)",
        (f"-{_STALE_RUN_SECONDS} seconds",),
    )


@router.post("/runs", response_model=RunResponse)
@limiter.limit("3/minute")
async def create_run(request: Request, req: RunCreate):
    return RunResponse(**await start_background_run(
        paper_id=req.paper_id,
        mode=req.mode,
        llm_model=req.llm_model,
        language=req.language,
        question=req.question,
        owner_token=req.owner_token,
    ))


async def start_background_run(
    *,
    paper_id: str,
    mode: str = "snap",
    llm_model: str = "",
    language: str = "en",
    question: str = "",
    owner_token: str = "",
) -> dict[str, Any]:
    # Verify paper exists
    paper = await db.fetch_one("SELECT paper_id FROM papers WHERE paper_id = ?", (paper_id,))
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    mode = mode if mode in _VALID_INPUT_MODES else "snap"
    language = language if language in ("en", "zh") else "en"
    question = (question or "").strip()[:_MAX_QUESTION_LEN]
    owner_token = (owner_token or "").strip()[:_MAX_OWNER_TOKEN_LEN]

    # Only allow models the operator explicitly configured (THINKING_MODELNAME).
    # An unknown model name is dropped to the default rather than forwarded to
    # the LLM backend, so a caller can't point a run at an arbitrary/unauthorised
    # (e.g. far more expensive) model. When no list is configured we can't
    # validate, so pass through unchanged.
    allowed_models = get_llm_runtime_config().thinking_models
    llm_model = (llm_model or "").strip()
    if llm_model and allowed_models and llm_model not in allowed_models:
        logger.warning(f"[run] Rejected unknown llm_model={llm_model!r}; using default")
        llm_model = ""

    if mode == "auto" and not question:
        raise HTTPException(status_code=400, detail="Smart Q&A mode requires a non-empty question")

    run_id = uuid.uuid4().hex[:16]
    await db.execute(
        "INSERT INTO runs (run_id, paper_id, mode, llm_model, language, status, user_question, owner_token) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
        (run_id, paper_id, mode, llm_model, language, question, owner_token),
    )

    # Create subscriber set for SSE
    _run_queues[run_id] = set()

    logger.info(
        f"[run:{run_id}] Created run paper={paper_id} mode={mode} model={llm_model or '(default)'} lang={language} q={'(yes)' if question else '(no)'}"
    )

    # Launch graph in background
    task = asyncio.create_task(_execute_run(run_id, paper_id, mode, llm_model, language, question))
    _run_tasks[run_id] = task
    task.add_done_callback(lambda _task, _run_id=run_id: _run_tasks.pop(_run_id, None))

    row = await db.fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=500, detail="Run creation failed")
    return row


async def _execute_run(
    run_id: str,
    paper_id: str,
    mode: str,
    llm_model: str,
    language: str = "en",
    user_question: str = "",
) -> None:
    """Execute the LangGraph workflow as a background task, bounded by semaphore."""
    acquired = False
    t0 = time.perf_counter()

    try:
        try:
            await asyncio.wait_for(_run_semaphore.acquire(), timeout=300.0)
            acquired = True
        except asyncio.TimeoutError:
            logger.warning(f"[run:{run_id}] Timed out waiting for execution slot")
            await db.execute(
                "UPDATE runs SET status = 'failed', error_msg = 'Server busy, please retry later', finished_at = datetime('now') "
                "WHERE run_id = ? AND status IN ('pending', 'running')",
                (run_id,),
            )
            await _publish_run_event(run_id, "error", {"error": "Server busy, please retry later"})
            return

        await db.execute(
            "UPDATE runs SET status = 'running', started_at = datetime('now') "
            "WHERE run_id = ? AND status IN ('pending', 'running')",
            (run_id,),
        )

        await _publish_run_event(run_id, "status", {"status": "running"})

        logger.info(f"[run:{run_id}] ▶ Graph execution started")

        initial_state: MainGraphState = {
            "paper_id": paper_id,
            "run_id": run_id,
            "mode": mode,
            "llm_model": llm_model,
            "language": language,
            "user_question": user_question,
            "progress": [],
        }

        graph = _get_graph()

        # Stream through graph nodes
        final_state: dict[str, Any] = {}
        async for event in graph.astream(initial_state):
            # event is a dict mapping node_name -> output_dict
            for node_name, node_output in event.items():
                elapsed = time.perf_counter() - t0
                final_state.update(node_output)
                progress = node_output.get("progress", [])
                latest = progress[-1] if progress else {"step": node_name, "status": "done"}
                logger.info(f"[run:{run_id}] ✔ Node '{node_name}' done at {elapsed:.1f}s — {latest}")
                step = latest.get("step", node_name)
                status = latest.get("status", "done")
                extra = {k: v for k, v in latest.items() if k not in ("step", "status")}
                await emit_progress(run_id, step, status, **extra)

        elapsed = time.perf_counter() - t0
        error = final_state.get("error")
        if error:
            logger.error(f"[run:{run_id}] ✗ Graph failed at {elapsed:.1f}s — {error}")
            await _publish_run_event(run_id, "error", {"error": error})
        elif final_state.get("persist_skipped"):
            logger.info(f"[run:{run_id}] Graph completed after run became inactive at {elapsed:.1f}s")
        else:
            logger.info(f"[run:{run_id}] ✔ Graph completed at {elapsed:.1f}s")
            await _publish_run_event(run_id, "done", {"run_id": run_id, "status": "done"})

    except asyncio.CancelledError:
        elapsed = time.perf_counter() - t0
        logger.info(f"[run:{run_id}] Cancelled at {elapsed:.1f}s")
        run_row = await db.fetch_one("SELECT status FROM runs WHERE run_id = ?", (run_id,))
        run_status = str((run_row or {}).get("status") or "")
        if run_status in ("pending", "running"):
            await db.execute(
                "UPDATE runs SET status = 'failed', error_msg = 'Cancelled by user', finished_at = datetime('now') "
                "WHERE run_id = ? AND status IN ('pending', 'running')",
                (run_id,),
            )
        if run_status in ("pending", "running"):
            await _publish_run_event(run_id, "cancelled", {"error": "Cancelled by user"})
        raise

    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.exception(f"[run:{run_id}] ✗ Graph exception at {elapsed:.1f}s — {e}")
        await db.execute(
            "UPDATE runs SET status = 'failed', error_msg = ?, finished_at = datetime('now') "
            "WHERE run_id = ? AND status IN ('pending', 'running')",
            (str(e), run_id),
        )
        await _publish_run_event(run_id, "error", {"error": str(e)})

    finally:
        if acquired:
            _run_semaphore.release()
        await _close_live_streams(run_id)


@router.get("/runs/recent", response_model=list[RecentRunResponse])
@limiter.limit("120/minute")
async def list_recent_runs(
    request: Request,
    owner_token: str = "",
    limit: int = 20,
    active_only: bool = False,
):
    """Recent runs for one browser (scoped by `owner_token`), with paper title.

    Runs are scoped to the caller's `owner_token` so one browser never sees
    another's tasks. When `active_only=true`, only pending/running runs are
    returned — used by the upload page banner to surface tasks the user
    navigated away from. Declared before `/runs/{run_id}` so the literal path
    wins.

    Abandoned runs are reconciled to 'failed' first, and only runs from the
    last ``_RECENT_RUN_DAYS`` days are returned, so stale tasks never linger
    as perpetual "running" entries.
    """
    limit = max(1, min(limit, 100))
    owner_token = (owner_token or "").strip()[:_MAX_OWNER_TOKEN_LEN]
    await _reconcile_stale_runs()

    conds = ["r.owner_token = ?", "r.started_at >= datetime('now', ?)"]
    params: list[Any] = [owner_token, f"-{_RECENT_RUN_DAYS} days"]
    if active_only:
        conds.append("r.status IN ('pending', 'running')")
    where = "WHERE " + " AND ".join(conds)
    rows = await db.fetch_all(
        f"""
        SELECT r.run_id, r.paper_id, COALESCE(p.title, '') AS paper_title,
               r.mode, r.status, r.started_at, r.finished_at,
               COALESCE(r.current_step, '') AS current_step,
               COALESCE(r.user_question, '') AS user_question
          FROM runs r
          LEFT JOIN papers p ON p.paper_id = r.paper_id
          {where}
         ORDER BY r.started_at DESC
         LIMIT ?
        """,
        (*params, limit),
    )
    return [RecentRunResponse(**r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunResponse)
@limiter.limit("120/minute")
async def get_run(request: Request, run_id: str):
    row = await db.fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunResponse(**row)


@router.get("/runs/{run_id}/output", response_model=RunOutputResponse)
@limiter.limit("20/minute")
async def get_run_output(request: Request, run_id: str):
    row = await db.fetch_one("SELECT * FROM run_outputs WHERE run_id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Run output not found")
    json_data = str(row.get("json_data") or "{}")
    try:
        payload = json.loads(json_data) if json_data else {}
        anchors = payload.get("evidence_anchors") if isinstance(payload, dict) else None
        needs_anchor_rebuild = not isinstance(anchors, list) or any(
            not isinstance(anchor, dict) or int(anchor.get("schema_version") or 0) < ANCHOR_SCHEMA_VERSION
            for anchor in anchors
        )
        if isinstance(payload, dict) and needs_anchor_rebuild:
            run = await db.fetch_one("SELECT paper_id, mode FROM runs WHERE run_id = ?", (run_id,))
            paper_id = str((run or {}).get("paper_id") or payload.get("paper_id") or "")
            if paper_id:
                paper_ir = await load_paper_ir_from_blocks(paper_id)
                payload["evidence_anchors"] = build_evidence_anchors(
                    markdown=str(row.get("markdown") or ""),
                    paper_ir=paper_ir,
                    run_id=run_id,
                    mode=str((run or {}).get("mode") or payload.get("mode") or ""),
                )
                json_data = json.dumps(payload, ensure_ascii=False)
                await db.execute("UPDATE run_outputs SET json_data = ? WHERE run_id = ?", (json_data, run_id))
                row = {**row, "json_data": json_data}
    except Exception as exc:
        logger.warning("[run:%s] failed to build evidence anchors for output: %s", run_id, exc)
    return RunOutputResponse(**row)


@router.post("/runs/{run_id}/dismiss", response_model=RunResponse)
@limiter.limit("30/minute")
async def dismiss_run(request: Request, run_id: str, owner_token: str = ""):
    """Manually clear a pending/running run the user abandoned.

    Only the owning browser (matching `owner_token`) may dismiss a run; legacy
    runs with no owner are dismissible by anyone. Marks the run failed so it
    leaves the active banner, and tears down any live SSE queue. Already-finished
    runs are returned unchanged.
    """
    owner_token = (owner_token or "").strip()[:_MAX_OWNER_TOKEN_LEN]
    row = await db.fetch_one("SELECT status, owner_token, paper_id FROM runs WHERE run_id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    # Don't reveal existence of runs the caller doesn't own.
    if row["owner_token"] and row["owner_token"] != owner_token:
        raise HTTPException(status_code=404, detail="Run not found")

    if row["status"] in ("pending", "running"):
        parse = await db.fetch_one(
            """
            SELECT parse_id
              FROM mineru_parses
             WHERE paper_id = ? AND status IN ('pending', 'running')
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (row["paper_id"],),
        )
        if parse and parse.get("parse_id"):
            parse_id = str(parse["parse_id"])
            if cancel_parse(parse_id):
                await db.execute(
                    "UPDATE mineru_parses SET status = 'failed', error_msg = 'Cancelled by user', updated_at = datetime('now') WHERE parse_id = ?",
                    (parse_id,),
                )
        await db.execute(
            "UPDATE runs SET status = 'failed', error_msg = 'Dismissed by user', "
            "finished_at = datetime('now') WHERE run_id = ? AND status IN ('pending', 'running')",
            (run_id,),
        )
        task = _run_tasks.pop(run_id, None)
        if task is not None and not task.done():
            task.cancel()
        await _publish_run_event(run_id, "cancelled", {"error": "Dismissed by user"})
        await _close_live_streams(run_id)
        logger.info(f"[run:{run_id}] Dismissed by user")

    updated = await db.fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    return RunResponse(**updated)


@router.get("/runs/{run_id}/stream")
@limiter.limit("10/minute")
async def stream_run(request: Request, run_id: str, since_seq: int = 0):
    """SSE endpoint for streaming run progress with DB-backed replay."""
    run = await db.fetch_one("SELECT status, error_msg FROM runs WHERE run_id = ?", (run_id,))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    start_seq = _parse_since_seq(request, since_seq)

    async def event_generator():
        last_seq = start_seq
        queue: asyncio.Queue = asyncio.Queue()
        subscribers = _run_queues.setdefault(run_id, set())
        subscribers.add(queue)
        deadline = time.monotonic() + _STREAM_TIMEOUT_SECONDS
        next_status_check = time.monotonic()
        try:
            for msg in await _fetch_run_event_messages(run_id, last_seq):
                last_seq = max(last_seq, int(msg.get("seq") or 0))
                yield _sse_frame(msg)
                if msg.get("event") in ("done", "error", "cancelled"):
                    yield _sse_frame({"event": "end", "data": {}})
                    return

            while True:
                now = time.monotonic()
                if now >= next_status_check:
                    current = await db.fetch_one("SELECT status, error_msg FROM runs WHERE run_id = ?", (run_id,))
                    next_status_check = now + 30.0
                    if not current:
                        yield _sse_frame({"event": "error", "data": {"error": "Run not found"}})
                        yield _sse_frame({"event": "end", "data": {}})
                        return
                    if current.get("status") not in ("pending", "running"):
                        terminal = _terminal_event_from_status(run_id, current)
                        terminal["seq"] = last_seq
                        yield _sse_frame(terminal)
                        yield _sse_frame({"event": "end", "data": {}})
                        return
                    if run_id not in _run_tasks:
                        await db.execute(
                            "UPDATE runs SET status = 'failed', error_msg = 'Interrupted (task no longer running)', "
                            "finished_at = datetime('now') WHERE run_id = ? AND status IN ('pending', 'running')",
                            (run_id,),
                        )
                        terminal = {
                            "event": "error",
                            "data": {"error": "Interrupted (task no longer running)", "status": "failed"},
                            "seq": last_seq,
                        }
                        yield _sse_frame(terminal)
                        yield _sse_frame({"event": "end", "data": {}})
                        return

                timeout = min(_STREAM_POLL_SECONDS, max(0.0, next_status_check - time.monotonic()), max(0.0, deadline - time.monotonic()))
                if timeout <= 0:
                    yield _sse_frame({"event": "timeout", "data": {}})
                    return
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    for msg in await _fetch_run_event_messages(run_id, last_seq):
                        last_seq = max(last_seq, int(msg.get("seq") or 0))
                        yield _sse_frame(msg)
                        if msg.get("event") in ("done", "error", "cancelled"):
                            yield _sse_frame({"event": "end", "data": {}})
                            return
                    continue
                if msg is None:
                    continue
                msg_seq = int(msg.get("seq") or 0)
                if msg_seq and msg_seq <= last_seq:
                    continue
                if msg_seq:
                    last_seq = msg_seq
                yield _sse_frame(msg)
                if msg.get("event") in ("done", "error", "cancelled"):
                    yield _sse_frame({"event": "end", "data": {}})
                    return
        finally:
            subscribers = _run_queues.get(run_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers and run_id not in _run_tasks:
                    _run_queues.pop(run_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/papers/{paper_id}/runs", response_model=list[RunResponse])
@limiter.limit("20/minute")
async def list_paper_runs(request: Request, paper_id: str):
    rows = await db.fetch_all(
        "SELECT * FROM runs WHERE paper_id = ? ORDER BY started_at DESC",
        (paper_id,),
    )
    return [RunResponse(**r) for r in rows]
