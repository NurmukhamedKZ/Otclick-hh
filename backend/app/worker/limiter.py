"""Per-user apply rate limits: 100/day (local TZ)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.supabase import service_client

logger = logging.getLogger(__name__)

DAILY_LIMIT = 100
DEFAULT_TZ = "Asia/Almaty"

LimitResult = Literal["allowed", "limit_day"]


def _tz_for_user(user_id: str) -> ZoneInfo:
    res = (
        service_client.table("profiles")
        .select("timezone")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    raw = (res.data or {}).get("timezone") if res else None
    try:
        return ZoneInfo(raw or DEFAULT_TZ)
    except ZoneInfoNotFoundError:
        logger.warning("unknown tz %r for user %s, falling back to %s", raw, user_id, DEFAULT_TZ)
        return ZoneInfo(DEFAULT_TZ)


def _today_local(tz: ZoneInfo) -> str:
    return datetime.now(tz).date().isoformat()


def _read_day_count(user_id: str, local_date: str) -> int:
    res = (
        service_client.table("apply_counters")
        .select("count")
        .eq("user_id", user_id)
        .eq("date", local_date)
        .maybe_single()
        .execute()
    )
    return ((res.data or {}).get("count") if res else 0) or 0


def _increment_day(user_id: str, local_date: str) -> int:
    """Atomic +1 (migration 025). A read-modify-write here loses increments as
    soon as anything other than the single per-user runner writes, and the daily
    cap stops holding."""
    res = service_client.rpc(
        "increment_apply_counter", {"p_user_id": user_id, "p_date": local_date}
    ).execute()
    return int(res.data or 0)


def _check_sync(user_id: str) -> LimitResult:
    tz = _tz_for_user(user_id)
    local_date = _today_local(tz)
    if _read_day_count(user_id, local_date) >= DAILY_LIMIT:
        return "limit_day"
    return "allowed"


def _increment_sync(user_id: str) -> int:
    tz = _tz_for_user(user_id)
    return _increment_day(user_id, _today_local(tz))


async def check(user_id: str) -> LimitResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _check_sync, user_id)


async def increment(user_id: str) -> int:
    """Bump today's counter; returns new value."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _increment_sync, user_id)
