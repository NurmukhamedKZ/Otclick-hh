"""Insert notifications rows. UI picks up via Supabase Realtime (day 14)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from app.db.supabase import jsonb_row, service_client

logger = logging.getLogger(__name__)

NotificationType = Literal[
    "captcha",
    "worker_stop",
    "limit_reached",
    "limit_total",
    "token_dead",
    "account_banned",
    "resume_missing",
    "recruiter_draft",
    "recruiter_todo",
    "recruiter_question",
    "form_approval",
    "cover_letter_written",
    "web_session_expired",
    "antibot_pause",
]

# Types that would otherwise fire on every poll cycle. Process-local: a worker
# restart re-notifies once, which is the behaviour we want anyway.
_once_sent: set[tuple[str, str]] = set()

def _insert_sync(user_id: str, type_: str, payload: dict[str, Any]) -> None:
    try:
        # postgrest 2.30 does not auto-serialize dicts/lists into jsonb columns
        # (raises "can't adapt type 'dict'"); jsonb_row wraps them as JSON.
        service_client.table("notifications").insert(
            jsonb_row({"user_id": user_id, "type": type_, "payload": payload})
        ).execute()
    except Exception:
        logger.exception("failed to insert notification %s for %s", type_, user_id)
    # Auxiliary Telegram push - never affects the worker path on failure.
    try:
        from app.services import telegram_notify
        telegram_notify.push_sync(user_id, type_, payload)
    except Exception:
        logger.warning("telegram push failed for %s", type_, exc_info=True)


async def notify(
    user_id: str, type_: NotificationType, payload: dict[str, Any] | None = None
) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _insert_sync, user_id, type_, payload or {})


async def notify_once(
    user_id: str, type_: NotificationType, payload: dict[str, Any] | None = None
) -> None:
    """Notify at most once per (user, type) per process — for conditions that
    are re-detected on every poll (a dead hh web session, say)."""
    key = (user_id, type_)
    if key in _once_sent:
        return
    _once_sent.add(key)
    await notify(user_id, type_, payload)


def clear_once(user_id: str, type_: NotificationType) -> None:
    """Re-arm a notify_once condition (the user fixed it)."""
    _once_sent.discard((user_id, type_))
