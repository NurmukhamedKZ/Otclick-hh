"""Plan → limits. Not a gate anymore: everyone works, the question is how much.

There is no trial (migration 026). A profile is either paid or free:

- ``active`` / ``cancelled`` inside ``plan_expires_at`` — autonomous mode, daily cap
- everything else (``free``, expired paid, unknown) — manual mode, lifetime cap

``BILLING_ENABLED=False`` (self-host default) short-circuits all of it: unlimited
and autonomous, plan column never read.

``has_access`` survives as "is this a paying customer right now" — billing status
and the genuinely paid features (recruiter agent) still ask it. It no longer
decides whether the apply worker may run at all.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal, TypedDict

from app.config import settings
from app.db.supabase import service_client

_SELECT = "plan,trial_ends,plan_expires_at"

Mode = Literal["manual", "auto"]


class Limits(TypedDict):
    mode: Mode
    daily: int | None
    total: int | None


def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def is_paid(profile: dict) -> bool:
    """True if this profile is inside a paid window right now."""
    plan = (profile.get("plan") or "free").strip()
    if plan not in ("active", "cancelled"):
        return False
    exp = _parse_ts(profile.get("plan_expires_at"))
    return exp is not None and exp > datetime.now(UTC)


def has_access(profile: dict) -> bool:
    """Paid access. False for free users — they are not blocked, just limited."""
    if not settings.BILLING_ENABLED:
        return True
    return is_paid(profile)


def limits_for(profile: dict) -> Limits:
    """What this profile may do right now. The single source of limit truth."""
    if not settings.BILLING_ENABLED:
        return {"mode": "auto", "daily": None, "total": None}
    if is_paid(profile):
        return {"mode": "auto", "daily": settings.PAID_DAILY_APPLIES, "total": None}
    return {"mode": "manual", "daily": None, "total": settings.FREE_TOTAL_APPLIES}


def _fetch_profile(user_id: str) -> dict:
    res = (
        service_client.table("profiles")
        .select(_SELECT)
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return (res.data if res else None) or {}


async def check_access(user_id: str) -> bool:
    loop = asyncio.get_running_loop()
    profile = await loop.run_in_executor(None, _fetch_profile, user_id)
    return has_access(profile)


async def get_limits(user_id: str) -> Limits:
    loop = asyncio.get_running_loop()
    profile = await loop.run_in_executor(None, _fetch_profile, user_id)
    return limits_for(profile)


def filter_paid(user_ids: list[str]) -> list[str]:
    """Sync — keep only user_ids with paid access (worker_main gates the
    recruiter agent on this; the apply loop runs for free users too)."""
    if not user_ids:
        return []
    if not settings.BILLING_ENABLED:
        return list(user_ids)
    res = (
        service_client.table("profiles")
        .select(f"id,{_SELECT}")
        .in_("id", user_ids)
        .execute()
    )
    by_id = {r["id"]: r for r in (res.data or [])}
    return [uid for uid in user_ids if is_paid(by_id.get(uid, {}))]
