from __future__ import annotations

import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services.research_construction import should_run_threshold, start_construction_job

logger = logging.getLogger("scholar.construction.scheduler")

_task: asyncio.Task[None] | None = None


def _timezone(name: str) -> dt.tzinfo:
    normalized = (name or "Asia/Shanghai").strip()
    if normalized in {"Asia/Shanghai", "Asia/Chongqing", "Asia/Harbin", "PRC"}:
        return dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        logger.warning("Invalid construction scheduler timezone=%s, falling back to Asia/Shanghai", name)
        return dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")


def _weekdays(raw: str) -> set[int]:
    values: set[int] = set()
    for part in str(raw or "").replace("|", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            continue
        if 0 <= value <= 6:
            values.add(value)
        elif 1 <= value <= 7:
            values.add(value - 1)
    return values


def next_construction_at(
    now: dt.datetime | None = None,
    *,
    hour: int = 6,
    minute: int = 0,
    weekday: str = "1",
    timezone: str = "Asia/Shanghai",
) -> dt.datetime:
    tz = _timezone(timezone)
    current = now.astimezone(tz) if now else dt.datetime.now(tz)
    safe_hour = min(max(int(hour), 0), 23)
    safe_minute = min(max(int(minute), 0), 59)
    weekdays = _weekdays(weekday)
    for offset in range(0, 8):
        candidate_day = current + dt.timedelta(days=offset)
        if weekdays and candidate_day.weekday() not in weekdays:
            continue
        target = candidate_day.replace(hour=safe_hour, minute=safe_minute, second=0, microsecond=0)
        if target > current:
            return target
    target = current.replace(hour=safe_hour, minute=safe_minute, second=0, microsecond=0) + dt.timedelta(days=1)
    return target


async def _scheduler_loop() -> None:
    settings = get_settings()
    logger.info(
        "Research construction scheduler enabled at %02d:%02d weekday=%s %s",
        settings.research_construction_schedule_hour,
        settings.research_construction_schedule_minute,
        settings.research_construction_schedule_weekday or "*",
        settings.research_construction_schedule_timezone,
    )
    while True:
        settings = get_settings()
        target = next_construction_at(
            hour=settings.research_construction_schedule_hour,
            minute=settings.research_construction_schedule_minute,
            weekday=settings.research_construction_schedule_weekday,
            timezone=settings.research_construction_schedule_timezone,
        )
        delay = max(0.0, (target - dt.datetime.now(target.tzinfo)).total_seconds())
        logger.info("Next research construction pass scheduled for %s", target.isoformat())
        await asyncio.sleep(delay)
        try:
            modes = {
                item.strip().lower()
                for item in settings.research_construction_trigger_mode.replace("|", ",").split(",")
                if item.strip()
            }
            threshold_mode = "threshold" in modes
            if threshold_mode and not await should_run_threshold():
                logger.info("Research construction skipped: threshold not met")
                continue
            job = await start_construction_job(force=not threshold_mode, trigger_source="scheduled")
            logger.info("Research construction scheduled job started job_id=%s status=%s", job.get("job_id"), job.get("status"))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Research construction scheduled run failed")


async def start_construction_scheduler() -> None:
    global _task
    settings = get_settings()
    modes = {
        item.strip().lower()
        for item in settings.research_construction_trigger_mode.replace("|", ",").split(",")
        if item.strip()
    }
    if not settings.research_construction_enabled or not ({"scheduled", "threshold"} & modes):
        logger.info("Research construction scheduler disabled")
        return
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_scheduler_loop(), name="research-construction-scheduler")


async def stop_construction_scheduler() -> None:
    global _task
    if not _task:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
