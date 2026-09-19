"""Persistent sender runtime controls and batch progress.

The control plane is durable and safe to exercise during calibration, but the
sender is intentionally NOT wired into worker_main yet. A future worker must
obtain the DB lease from this module before processing one queue item.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime

from fastapi import HTTPException

from app.db.supabase import service_client
from app.services import vacancy_pipeline

RUNTIME_WIRED = False
_TERMINAL_QUEUE_STATUSES = frozenset({"sent", "failed", "manual_required", "cancelled"})

_CONTROL_COLUMNS = (
    "user_id,desired_state,active_batch_id,safety_interval_seconds,"
    "lease_owner,lease_expires_at,last_cycle_at,last_outcome,updated_at"
)
_BATCH_COLUMNS = "id,status,total_jobs,created_at,started_at,finished_at,updated_at"
_BATCH_QUEUE_COLUMNS = (
    "id,vacancy_pipeline_id,hh_vacancy_id,status,attempts,last_error,"
    "queued_at,started_at,finished_at"
)


def _ensure_control(user_id: str) -> dict:
    service_client.table("application_send_control").upsert(
        {"user_id": user_id}, on_conflict="user_id"
    ).execute()
    res = (
        service_client.table("application_send_control")
        .select(_CONTROL_COLUMNS)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        raise RuntimeError("send runtime control row unavailable")
    return res.data


def _batch(user_id: str, batch_id: str | None) -> dict | None:
    if not batch_id:
        return None
    res = (
        service_client.table("application_send_batches")
        .select(_BATCH_COLUMNS)
        .eq("user_id", user_id)
        .eq("id", batch_id)
        .maybe_single()
        .execute()
    )
    return res.data if res and res.data else None


def _batch_jobs(user_id: str, batch_id: str | None) -> list[dict]:
    if not batch_id:
        return []
    res = (
        service_client.table("application_send_queue")
        .select(_BATCH_QUEUE_COLUMNS)
        .eq("user_id", user_id)
        .eq("batch_id", batch_id)
        .order("queued_at", desc=False)
        .execute()
    )
    return res.data or []


def _unbatched_queued(user_id: str) -> list[dict]:
    res = (
        service_client.table("application_send_queue")
        .select("id")
        .eq("user_id", user_id)
        .eq("status", "queued")
        .is_("batch_id", "null")
        .order("queued_at", desc=False)
        .execute()
    )
    return res.data or []


def _progress(batch: dict | None, jobs: list[dict]) -> dict:
    counts = Counter(str(row.get("status") or "unknown") for row in jobs)
    processed = sum(counts.get(status, 0) for status in _TERMINAL_QUEUE_STATUSES)
    current = next((row for row in jobs if row.get("status") == "sending"), None)
    total = int((batch or {}).get("total_jobs") or len(jobs))
    return {
        "batch_id": (batch or {}).get("id"),
        "batch_status": (batch or {}).get("status"),
        "total": total,
        "processed": processed,
        "queued": counts.get("queued", 0),
        "sending": counts.get("sending", 0),
        "sent": counts.get("sent", 0),
        "failed": counts.get("failed", 0),
        "manual_required": counts.get("manual_required", 0),
        "cancelled": counts.get("cancelled", 0),
        "current": current,
    }


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _lease_is_active(control: dict) -> bool:
    if not control.get("lease_owner"):
        return False
    expires = _parse_dt(control.get("lease_expires_at"))
    return bool(expires and expires > datetime.now(UTC))


def _state(user_id: str) -> dict:
    control = _ensure_control(user_id)
    batch_id = str(control.get("active_batch_id") or "") or None
    batch = _batch(user_id, batch_id)
    jobs = _batch_jobs(user_id, batch_id)
    pending = _unbatched_queued(user_id)
    # Lease owner is intentionally not exposed to the browser. Only a currently
    # unexpired lease is reported as active; stale owner metadata is ignored.
    return {
        "desired_state": control.get("desired_state") or "paused",
        "safety_interval_seconds": int(control.get("safety_interval_seconds") or 0),
        "last_cycle_at": control.get("last_cycle_at"),
        "last_outcome": control.get("last_outcome"),
        "lease_active": _lease_is_active(control),
        "runtime_wired": RUNTIME_WIRED,
        "waiting_for_next_batch": len(pending),
        "progress": _progress(batch, jobs),
    }


async def get_state(user_id: str) -> dict:
    return await asyncio.to_thread(_state, user_id)


def _create_batch(user_id: str) -> str:
    queued = _unbatched_queued(user_id)
    if not queued:
        raise HTTPException(status_code=409, detail="send queue has no unbatched queued jobs")

    batch_res = service_client.table("application_send_batches").insert(
        {
            "user_id": user_id,
            "status": "running",
            "total_jobs": 0,
        }
    ).execute()
    if not (batch_res and batch_res.data):
        raise RuntimeError("failed to create send batch")
    batch_id = str(batch_res.data[0]["id"])
    ids = [str(row["id"]) for row in queued]

    assigned = (
        service_client.table("application_send_queue")
        .update({"batch_id": batch_id, "updated_at": vacancy_pipeline._now()})
        .eq("user_id", user_id)
        .eq("status", "queued")
        .is_("batch_id", "null")
        .in_("id", ids)
        .execute()
    )
    assigned_count = len(assigned.data or [])
    if assigned_count == 0:
        service_client.table("application_send_batches").delete().eq("id", batch_id).eq(
            "user_id", user_id
        ).execute()
        raise HTTPException(status_code=409, detail="queued jobs changed concurrently")

    service_client.table("application_send_batches").update(
        {"total_jobs": assigned_count, "updated_at": vacancy_pipeline._now()}
    ).eq("id", batch_id).eq("user_id", user_id).execute()
    return batch_id


def _set_control(user_id: str, *, action: str, safety_interval_seconds: int | None) -> dict:
    control = _ensure_control(user_id)
    if safety_interval_seconds is not None and not 0 <= safety_interval_seconds <= 300:
        raise HTTPException(status_code=400, detail="safety interval must be between 0 and 300 seconds")

    changes: dict = {"updated_at": vacancy_pipeline._now()}
    if safety_interval_seconds is not None:
        changes["safety_interval_seconds"] = safety_interval_seconds

    active_batch_id = str(control.get("active_batch_id") or "") or None
    if action == "resume":
        if not active_batch_id:
            active_batch_id = _create_batch(user_id)
            changes["active_batch_id"] = active_batch_id
        else:
            batch = _batch(user_id, active_batch_id)
            if not batch or batch.get("status") == "completed":
                changes["active_batch_id"] = _create_batch(user_id)
                active_batch_id = str(changes["active_batch_id"])
        changes["desired_state"] = "running"
        service_client.table("application_send_batches").update(
            {"status": "running", "finished_at": None, "updated_at": vacancy_pipeline._now()}
        ).eq("id", active_batch_id).eq("user_id", user_id).execute()
    elif action == "pause":
        changes["desired_state"] = "paused"
        if active_batch_id:
            service_client.table("application_send_batches").update(
                {"status": "paused", "updated_at": vacancy_pipeline._now()}
            ).eq("id", active_batch_id).eq("user_id", user_id).neq("status", "completed").execute()
    elif action == "stop_after_current":
        if not active_batch_id:
            changes["desired_state"] = "paused"
        else:
            jobs = _batch_jobs(user_id, active_batch_id)
            if any(row.get("status") == "sending" for row in jobs):
                changes["desired_state"] = "stop_after_current"
            else:
                changes["desired_state"] = "paused"
                service_client.table("application_send_batches").update(
                    {"status": "paused", "updated_at": vacancy_pipeline._now()}
                ).eq("id", active_batch_id).eq("user_id", user_id).neq("status", "completed").execute()
    elif action == "configure":
        if safety_interval_seconds is None:
            raise HTTPException(status_code=400, detail="safety_interval_seconds is required")
    else:
        raise HTTPException(status_code=400, detail="unknown sender control action")

    res = (
        service_client.table("application_send_control")
        .update(changes)
        .eq("user_id", user_id)
        .execute()
    )
    if not (res and res.data):
        raise HTTPException(status_code=409, detail="sender control changed concurrently")
    return _state(user_id)


async def set_control(
    user_id: str,
    *,
    action: str,
    safety_interval_seconds: int | None = None,
) -> dict:
    return await asyncio.to_thread(
        _set_control,
        user_id,
        action=action,
        safety_interval_seconds=safety_interval_seconds,
    )


def _rpc_bool(name: str, params: dict) -> bool:
    res = service_client.rpc(name, params).execute()
    data = res.data if res else False
    if isinstance(data, list):
        return bool(data and data[0])
    return bool(data)


def acquire_lease(user_id: str, owner: str, ttl_seconds: int = 120) -> str | None:
    acquired = _rpc_bool(
        "acquire_application_send_lease",
        {"p_user_id": user_id, "p_owner": owner, "p_ttl_seconds": ttl_seconds},
    )
    if not acquired:
        return None
    control = _ensure_control(user_id)
    return str(control.get("active_batch_id") or "") or None


def _finalize_batch_if_done(user_id: str, batch_id: str | None) -> None:
    if not batch_id:
        return
    jobs = _batch_jobs(user_id, batch_id)
    if any(row.get("status") in {"queued", "sending"} for row in jobs):
        return
    now = vacancy_pipeline._now()
    service_client.table("application_send_batches").update(
        {"status": "completed", "finished_at": now, "updated_at": now}
    ).eq("id", batch_id).eq("user_id", user_id).execute()
    service_client.table("application_send_control").update(
        {
            "desired_state": "paused",
            "active_batch_id": None,
            "updated_at": now,
        }
    ).eq("user_id", user_id).eq("active_batch_id", batch_id).execute()


def release_lease(user_id: str, owner: str, batch_id: str | None, outcome: str | None) -> bool:
    released = _rpc_bool(
        "release_application_send_lease",
        {"p_user_id": user_id, "p_owner": owner, "p_outcome": outcome},
    )
    if not released:
        return False

    control = _ensure_control(user_id)
    if batch_id and control.get("desired_state") == "paused":
        service_client.table("application_send_batches").update(
            {"status": "paused", "updated_at": vacancy_pipeline._now()}
        ).eq("id", batch_id).eq("user_id", user_id).neq("status", "completed").execute()
    _finalize_batch_if_done(user_id, batch_id)
    return True
