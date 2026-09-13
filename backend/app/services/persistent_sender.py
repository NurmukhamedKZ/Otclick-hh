"""Sender engine for application_send_queue.

IMPORTANT: this module is intentionally NOT wired into worker_main yet.
`process_next()` also exits before touching sender-control state, the queue or HH
whenever ALLOW_REAL_APPLY=false. This gives us an end-to-end sender that can be
tested safely before the user explicitly enables real sending.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.config import settings
from app.db.supabase import service_client
from app.hh import web
from app.services import send_runtime_control, vacancy_pipeline
from app.services.form_filler import WebSessionExpired, submit_response
from app.services.send_queue_service import letter_hash

logger = logging.getLogger(__name__)

LEASE_TTL_SECONDS = 300


def _next_job(user_id: str, batch_id: str) -> dict | None:
    """Return the oldest queued item from the currently snapshotted batch only."""
    res = (
        service_client.table("application_send_queue")
        .select(
            "id,user_id,vacancy_pipeline_id,resume_id,hh_vacancy_id,batch_id,"
            "approved_letter_hash,approved_letter_text,status,attempts"
        )
        .eq("user_id", user_id)
        .eq("batch_id", batch_id)
        .eq("status", "queued")
        .order("queued_at", desc=False)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def _pipeline_snapshot(user_id: str, pipeline_id: str) -> dict | None:
    res = (
        service_client.table("vacancy_pipeline")
        .select("id,status,resume_id,hh_vacancy_id,cover_letter_draft,approved_letter_hash")
        .eq("user_id", user_id)
        .eq("id", pipeline_id)
        .maybe_single()
        .execute()
    )
    return res.data if res and res.data else None


def _claim_job(user_id: str, job_id: str, batch_id: str) -> bool:
    res = (
        service_client.table("application_send_queue")
        .update({
            "status": "sending",
            "started_at": vacancy_pipeline._now(),
            "updated_at": vacancy_pipeline._now(),
        })
        .eq("id", job_id)
        .eq("user_id", user_id)
        .eq("batch_id", batch_id)
        .eq("status", "queued")
        .execute()
    )
    return bool(res.data)


def _finish_job(user_id: str, job_id: str, status: str, error: str | None = None) -> None:
    service_client.table("application_send_queue").update({
        "status": status,
        "last_error": error,
        "finished_at": vacancy_pipeline._now(),
        "updated_at": vacancy_pipeline._now(),
    }).eq("id", job_id).eq("user_id", user_id).eq("status", "sending").execute()


def _increment_attempt(user_id: str, job_id: str, attempts: int) -> None:
    service_client.table("application_send_queue").update({
        "attempts": attempts + 1,
        "updated_at": vacancy_pipeline._now(),
    }).eq("id", job_id).eq("user_id", user_id).eq("status", "sending").execute()


async def _move_pipeline(user_id: str, pipeline_id: str, from_status: str, to_status: str) -> bool:
    return await asyncio.to_thread(
        vacancy_pipeline.transition,
        user_id=user_id,
        pipeline_id=pipeline_id,
        from_statuses=[from_status],
        to_status=to_status,
    )


def _snapshot_matches(job: dict, pipeline: dict, batch_id: str) -> bool:
    text = str(job.get("approved_letter_text") or "")
    digest = str(job.get("approved_letter_hash") or "")
    return bool(
        text
        and digest
        and str(job.get("batch_id") or "") == batch_id
        and letter_hash(text) == digest
        and pipeline.get("status") == "queued_to_send"
        and str(pipeline.get("resume_id") or "") == str(job.get("resume_id") or "")
        and str(pipeline.get("hh_vacancy_id") or "") == str(job.get("hh_vacancy_id") or "")
        and str(pipeline.get("approved_letter_hash") or "") == digest
        and str(pipeline.get("cover_letter_draft") or "").strip() == text.strip()
    )


async def _process_leased(user_id: str, batch_id: str) -> dict[str, str | bool | None]:
    job = await asyncio.to_thread(_next_job, user_id, batch_id)
    if not job:
        return {"processed": False, "outcome": "batch_empty", "job_id": None}
    job_id = str(job["id"])
    pipeline_id = str(job["vacancy_pipeline_id"])

    claimed = await asyncio.to_thread(_claim_job, user_id, job_id, batch_id)
    if not claimed:
        return {"processed": False, "outcome": "claim_lost", "job_id": job_id}

    pipeline = await asyncio.to_thread(_pipeline_snapshot, user_id, pipeline_id)
    if not pipeline or not _snapshot_matches(job, pipeline, batch_id):
        await asyncio.to_thread(_finish_job, user_id, job_id, "failed", "approval_snapshot_mismatch")
        if pipeline and pipeline.get("status") == "queued_to_send":
            await _move_pipeline(user_id, pipeline_id, "queued_to_send", "send_error")
        return {"processed": True, "outcome": "approval_snapshot_mismatch", "job_id": job_id}

    try:
        vacancy = await web.get_vacancy(user_id, str(job["hh_vacancy_id"]))
    except web.VacancyGone:
        await asyncio.to_thread(_finish_job, user_id, job_id, "failed", "vacancy_gone")
        await _move_pipeline(user_id, pipeline_id, "queued_to_send", "archived")
        return {"processed": True, "outcome": "vacancy_gone", "job_id": job_id}
    except WebSessionExpired as ex:
        await asyncio.to_thread(_finish_job, user_id, job_id, "failed", f"web_session_expired: {ex}")
        await _move_pipeline(user_id, pipeline_id, "queued_to_send", "send_error")
        return {"processed": True, "outcome": "web_session_expired", "job_id": job_id}

    if vacancy.get("archived"):
        await asyncio.to_thread(_finish_job, user_id, job_id, "failed", "vacancy_archived")
        await _move_pipeline(user_id, pipeline_id, "queued_to_send", "archived")
        return {"processed": True, "outcome": "vacancy_archived", "job_id": job_id}

    # HH is authoritative. If a negotiation already exists, never submit twice.
    if vacancy.get("already_responded"):
        await asyncio.to_thread(_finish_job, user_id, job_id, "sent", "reconciled_already_responded")
        await _move_pipeline(user_id, pipeline_id, "queued_to_send", "sent")
        return {"processed": True, "outcome": "already_responded", "job_id": job_id}

    # Tests/forms remain manual. The persistent sender never generates or
    # auto-submits form answers.
    if vacancy.get("has_test"):
        await asyncio.to_thread(_finish_job, user_id, job_id, "manual_required", "hh_vacancy_has_test")
        await _move_pipeline(user_id, pipeline_id, "queued_to_send", "send_error")
        return {"processed": True, "outcome": "manual_required", "job_id": job_id}

    await asyncio.to_thread(_increment_attempt, user_id, job_id, int(job.get("attempts") or 0))
    send_status, error = await submit_response(
        user_id=user_id,
        resume_id=str(job["resume_id"]),
        vacancy_id=str(job["hh_vacancy_id"]),
        letter=str(job["approved_letter_text"]),
        answers=None,
    )
    if send_status == "sent":
        await asyncio.to_thread(_finish_job, user_id, job_id, "sent", None)
        await _move_pipeline(user_id, pipeline_id, "queued_to_send", "sent")
        return {"processed": True, "outcome": "sent", "job_id": job_id}

    # Any uncertain/rejected submit is reconciled against HH before being
    # classified as failed. There is no automatic retry in this implementation.
    try:
        after = await web.get_vacancy(user_id, str(job["hh_vacancy_id"]))
    except Exception:
        after = {}
    if after.get("already_responded"):
        await asyncio.to_thread(_finish_job, user_id, job_id, "sent", "reconciled_after_uncertain_submit")
        await _move_pipeline(user_id, pipeline_id, "queued_to_send", "sent")
        return {"processed": True, "outcome": "sent_reconciled", "job_id": job_id}

    message = str(error or send_status or "hh_submit_failed")[:2000]
    await asyncio.to_thread(_finish_job, user_id, job_id, "failed", message)
    await _move_pipeline(user_id, pipeline_id, "queued_to_send", "send_error")
    logger.warning("persistent sender failed user=%s job=%s: %s", user_id, job_id, message)
    return {"processed": True, "outcome": "failed", "job_id": job_id}


async def process_next(
    user_id: str,
    *,
    lease_owner: str | None = None,
) -> dict[str, str | bool | None]:
    """Process at most one approved send job under a per-HH-account DB lease.

    Not scheduled anywhere yet. The hard safety flag remains the outermost gate:
    when false, this function returns before sender-control state, queue state,
    cookies or any HH endpoint are touched.
    """
    if not settings.ALLOW_REAL_APPLY:
        return {"processed": False, "outcome": "real_apply_disabled", "job_id": None}

    owner = lease_owner or f"sender-{uuid.uuid4()}"
    batch_id = await asyncio.to_thread(
        send_runtime_control.acquire_lease,
        user_id,
        owner,
        LEASE_TTL_SECONDS,
    )
    if not batch_id:
        return {"processed": False, "outcome": "paused_locked_or_throttled", "job_id": None}

    result: dict[str, str | bool | None] = {
        "processed": False,
        "outcome": "sender_internal_error",
        "job_id": None,
    }
    try:
        result = await _process_leased(user_id, batch_id)
        return result
    finally:
        outcome = str(result.get("outcome") or "sender_internal_error")
        try:
            await asyncio.to_thread(
                send_runtime_control.release_lease,
                user_id,
                owner,
                batch_id,
                outcome,
            )
        except Exception:
            logger.exception("failed to release persistent sender lease user=%s owner=%s", user_id, owner)
