"""Blacklist CRUD + auto-blacklist helpers.

Manual entries (reason="manual") come from the user via the API. Auto entries
(reason="auto_already_applied") are written by the worker when it sees a vacancy
the user already interacted with — either a 4xx "already applied" on apply, or a
non-empty ``relations`` field in search results (see vacancy_producer)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException, status

from app.db.supabase import service_client

logger = logging.getLogger(__name__)

_COLUMNS = "id,employer_id,employer_name,reason,created_at"


async def list_blacklist(user_id: str) -> list[dict]:
    loop = asyncio.get_running_loop()

    def _q():
        return (
            service_client.table("blacklist")
            .select(_COLUMNS)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )

    res = await loop.run_in_executor(None, _q)
    return res.data or []


async def add_blacklist(
    user_id: str,
    employer_id: str,
    employer_name: str | None = None,
    reason: str = "manual",
) -> dict:
    loop = asyncio.get_running_loop()

    def _upsert():
        return (
            service_client.table("blacklist")
            .upsert(
                {
                    "user_id": user_id,
                    "employer_id": employer_id,
                    "employer_name": employer_name,
                    "reason": reason,
                },
                on_conflict="user_id,employer_id",
            )
            .execute()
        )

    res = await loop.run_in_executor(None, _upsert)
    if not res.data:
        raise HTTPException(status_code=500, detail="blacklist upsert failed")
    return res.data[0]


async def remove_blacklist(user_id: str, entry_id: str) -> None:
    loop = asyncio.get_running_loop()

    def _delete():
        return (
            service_client.table("blacklist")
            .delete()
            .eq("user_id", user_id)
            .eq("id", entry_id)
            .execute()
        )

    res = await loop.run_in_executor(None, _delete)
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="blacklist entry not found"
        )


def bulk_auto_blacklist(
    user_id: str,
    entries: dict[str, str | None],
    reason: str = "auto_already_applied",
) -> None:
    """Sync bulk upsert — called from worker executors. ``entries`` maps
    employer_id → employer_name. Best-effort: failures are logged, not raised."""
    if not entries:
        return
    rows = [
        {
            "user_id": user_id,
            "employer_id": eid,
            "employer_name": name,
            "reason": reason,
        }
        for eid, name in entries.items()
    ]
    try:
        service_client.table("blacklist").upsert(
            rows, on_conflict="user_id,employer_id"
        ).execute()
    except Exception:  # pragma: no cover
        logger.exception("bulk auto-blacklist failed for user=%s", user_id)
