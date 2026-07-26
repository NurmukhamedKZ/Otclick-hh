"""Persisted worker on/off intent (profiles.worker_enabled).

Dashboard Start/Stop flips the flag; the standalone worker container polls
`active_user_flags` and starts/stops a runner per user. This decouples
"user wants the worker running" from any single process's in-memory state, so
the worker no longer auto-applies for every connected user at container boot.
"""

from __future__ import annotations

import asyncio

from app.db.supabase import service_client


async def set_enabled(user_id: str, value: bool) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: service_client.table("profiles")
        .update({"worker_enabled": value})
        .eq("id", user_id)
        .execute(),
    )


async def is_enabled(user_id: str) -> bool:
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(
        None,
        lambda: service_client.table("profiles")
        .select("worker_enabled")
        .eq("id", user_id)
        .maybe_single()
        .execute(),
    )
    data = res.data if res else None
    return bool(data and data.get("worker_enabled"))


async def set_agent_enabled(user_id: str, value: bool) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: service_client.table("profiles")
        .update({"agent_enabled": value})
        .eq("id", user_id)
        .execute(),
    )


async def is_agent_enabled(user_id: str) -> bool:
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(
        None,
        lambda: service_client.table("profiles")
        .select("agent_enabled")
        .eq("id", user_id)
        .maybe_single()
        .execute(),
    )
    data = res.data if res else None
    return bool(data and data.get("agent_enabled"))


def active_user_flags() -> dict[str, tuple[bool, bool]]:
    """Sync — {user_id: (apply_enabled, agent_enabled)} for users with valid creds.

    Only includes users with at least one flag on. Plan gating
    (filter_accessible) is applied separately by the caller.
    """
    creds = (
        service_client.table("hh_credentials")
        .select("user_id,invalid_at")
        .is_("invalid_at", None)
        .execute()
    )
    active = {r["user_id"] for r in (creds.data or []) if r.get("user_id")}
    if not active:
        return {}
    prof = (
        service_client.table("profiles")
        .select("id,worker_enabled,agent_enabled")
        .in_("id", list(active))
        .execute()
    )
    out: dict[str, tuple[bool, bool]] = {}
    for r in prof.data or []:
        uid = r.get("id")
        if not uid:
            continue
        apply_on = bool(r.get("worker_enabled"))
        agent_on = bool(r.get("agent_enabled"))
        if apply_on or agent_on:
            out[uid] = (apply_on, agent_on)
    return out
