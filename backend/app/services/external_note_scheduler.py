from __future__ import annotations

import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.db import database as db
from app.services.external_paper_notes import sync_paper_notes

logger = logging.getLogger("scholar.paper_notes.scheduler")

_task: asyncio.Task[None] | None = None


def _timezone(name: str) -> dt.tzinfo:
    normalized = (name or "Asia/Shanghai").strip()
    if normalized in {"Asia/Shanghai", "Asia/Chongqing", "Asia/Harbin", "PRC"}:
        return dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        logger.warning("Invalid Paper-Notes scheduler timezone=%s, falling back to Asia/Shanghai", name)
        return dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")


def next_sync_at(
    now: dt.datetime | None = None,
    *,
    hour: int = 7,
    minute: int = 0,
    timezone: str = "Asia/Shanghai",
) -> dt.datetime:
    tz = _timezone(timezone)
    current = now.astimezone(tz) if now else dt.datetime.now(tz)
    safe_hour = min(max(int(hour), 0), 23)
    safe_minute = min(max(int(minute), 0), 59)
    target = current.replace(hour=safe_hour, minute=safe_minute, second=0, microsecond=0)
    if target <= current:
        target += dt.timedelta(days=1)
    return target


async def refresh_missed_paper_notes(now: dt.datetime | None = None) -> dict | None:
    settings = get_settings()
    if not settings.paper_notes_enabled or not settings.paper_notes_auto_sync_enabled:
        return None
    tz = _timezone(settings.paper_notes_sync_timezone)
    current = now.astimezone(tz) if now else dt.datetime.now(tz)
    target = current.replace(
        hour=min(max(int(settings.paper_notes_sync_hour), 0), 23),
        minute=min(max(int(settings.paper_notes_sync_minute), 0), 59),
        second=0,
        microsecond=0,
    )
    if current < target:
        return None
    today = current.date().isoformat()
    row = await db.fetch_one(
        """
        SELECT sync_id FROM external_note_sync_runs
         WHERE source_id = 'paper_notes'
           AND substr(created_at, 1, 10) = ?
           AND status IN ('done', 'partial', 'running')
         LIMIT 1
        """,
        (today,),
    )
    if row:
        return None
    logger.info("Catching up missed Paper-Notes sync for %s", today)
    return await sync_paper_notes(force=False)


async def _scheduler_loop() -> None:
    settings = get_settings()
    logger.info(
        "Paper-Notes scheduler enabled at %02d:%02d %s",
        settings.paper_notes_sync_hour,
        settings.paper_notes_sync_minute,
        settings.paper_notes_sync_timezone,
    )
    while True:
        settings = get_settings()
        try:
            await refresh_missed_paper_notes()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Paper-Notes catch-up sync failed")
        target = next_sync_at(
            hour=settings.paper_notes_sync_hour,
            minute=settings.paper_notes_sync_minute,
            timezone=settings.paper_notes_sync_timezone,
        )
        delay = max(0.0, (target - dt.datetime.now(target.tzinfo)).total_seconds())
        logger.info("Next Paper-Notes sync scheduled for %s", target.isoformat())
        await asyncio.sleep(delay)
        try:
            await sync_paper_notes(force=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Paper-Notes scheduled sync failed")


async def start_external_note_scheduler() -> None:
    global _task
    settings = get_settings()
    if not settings.paper_notes_enabled or not settings.paper_notes_auto_sync_enabled:
        logger.info("Paper-Notes scheduler disabled")
        return
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_scheduler_loop(), name="paper-notes-scheduler")


async def stop_external_note_scheduler() -> None:
    global _task
    if not _task:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
