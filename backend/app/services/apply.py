"""Send one job application to hh via POST /negotiations.

Flow:
  1. Resolve resume_uuid → (hh_resume_id, title)
  2. Skip if already applied
  3. Load ApiClient
  4. Fetch vacancy details ONCE — drives 3 decisions: form_required, employer_id, response_letter_required
  5. If has_test → record form_required, return
  6. Generate cover letter ONLY if response_letter_required, else send empty message
  7. POST /negotiations, handle errors
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal

from app.db.supabase import service_client
from app.hh import errors as hh_errors
from app.services import captcha as captcha_service
from app.services import form_drafts
from app.services import notifications
from app.ai.agent import HHAgent
from app.services.hh_credentials import (
    HHCredentialsInvalid,
    load_api_client,
    mark_invalid,
    persist_if_refreshed,
)

logger = logging.getLogger(__name__)

ApplyStatus = Literal[
    "sent",
    "form_sent",
    "form_pending",
    "failed",
    "captcha",
    "skipped",
    "limit_day",
    "token_dead",
    "account_banned",
    "form_required",
    "resume_missing",
    "vacancy_gone",
]

# Statuses that are NOT a spent attempt: the vacancy never reached hh, so it may
# be re-evaluated on a later run (e.g. the user reconnected and the web session
# that solves vacancy tests works again). Both the producer (when deciding what
# to skip) and _already_applied read this — they used to disagree, which made
# form_required rows permanently unreachable.
RETRYABLE_STATUSES = frozenset({"form_required"})

_FORM_REQUIRED_MARKERS = (
    "must process test",
    "process test first",
    "тест",
)

_ALREADY_APPLIED_MARKERS = (
    "already",
    "duplicate",
    "повтор",
    "уже отправ",
)

# hh account banned/blocked — reconnect won't help (vs token_dead which it does).
_BANNED_MARKERS = (
    "blocked",
    "banned",
    "disabled",
    "заблокир",
)

# Resume deleted/hidden on hh side after we synced it locally.
_RESUME_GONE_MARKERS = (
    "resume_not_found",
    "resume_deleted",
    "resume_visibility",
    "unknown_resume",
    "resume not found",
)


def _match_markers(ex: Exception, markers: tuple[str, ...]) -> bool:
    msg = str(ex).lower()
    return any(m in msg for m in markers)


def _resolve_resume(user_id: str, resume_uuid: str) -> dict | None:
    res = (
        service_client.table("resumes")
        .select("id,hh_resume_id,title")
        .eq("user_id", user_id)
        .eq("id", resume_uuid)
        .maybe_single()
        .execute()
    )
    return res.data if res else None


def _already_applied(user_id: str, vacancy_id: str) -> bool:
    res = (
        service_client.table("applications")
        .select("id,status")
        .eq("user_id", user_id)
        .eq("vacancy_id", vacancy_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return False
    # form_required pre-record is not a real attempt — allow re-evaluation.
    # form_pending = AI answers waiting for user approval; do not re-queue.
    return res.data[0].get("status") not in RETRYABLE_STATUSES


def _is_already_applied_error(ex: hh_errors.ClientError) -> bool:
    return _match_markers(ex, _ALREADY_APPLIED_MARKERS)


def is_ban_error(ex: Exception) -> bool:
    """Account-level ban/block (reconnect won't help). Shared with runner probe."""
    return _match_markers(ex, _BANNED_MARKERS)


def _disable_filters_for_resume(user_id: str, resume_uuid: str) -> None:
    """Resume gone on hh → disable its filters so producer stops re-queueing it.
    Non-destructive (vs deleting the resume row, which cascades to filters)."""
    try:
        service_client.table("filters").update({"enabled": False}).eq(
            "user_id", user_id
        ).eq("resume_id", resume_uuid).execute()
    except Exception:  # pragma: no cover
        logger.exception("failed to disable filters for dead resume %s", resume_uuid)


def _record_application(
    *,
    user_id: str,
    resume_uuid: str,
    vacancy_id: str,
    status: ApplyStatus,
    cover_letter: str | None,
    error: str | None,
    employer_id: str | None = None,
    form_answers: list[dict] | None = None,
    employer_name: str | None = None,
    filter_id: str | None = None,
) -> None:
    row = {
        "user_id": user_id,
        "resume_id": resume_uuid,
        "vacancy_id": vacancy_id,
        "employer_id": employer_id,
        "status": status,
        "cover_letter": cover_letter,
        "error": error,
    }
    # Analytics attribution — only set when known, never overwrite with null
    # (this is an upsert; a later row must not blank an earlier attribution).
    if employer_name:
        row["employer_name"] = employer_name
    if filter_id:
        row["filter_id"] = filter_id
    if status in ("sent", "form_sent"):
        row["applied_at"] = datetime.now(timezone.utc).isoformat()
    if form_answers:
        row["form_answers"] = form_answers
    try:
        service_client.table("applications").upsert(
            row, on_conflict="user_id,vacancy_id"
        ).execute()
    except Exception:  # pragma: no cover
        logger.exception("failed to persist application row")


def _auto_blacklist(user_id: str, employer_id: str | None) -> None:
    if not employer_id:
        return
    try:
        service_client.table("blacklist").upsert(
            {
                "user_id": user_id,
                "employer_id": employer_id,
                "reason": "auto_already_applied",
            },
            on_conflict="user_id,employer_id",
        ).execute()
    except Exception:  # pragma: no cover
        logger.exception("failed to auto-blacklist employer %s", employer_id)


def _extract_employer_id(vacancy: dict) -> str | None:
    emp = vacancy.get("employer") if isinstance(vacancy, dict) else None
    return str(emp["id"]) if isinstance(emp, dict) and emp.get("id") else None


async def apply_one(
    user_id: str,
    resume_uuid: str,
    vacancy_id: str,
    agent: HHAgent,
    filter_id: str | None = None,
) -> ApplyStatus:
    loop = asyncio.get_running_loop()
    logger.info(
        "apply: user=%s resume=%s vacancy=%s — start",
        user_id, resume_uuid, vacancy_id,
    )

    resume = await loop.run_in_executor(
        None, _resolve_resume, user_id, resume_uuid
    )
    if resume is None:
        logger.warning("apply: resume %s not found for user %s", resume_uuid, user_id)
        return "resume_missing"
    hh_resume_id = resume["hh_resume_id"]

    if await loop.run_in_executor(None, _already_applied, user_id, vacancy_id):
        logger.info("apply: user=%s already applied to vacancy=%s", user_id, vacancy_id)
        return "skipped"

    try:
        client = await load_api_client(user_id)
    except HHCredentialsInvalid:
        logger.error("apply: user=%s creds invalid", user_id)
        return "token_dead"
    original_access = client.access_token

    try:
        try:
            vacancy = await loop.run_in_executor(
                None, lambda: client.get(f"vacancies/{vacancy_id}")
            )
        except hh_errors.ResourceNotFound:
            logger.info("apply: vacancy=%s gone (404)", vacancy_id)
            await loop.run_in_executor(
                None,
                lambda: _record_application(
                    user_id=user_id,
                    resume_uuid=resume_uuid,
                    vacancy_id=vacancy_id,
                    status="vacancy_gone",
                    cover_letter=None,
                    error="vacancy 404",
                ),
            )
            return "vacancy_gone"
        except hh_errors.Forbidden as ex:
            if is_ban_error(ex):
                logger.error("apply: vacancy fetch Forbidden — account banned: %s", ex)
                await mark_invalid(user_id, f"account banned (vacancy fetch): {ex}")
                return "account_banned"
            logger.warning("apply: vacancy fetch Forbidden — token dead: %s", ex)
            await mark_invalid(user_id, f"Forbidden on vacancy fetch: {ex}")
            return "token_dead"

        employer_id = _extract_employer_id(vacancy)
        employer_name = (vacancy.get("employer") or {}).get("name")

        # Has-test check survives the producer race: vacancy may have flipped
        # has_test=true between search and apply. AI generates answers but the
        # worker NEVER auto-submits — drop a form_draft for user approval.
        if vacancy.get("has_test") is True:
            fill_status, form_answers = await agent.write_form_answers(
                user_id, resume_uuid, vacancy
            )
            logger.info(
                "apply: vacancy=%s has_test=true → fill_status=%s",
                vacancy_id, fill_status,
            )
            if fill_status == "form_pending":
                # Test vacancies can also require a letter — prefill it, else
                # hh rejects the submit at approval time. Editable in the UI.
                draft_letter = ""
                if vacancy.get("response_letter_required"):
                    try:
                        draft_letter = await agent.write_cover_letter(
                            user_id=user_id,
                            vacancy=vacancy,
                            resume=resume,
                            resume_uuid=resume_uuid,
                        )
                    except Exception:
                        logger.exception(
                            "apply: draft cover letter failed vacancy=%s", vacancy_id
                        )
                await form_drafts.insert_draft(
                    user_id=user_id,
                    resume_id=resume_uuid,
                    vacancy=vacancy,
                    answers=form_answers,
                    letter=draft_letter,
                )
                await notifications.notify(
                    user_id, "form_approval",
                    {
                        "vacancy_id": vacancy_id,
                        "vacancy_title": vacancy.get("name"),
                        "employer": (vacancy.get("employer") or {}).get("name"),
                    },
                )
            await loop.run_in_executor(
                None,
                lambda: _record_application(
                    user_id=user_id,
                    resume_uuid=resume_uuid,
                    vacancy_id=vacancy_id,
                    status=fill_status,
                    cover_letter=None,
                    error=None if fill_status == "form_pending" else "vacancy.has_test",
                    employer_id=employer_id,
                    form_answers=form_answers or None,
                    employer_name=employer_name,
                    filter_id=filter_id,
                ),
            )
            return fill_status

        letter_required = bool(vacancy.get("response_letter_required"))
        cover_letter = ""
        if letter_required:
            try:
                cover_letter = await agent.write_cover_letter(
                    user_id=user_id,
                    vacancy=vacancy,
                    resume=resume,
                    resume_uuid=resume_uuid,
                )
                if cover_letter:
                    await notifications.notify(
                        user_id,
                        "cover_letter_written",
                        {
                            "vacancy_id": vacancy_id,
                            "vacancy_title": vacancy.get("name"),
                            "employer": (vacancy.get("employer") or {}).get("name"),
                        },
                    )
            except Exception:
                logger.exception(
                    "apply: cover letter generation failed for vacancy=%s — using empty letter and failing",
                    vacancy_id,
                )
                await loop.run_in_executor(
                    None,
                    lambda: _record_application(
                        user_id=user_id,
                        resume_uuid=resume_uuid,
                        vacancy_id=vacancy_id,
                        status="failed",
                        cover_letter=None,
                        error="cover_letter_generation_failed",
                        employer_id=employer_id,
                    ),
                )
                return "failed"

        params = {
            "resume_id": hh_resume_id,
            "vacancy_id": vacancy_id,
        }
        if letter_required:
            params["message"] = cover_letter

        logger.info(
            "apply: POST /negotiations user=%s vacancy=%s letter_required=%s len=%d",
            user_id, vacancy_id, letter_required, len(cover_letter),
        )
        try:
            await loop.run_in_executor(
                None, lambda: client.post("/negotiations", params)
            )
        except hh_errors.CaptchaRequired as ex:
            captcha_url = ex.captcha_url
            await loop.run_in_executor(
                None,
                lambda: _record_application(
                    user_id=user_id,
                    resume_uuid=resume_uuid,
                    vacancy_id=vacancy_id,
                    status="captcha",
                    cover_letter=cover_letter or None,
                    error=captcha_url,
                    employer_id=employer_id,
                ),
            )
            try:
                await captcha_service.create_request(user_id, captcha_url)
            except Exception:
                logger.exception("apply: failed to create captcha_request")
            return "captcha"
        except hh_errors.LimitExceeded:
            logger.info("user %s: hh LimitExceeded on vacancy %s", user_id, vacancy_id)
            return "limit_day"
        except hh_errors.Forbidden as ex:
            ex_str = str(ex)
            msg = ex_str.lower()
            if any(m in msg for m in _FORM_REQUIRED_MARKERS):
                logger.info(
                    "apply: user=%s vacancy=%s form_required by hh Forbidden marker",
                    user_id, vacancy_id,
                )
                await loop.run_in_executor(
                    None,
                    lambda: _record_application(
                        user_id=user_id,
                        resume_uuid=resume_uuid,
                        vacancy_id=vacancy_id,
                        status="form_required",
                        cover_letter=cover_letter or None,
                        error=f"form_required: {ex_str}",
                        employer_id=employer_id,
                    ),
                )
                return "form_required"
            if is_ban_error(ex):
                logger.error("user %s: hh Forbidden — account banned", user_id)
                await mark_invalid(user_id, f"account banned: {ex}")
                return "account_banned"
            if _match_markers(ex, _RESUME_GONE_MARKERS):
                logger.warning(
                    "user %s: resume %s gone on hh — disabling its filters",
                    user_id, resume_uuid,
                )
                await loop.run_in_executor(
                    None, _disable_filters_for_resume, user_id, resume_uuid
                )
                return "resume_missing"
            logger.warning("user %s: hh Forbidden — marking creds invalid", user_id)
            await mark_invalid(user_id, f"Forbidden: {ex}")
            return "token_dead"
        except hh_errors.ClientError as ex:
            ex_str = str(ex)
            ex_type = type(ex).__name__
            if _is_already_applied_error(ex):
                await loop.run_in_executor(
                    None, _auto_blacklist, user_id, employer_id
                )
                await loop.run_in_executor(
                    None,
                    lambda: _record_application(
                        user_id=user_id,
                        resume_uuid=resume_uuid,
                        vacancy_id=vacancy_id,
                        status="skipped",
                        cover_letter=cover_letter or None,
                        error=f"already_applied: {ex_str}",
                        employer_id=employer_id,
                    ),
                )
                return "skipped"
            if _match_markers(ex, _RESUME_GONE_MARKERS):
                logger.warning(
                    "user %s: resume %s gone on hh (%s) — disabling its filters",
                    user_id, resume_uuid, ex_type,
                )
                await loop.run_in_executor(
                    None, _disable_filters_for_resume, user_id, resume_uuid
                )
                return "resume_missing"
            await loop.run_in_executor(
                None,
                lambda: _record_application(
                    user_id=user_id,
                    resume_uuid=resume_uuid,
                    vacancy_id=vacancy_id,
                    status="failed",
                    cover_letter=cover_letter or None,
                    error=f"{ex_type}: {ex_str}",
                    employer_id=employer_id,
                ),
            )
            return "failed"

        logger.info(
            "apply: SENT user=%s vacancy=%s employer=%s",
            user_id, vacancy_id, employer_id,
        )
        await loop.run_in_executor(
            None,
            lambda: _record_application(
                user_id=user_id,
                resume_uuid=resume_uuid,
                vacancy_id=vacancy_id,
                status="sent",
                cover_letter=cover_letter or None,
                error=None,
                employer_id=employer_id,
                employer_name=employer_name,
                filter_id=filter_id,
            ),
        )
        return "sent"
    finally:
        await persist_if_refreshed(user_id, client, original_access)
