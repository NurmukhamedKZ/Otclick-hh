"""Exact-text approval and durable send queue for the new vacancy funnel.

This module only persists approval/queue state. It NEVER calls HH. Real
submission remains a separate sender and is protected by ALLOW_REAL_APPLY.
"""

from __future__ import annotations

import asyncio
import hashlib

from fastapi import HTTPException, status

from app.db.supabase import service_client
from app.services import vacancy_pipeline, vacancy_review_service

_QUEUE_COLUMNS = (
    "id,vacancy_pipeline_id,resume_id,hh_vacancy_id,approved_letter_hash,"
    "batch_id,status,attempts,last_error,queued_at,started_at,finished_at,created_at,updated_at"
)


def letter_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _queue_row(user_id: str, pipeline_id: str) -> dict | None:
    res = (
        service_client.table("application_send_queue")
        .select(_QUEUE_COLUMNS)
        .eq("user_id", user_id)
        .eq("vacancy_pipeline_id", pipeline_id)
        .maybe_single()
        .execute()
    )
    return res.data if res and res.data else None


async def approve_letter(user_id: str, pipeline_id: str) -> dict:
    vacancy = await vacancy_review_service.get_vacancy(user_id, pipeline_id)
    if vacancy["status"] == "approved":
        text = str(vacancy.get("cover_letter_draft") or "").strip()
        digest = letter_hash(text) if text else None
        if text and digest == vacancy.get("approved_letter_hash"):
            return vacancy
        raise HTTPException(status_code=409, detail="approved letter hash does not match draft")
    if vacancy["status"] != "letter_draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"letter can only be approved from letter_draft, not {vacancy['status']}",
        )

    text = str(vacancy.get("cover_letter_draft") or "").strip()
    if not text:
        raise HTTPException(status_code=409, detail="cover letter draft is empty")
    digest = letter_hash(text)
    changed = await asyncio.to_thread(
        vacancy_pipeline.transition,
        user_id=user_id,
        pipeline_id=pipeline_id,
        from_statuses=["letter_draft"],
        to_status="approved",
        changes={
            "approved_letter_hash": digest,
            "approved_at": vacancy_pipeline._now(),
        },
    )
    if not changed:
        raise HTTPException(status_code=409, detail="vacancy changed concurrently")
    return await vacancy_review_service.get_vacancy(user_id, pipeline_id)


async def queue_approved(user_id: str, pipeline_id: str) -> dict:
    """Snapshot the exact approved text and move the funnel into queued_to_send.

    Idempotent for an already queued job. A previously cancelled job can be
    re-queued only while the vacancy still has a valid approval for the same
    exact draft. Requeue always clears any old batch identity so it can only be
    picked up by a future Resume snapshot.
    """
    vacancy = await vacancy_review_service.get_vacancy(user_id, pipeline_id)
    existing = await asyncio.to_thread(_queue_row, user_id, pipeline_id)

    if vacancy["status"] == "queued_to_send" and existing and existing["status"] == "queued":
        return existing
    if vacancy["status"] != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"only an approved vacancy can be queued, not {vacancy['status']}",
        )

    text = str(vacancy.get("cover_letter_draft") or "").strip()
    approved_hash = str(vacancy.get("approved_letter_hash") or "")
    if not text or not approved_hash or letter_hash(text) != approved_hash:
        raise HTTPException(status_code=409, detail="approved letter changed; approve exact text again")
    if not vacancy.get("resume_id"):
        raise HTTPException(status_code=409, detail="approved vacancy has no selected resume")

    payload = {
        "user_id": user_id,
        "vacancy_pipeline_id": pipeline_id,
        "resume_id": vacancy["resume_id"],
        "hh_vacancy_id": vacancy["hh_vacancy_id"],
        "approved_letter_hash": approved_hash,
        "approved_letter_text": text,
        "batch_id": None,
        "status": "queued",
        "attempts": 0,
        "last_error": None,
        "queued_at": vacancy_pipeline._now(),
        "started_at": None,
        "finished_at": None,
        "updated_at": vacancy_pipeline._now(),
    }

    if existing:
        if existing["status"] != "cancelled":
            raise HTTPException(status_code=409, detail=f"send job already exists with status {existing['status']}")
        res = (
            service_client.table("application_send_queue")
            .update(payload)
            .eq("id", existing["id"])
            .eq("user_id", user_id)
            .eq("status", "cancelled")
            .execute()
        )
    else:
        res = service_client.table("application_send_queue").insert(payload).execute()
    if not (res and res.data):
        raise HTTPException(status_code=500, detail="failed to persist send queue job")
    job = res.data[0]

    changed = await asyncio.to_thread(
        vacancy_pipeline.transition,
        user_id=user_id,
        pipeline_id=pipeline_id,
        from_statuses=["approved"],
        to_status="queued_to_send",
    )
    if not changed:
        # No HH call has happened. Return the durable queue row to cancelled so
        # a stale concurrent click cannot leave an executable orphan later.
        service_client.table("application_send_queue").update(
            {"status": "cancelled", "updated_at": vacancy_pipeline._now()}
        ).eq("id", job["id"]).eq("user_id", user_id).execute()
        raise HTTPException(status_code=409, detail="vacancy changed concurrently")
    return job


