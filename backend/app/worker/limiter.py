"""Per-user apply limits.

Paid: N/day in the user's local TZ. Free: a lifetime total, counted straight off
`applications` — no counter column, one query per loop iteration is cheaper than
a new entity to keep in sync. Which of the two applies comes from
`plan.limits_for`, never from a constant here.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.db.supabase import service_client
from app.services import plan as plan_service

logger = logging.getLogger(__name__)

DAILY_LIMIT = settings.PAID_DAILY_APPLIES
DEFAULT_TZ = "Asia/Almaty"

# Statuses that actually reached hh. form_required / failed / captcha never did
# and must not burn a free user's lifetime quota.
COUNTED_STATUSES = ("sent", "form_sent")

LimitResult = Literal["allowed", "limit_day", "limit_total"]


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


def sent_total(user_id: str) -> int:
    """Applies that actually reached hh, ever. Drives the free lifetime cap."""
    res = (
        service_client.table("applications")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .in_("status", list(COUNTED_STATUSES))
        .execute()
    )
    return (getattr(res, "count", None) if res else 0) or 0


def _check_sync(user_id: str) -> LimitResult:
    limits = plan_service.limits_for(plan_service._fetch_profile(user_id))

    total_cap = limits["total"]
    if total_cap is not None and sent_total(user_id) >= total_cap:
        return "limit_total"

    daily_cap = limits["daily"]
    if daily_cap is not None:
        tz = _tz_for_user(user_id)
        if _read_day_count(user_id, _today_local(tz)) >= daily_cap:
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
