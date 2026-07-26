"""Sync user's hh resumes → Supabase `resumes` table."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.db.supabase import service_client
from app.services.hh_credentials import load_api_client, persist_if_refreshed
from app.services.notifications import notify

logger = logging.getLogger(__name__)


def _extract_status(item: dict) -> str | None:
    s = item.get("status")
    if isinstance(s, dict):
        return s.get("id") or s.get("name")
    if isinstance(s, str):
        return s
    return None


def _extract_roles(item: dict) -> list[int] | None:
    """Int professional_role ids from an hh resume item ({id, name} dicts)."""
    out: list[int] = []
    for r in item.get("professional_roles") or []:
        rid = r.get("id") if isinstance(r, dict) else r
        try:
            out.append(int(rid))
        except (TypeError, ValueError):
            continue
    return out or None


def _upsert_resumes(user_id: str, items: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "user_id": user_id,
            "hh_resume_id": str(item["id"]),
            "title": item.get("title"),
            "professional_roles": _extract_roles(item),
            "status": _extract_status(item),
            "synced_at": now,
        }
        for item in items
        if item.get("id")
    ]
    seen_ids = [r["hh_resume_id"] for r in rows]

    # Delete resumes that disappeared from hh (user deleted them remotely).
    # Use NOT IN; empty list ⇒ wipe all rows for this user.
    delete_q = service_client.table("resumes").delete().eq("user_id", user_id)
    if seen_ids:
        delete_q = delete_q.not_.in_("hh_resume_id", seen_ids)
    delete_q.execute()

    if not rows:
        return []
    res = (
        service_client.table("resumes")
        .upsert(rows, on_conflict="user_id,hh_resume_id")
        .execute()
    )
    return res.data or []


def _disable_orphaned_filters(user_id: str) -> list[str]:
    """Filters whose resume was deleted on hh keep enabled=true with a NULL
    resume_id (migration 021's ON DELETE SET NULL), and the producer silently
    drops those — the worker looks "running" while doing nothing. Turn them off
    so the state is visible. Returns the ids that were disabled."""
    res = (
        service_client.table("filters")
        .update({"enabled": False})
        .eq("user_id", user_id)
        .eq("enabled", True)
        .is_("resume_id", "null")
        .execute()
    )
    return [r["id"] for r in (res.data or []) if r.get("id")]


async def sync_resumes(user_id: str) -> list[dict]:
    """Pull /resumes/mine → upsert rows. Returns stored rows."""
    client = await load_api_client(user_id)
    original_access = client.access_token
    loop = asyncio.get_running_loop()
    try:
        payload = await loop.run_in_executor(None, client.get, "resumes/mine")
    finally:
        await persist_if_refreshed(user_id, client, original_access)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    rows = await loop.run_in_executor(None, _upsert_resumes, user_id, items)

    try:
        orphaned = await loop.run_in_executor(None, _disable_orphaned_filters, user_id)
    except Exception:
        logger.exception("resume_sync: failed to disable orphaned filters")
        orphaned = []
    if orphaned:
        logger.warning(
            "resume_sync: user=%s disabled %d filter(s) left without a resume",
            user_id, len(orphaned),
        )
        await notify(
            user_id, "resume_missing",
            {"disabled_filters": len(orphaned), "reason": "resume deleted on hh"},
        )
    return rows


async def list_resumes(user_id: str) -> list[dict]:
    loop = asyncio.get_running_loop()
    def _q():
        return (
            service_client.table("resumes")
            .select("id,hh_resume_id,title,status,synced_at")
            .eq("user_id", user_id)
            .order("synced_at", desc=True)
            .execute()
        )
    res = await loop.run_in_executor(None, _q)
    return res.data or []