async def cancel_queued(user_id: str, pipeline_id: str) -> dict:
    vacancy = await vacancy_review_service.get_vacancy(user_id, pipeline_id)
    if vacancy["status"] != "queued_to_send":
        raise HTTPException(status_code=409, detail="vacancy is not queued")
    existing = await asyncio.to_thread(_queue_row, user_id, pipeline_id)
    if not existing or existing["status"] != "queued":
        raise HTTPException(status_code=409, detail="queued job is not cancellable")

    res = (
        service_client.table("application_send_queue")
        .update({
            "status": "cancelled",
            "finished_at": vacancy_pipeline._now(),
            "updated_at": vacancy_pipeline._now(),
        })
        .eq("id", existing["id"])
        .eq("user_id", user_id)
        .eq("status", "queued")
        .execute()
    )
    if not (res and res.data):
        raise HTTPException(status_code=409, detail="queue job changed concurrently")

    changed = await asyncio.to_thread(
        vacancy_pipeline.transition,
        user_id=user_id,
        pipeline_id=pipeline_id,
        from_statuses=["queued_to_send"],
        to_status="approved",
    )
    if not changed:
        raise HTTPException(status_code=409, detail="vacancy changed concurrently")
    return res.data[0]


async def reset_failed(user_id: str, pipeline_id: str) -> dict:
    """Return a failed/manual job to the explicit approval step without retrying.

    This is deliberately a reset, not an automatic retry. The queue row becomes
    cancelled and the vacancy returns from send_error to approved. The user may
    then fix HH connectivity or edit/reapprove the letter before queueing again.
    Archived vacancies are not resettable.
    """
    vacancy = await vacancy_review_service.get_vacancy(user_id, pipeline_id)
    existing = await asyncio.to_thread(_queue_row, user_id, pipeline_id)
    if not existing:
        raise HTTPException(status_code=404, detail="send job not found")

    if existing.get("status") == "cancelled" and vacancy.get("status") == "approved":
        return existing
    if existing.get("status") not in {"failed", "manual_required"}:
        raise HTTPException(status_code=409, detail=f"send job {existing.get('status')} is not resettable")
    if vacancy.get("status") != "send_error":
        raise HTTPException(status_code=409, detail=f"vacancy {vacancy.get('status')} is not resettable")

    draft = str(vacancy.get("cover_letter_draft") or "").strip()
    approved_hash = str(vacancy.get("approved_letter_hash") or "")
    if not draft or not approved_hash or letter_hash(draft) != approved_hash:
        raise HTTPException(status_code=409, detail="approved text changed; regenerate or approve again")
    if str(existing.get("approved_letter_hash") or "") != approved_hash:
        raise HTTPException(status_code=409, detail="queue approval snapshot no longer matches vacancy")

    previous_status = str(existing["status"])
    now = vacancy_pipeline._now()
    res = (
        service_client.table("application_send_queue")
        .update({
            "status": "cancelled",
            "last_error": f"reset_from:{previous_status}",
            "finished_at": now,
            "updated_at": now,
        })
        .eq("id", existing["id"])
        .eq("user_id", user_id)
        .eq("status", previous_status)
        .execute()
    )
    if not (res and res.data):
        raise HTTPException(status_code=409, detail="send job changed concurrently")

    changed = await asyncio.to_thread(
        vacancy_pipeline.transition,
        user_id=user_id,
        pipeline_id=pipeline_id,
        from_statuses=["send_error"],
        to_status="approved",
    )
    if not changed:
        # No HH action can happen from either failed/manual_required state. Best
        # effort rollback keeps the queue and pipeline consistent for inspection.
        service_client.table("application_send_queue").update({
            "status": previous_status,
            "last_error": existing.get("last_error"),
            "updated_at": vacancy_pipeline._now(),
        }).eq("id", existing["id"]).eq("user_id", user_id).eq("status", "cancelled").execute()
        raise HTTPException(status_code=409, detail="vacancy changed concurrently")
    return res.data[0]


async def list_queue(user_id: str, *, statuses: list[str] | None = None, limit: int = 100) -> list[dict]:
    allowed = {"queued", "sending", "sent", "failed", "manual_required", "cancelled"}
    unknown = [s for s in (statuses or []) if s not in allowed]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown queue status(es): {', '.join(unknown)}")

    def _query():
        q = (
            service_client.table("application_send_queue")
            .select(_QUEUE_COLUMNS)
            .eq("user_id", user_id)
        )
        if statuses:
            q = q.in_("status", list(dict.fromkeys(statuses)))
        return q.order("queued_at", desc=False).limit(limit).execute()

    res = await asyncio.to_thread(_query)
    return res.data or []
