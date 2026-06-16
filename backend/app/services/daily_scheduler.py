from __future__ import annotations

import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings

logger = logging.getLogger("scholar.daily.scheduler")

_task: asyncio.Task[None] | None = None


def _timezone(name: str) -> dt.tzinfo:
    normalized = (name or "Asia/Shanghai").strip()
    if normalized in {"Asia/Shanghai", "Asia/Chongqing", "Asia/Harbin", "PRC"}:
        return dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        logger.warning("Invalid daily scheduler timezone=%s, falling back to Asia/Shanghai", name)
        return dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")


def next_refresh_at(
    now: dt.datetime | None = None,
    *,
    hour: int = 6,
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


def missed_refresh_date(
    now: dt.datetime | None = None,
    *,
    hour: int = 6,
    minute: int = 0,
    timezone: str = "Asia/Shanghai",
) -> str:
    tz = _timezone(timezone)
    current = now.astimezone(tz) if now else dt.datetime.now(tz)
    safe_hour = min(max(int(hour), 0), 23)
    safe_minute = min(max(int(minute), 0), 59)
    target = current.replace(hour=safe_hour, minute=safe_minute, second=0, microsecond=0)
    if current < target:
        return ""
    return current.date().isoformat()


async def _refresh_daily_recommendations(**kwargs) -> dict:
    from app.services.daily_recommendations import refresh_daily_recommendations

    return await refresh_daily_recommendations(**kwargs)


async def refresh_missed_daily_recommendations(
    now: dt.datetime | None = None,
    *,
    refresh_func=None,
) -> dict | None:
    settings = get_settings()
    fetched_date = missed_refresh_date(
        now,
        hour=settings.daily_recommendation_auto_refresh_hour,
        minute=settings.daily_recommendation_auto_refresh_minute,
        timezone=settings.daily_recommendation_auto_refresh_timezone,
    )
    if not fetched_date:
        return None
    from app.db import database as db

    row = await db.fetch_one(
        "SELECT COUNT(*) AS total FROM daily_recommendation_items WHERE fetched_date = ?",
        (fetched_date,),
    )
    if int((row or {}).get("total") or 0) > 0:
        return None
    logger.info("Catching up missed daily recommendation refresh for %s", fetched_date)
    func = refresh_func or _refresh_daily_recommendations
    return await func(fetched_date=fetched_date, force=True)


async def _scheduler_loop() -> None:
    settings = get_settings()
    logger.info(
        "Daily recommendation scheduler enabled at %02d:%02d %s",
        settings.daily_recommendation_auto_refresh_hour,
        settings.daily_recommendation_auto_refresh_minute,
        settings.daily_recommendation_auto_refresh_timezone,
    )
    while True:
        settings = get_settings()
        try:
            result = await refresh_missed_daily_recommendations()
            if result:
                logger.info(
                    "Daily recommendation catch-up finished date=%s fetched=%s kept=%s skipped=%s message=%s",
                    result.get("date"),
                    result.get("fetched"),
                    result.get("kept"),
                    result.get("skipped"),
                    result.get("message"),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily recommendation catch-up refresh failed")
        target = next_refresh_at(
            hour=settings.daily_recommendation_auto_refresh_hour,
            minute=settings.daily_recommendation_auto_refresh_minute,
            timezone=settings.daily_recommendation_auto_refresh_timezone,
        )
        delay = max(0.0, (target - dt.datetime.now(target.tzinfo)).total_seconds())
        logger.info("Next daily recommendation refresh scheduled for %s", target.isoformat())
        await asyncio.sleep(delay)
        try:
            result = await _refresh_daily_recommendations(fetched_date=target.date().isoformat(), force=True)
            logger.info(
                "Daily recommendation auto refresh finished date=%s fetched=%s kept=%s skipped=%s message=%s",
                result.get("date"),
                result.get("fetched"),
                result.get("kept"),
                result.get("skipped"),
                result.get("message"),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily recommendation auto refresh failed")


async def start_daily_scheduler() -> None:
    global _task
    settings = get_settings()
    if not settings.daily_recommendation_enabled or not settings.daily_recommendation_auto_refresh_enabled:
        logger.info("Daily recommendation scheduler disabled")
        return
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_scheduler_loop(), name="daily-recommendation-scheduler")


async def stop_daily_scheduler() -> None:
    global _task
    if not _task:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
