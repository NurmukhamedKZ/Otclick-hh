"""Persisted per-user runtime switches (profiles.*_enabled).

Every switch the product exposes lives here and is flipped from the UI, never
from an env file or a console: `apply` (legacy auto-apply loop), `discovery`
(funnel discovery + scoring), `agent` (recruiter chat agent) and `real_apply`
(the user's half of the send gate — settings.ALLOW_REAL_APPLY is the other).

The standalone worker container polls `active_user_flags` and reconciles loops
per user, so "user wants X running" is decoupled from any process's memory.
"""

from __future__ import annotations

import asyncio

from app.db.supabase import service_client

# UI switch name → profiles column. Adding a switch means adding a column here
# and a migration; nothing else in the worker/API has to learn about it.
FLAG_COLUMNS: dict[str, str] = {
    "apply": "worker_enabled",
    "discovery": "discovery_enabled",
    "agent": "agent_enabled",
    "real_apply": "real_apply_enabled",
}

# Flags that make the worker container do work for a user.
_LOOP_FLAGS = ("apply", "discovery", "agent")


def _column(flag: str) -> str:
    try:
        return FLAG_COLUMNS[flag]
    except KeyError:
        raise ValueError(f"unknown worker flag: {flag}") from None


async def set_flag(user_id: str, flag: str, value: bool) -> None:
    column = _column(flag)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: service_client.table("profiles")
        .update({column: value})
        .eq("id", user_id)
        .execute(),
    )


async def get_flags(user_id: str) -> dict[str, bool]:
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(
        None,
        lambda: service_client.table("profiles")
        .select(",".join(FLAG_COLUMNS.values()))
        .eq("id", user_id)
        .maybe_single()
        .execute(),
    )
    data = (res.data if res else None) or {}
    return {flag: bool(data.get(column)) for flag, column in FLAG_COLUMNS.items()}


async def set_enabled(user_id: str, value: bool) -> None:
    await set_flag(user_id, "apply", value)


async def is_enabled(user_id: str) -> bool:
    return (await get_flags(user_id))["apply"]


async def set_agent_enabled(user_id: str, value: bool) -> None:
    await set_flag(user_id, "agent", value)


async def is_agent_enabled(user_id: str) -> bool:
    return (await get_flags(user_id))["agent"]


def active_user_flags() -> dict[str, dict[str, bool]]:
    """Sync — {user_id: {apply, discovery, agent}} for users with valid creds.

    Only users with at least one loop flag on are returned.
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
        .select("id," + ",".join(FLAG_COLUMNS[f] for f in _LOOP_FLAGS))
        .in_("id", list(active))
        .execute()
    )
    out: dict[str, dict[str, bool]] = {}
    for r in prof.data or []:
        uid = r.get("id")
        if not uid:
            continue
        flags = {f: bool(r.get(FLAG_COLUMNS[f])) for f in _LOOP_FLAGS}
        if any(flags.values()):
            out[uid] = flags
    return out
