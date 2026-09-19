"""Durable manual discovery/scoring runs shared by API and worker containers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import HTTPException

from app.db.supabase import service_client

_COLUMNS = (
    "id,user_id,status,discovery,scoring,error,created_at,started_at,finished_at,updated_at"
)
_ACTIVE_STATUSES = ("queued", "discovery", "scoring")
_FINAL_STATUSES = ("completed", "completed_with_errors", "failed")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _active_for_user(user_id: str) -> dict | None:
    res = (
        service_client.table("search_runs")
        .select(_COLUMNS)
        .eq("user_id", user_id)
        .in_("status", list(_ACTIVE_STATUSES))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def _enqueue(user_id: str) -> tuple[dict, bool]:
    existing = _active_for_user(user_id)
    if existing:
        return existing, False

    try:
        res = (
            service_client.table("search_runs")
            .insert(
                {
                    "user_id": user_id,
                    "status": "queued",
                    "created_at": _now(),
                    "updated_at": _now(),
                }
            )
            .execute()
        )
    except Exception:
        # The partial unique index is the final arbiter if two API processes race.
        existing = _active_for_user(user_id)
        if existing:
            return existing, False
        raise

    if not (res and res.data):
        raise RuntimeError("search run insert returned no row")
    return res.data[0], True


async def enqueue(user_id: str) -> tuple[dict, bool]:
    return await asyncio.to_thread(_enqueue, user_id)


def _get_owned(user_id: str, run_id: str) -> dict:
    res = (
        service_client.table("search_runs")
        .select(_COLUMNS)
        .eq("user_id", user_id)
        .eq("id", run_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        raise HTTPException(status_code=404, detail="search run not found")
    return res.data


async def get_owned(user_id: str, run_id: str) -> dict:
    return await asyncio.to_thread(_get_owned, user_id, run_id)


def _claim_next() -> dict | None:
    res = service_client.rpc("claim_next_search_run", {}).execute()
    rows = res.data or []
    return rows[0] if rows else None


async def claim_next() -> dict | None:
    return await asyncio.to_thread(_claim_next)


def _update(run_id: str, *, from_statuses: tuple[str, ...], changes: dict) -> dict | None:
    res = (
        service_client.table("search_runs")
        .update({**changes, "updated_at": _now()})
        .eq("id", run_id)
        .in_("status", list(from_statuses))
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


async def begin_scoring(run_id: str, discovery: dict) -> dict | None:
    return await asyncio.to_thread(
        _update,
        run_id,
        from_statuses=("discovery",),
        changes={"status": "scoring", "discovery": discovery, "error": None},
    )


async def complete(run_id: str, *, discovery: dict, scoring: dict) -> dict | None:
    has_errors = bool(discovery.get("errors")) or bool(scoring.get("errors")) or bool(
        scoring.get("retryable_errors")
    )
    target = "completed_with_errors" if has_errors else "completed"
    return await asyncio.to_thread(
        _update,
        run_id,
        from_statuses=("scoring",),
        changes={
            "status": target,
            "discovery": discovery,
            "scoring": scoring,
            "error": None,
            "finished_at": _now(),
        },
    )


async def fail(run_id: str, error: Exception | str, *, discovery: dict | None = None) -> dict | None:
    message = (str(error) or "unknown search run error")[:2000]
    changes = {
        "status": "failed",
        "error": message,
        "finished_at": _now(),
    }
    if discovery is not None:
        changes["discovery"] = discovery
    return await asyncio.to_thread(
        _update,
        run_id,
        from_statuses=("discovery", "scoring"),
        changes=changes,
    )


def is_final(status: str) -> bool:
    return status in _FINAL_STATUSES
