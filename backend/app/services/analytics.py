"""Funnel analytics — one RPC call into analytics_summary (migration 023)."""

from __future__ import annotations

import asyncio
import logging

from app.db.supabase import service_client

logger = logging.getLogger(__name__)

EMPTY: dict = {
    "funnel": {
        "ai_checked": 0, "ai_kept": 0, "sent": 0, "viewed": 0,
        "replied": 0, "invited": 0, "discarded": 0, "waiting": 0,
    },
    "kpi": {
        "view_rate": None, "reply_rate": None, "invite_rate": None,
        "discard_rate": None, "median_reaction_hours": None,
        "stuck_forms": 0, "stuck_captcha": 0, "stuck_drafts": 0,
    },
    "ai_filter": {"checked": 0, "kept": 0, "dropped": 0, "drop_rate": None},
    "by_filter": [], "by_resume": [], "by_letter": [],
    "failures": [], "silent_employers": [], "daily": [],
}


def _fetch(user_id: str, days: int) -> dict:
    res = service_client.rpc(
        "analytics_summary", {"p_user_id": user_id, "p_days": days}
    ).execute()
    return res.data or {}


async def summary(user_id: str, days: int) -> dict:
    loop = asyncio.get_running_loop()
    try:
        data = await loop.run_in_executor(None, _fetch, user_id, days)
    except Exception:
        logger.exception("analytics_summary rpc failed for %s", user_id)
        return {**EMPTY, "days": days}
    return {**EMPTY, **data, "days": days}
