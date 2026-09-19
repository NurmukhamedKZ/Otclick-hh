"""Apply counters and compatibility limiter.

Commercial free/paid quotas were removed from the self-hosted build. `check()`
therefore never blocks sending. Daily counters and total-delivered helpers remain
because they are useful for analytics/status and are independent of billing.

The hard `ALLOW_REAL_APPLY` safety gate and explicit send-queue approval are
separate controls and are intentionally unaffected by this module.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.supabase import service_client

logger = logging.getLogger(__name__)

DEFAULT_TZ = "Asia/Almaty"

# Statuses that actually reached hh. form_required / failed / captcha never did.
COUNTED_STATUSES = ("sent", "form_sent")

LimitResult = Literal["allowed"]


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
    """Atomic +1 (migration 025), retained for status/analytics counters."""
    res = service_client.rpc(
        "increment_apply_counter", {"p_user_id": user_id, "p_date": local_date}
    ).execute()
    return int(res.data or 0)


def sent_total(user_id: str) -> int:
    """Count responses that actually reached hh, across all time."""
    res = (
        service_client.table("applications")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .in_("status", list(COUNTED_STATUSES))
        .execute()
    )
    return (getattr(res, "count", None) if res else 0) or 0


def _check_sync(user_id: str) -> LimitResult:
    """Compatibility hook: commercial quotas no longer exist."""
    return "allowed"


def _increment_sync(user_id: str) -> int:
    tz = _tz_for_user(user_id)
    return _increment_day(user_id, _today_local(tz))


async def check(user_id: str) -> LimitResult:
    return "allowed"


async def increment(user_id: str) -> int:
    """Bump today's counter; returns new value."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _increment_sync, user_id)
