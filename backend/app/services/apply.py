"""Send one job application to hh over the logged-in web session.

No OAuth token anywhere on this path — hh refuses the OAuth grant outside the
client's region (`geo_forbidden`), so both the vacancy fetch and the response
go through the web session captured at login.

Flow:
  1. Resolve resume_uuid → (hh_resume_id, title)
  2. Skip if already applied (locally, then per hh's own per-applicant block)
  3. Fetch the vacancy page ONCE — drives 3 decisions: has_test, employer_id,
     response_letter_required
  4. If has_test → AI drafts answers, user approves; never auto-submitted
  5. Generate cover letter ONLY if response_letter_required
  6. POST vacancy_response/popup, map every rejection onto an ApplyStatus
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Literal

from app.ai.agent import HHAgent
from app.db.supabase import service_client
from app.hh import web
from app.services import captcha as captcha_service
from app.services import form_drafts, form_filler, notifications
from app.services.form_filler import WebSessionExpired
from app.services.hh_credentials import mark_invalid

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
        row["applied_at"] = datetime.now(UTC).isoformat()
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

    if await loop.run_in_executor(None, _already_applied, user_id, vacancy_id):
        logger.info("apply: user=%s already applied to vacancy=%s", user_id, vacancy_id)
        return "skipped"

    try:
        vacancy = await web.get_vacancy(user_id, vacancy_id)
    except web.VacancyGone:
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
    except WebSessionExpired as ex:
        logger.warning("apply: web session dead on vacancy fetch: %s", ex)
        await form_filler.report_dead_session(user_id, ex)
        await mark_invalid(user_id, f"web session dead on vacancy fetch: {ex}")
        return "token_dead"

    employer_id = _extract_employer_id(vacancy)
    employer_name = (vacancy.get("employer") or {}).get("name")

    # hh itself says this user already has a negotiation on this vacancy.
    # Authoritative, unlike matching hh's rejection wording after the POST.
    if vacancy.get("already_responded"):
        logger.info(
            "apply: user=%s vacancy=%s already has a negotiation on hh",
            user_id, vacancy_id,
        )
        await loop.run_in_executor(None, _auto_blacklist, user_id, employer_id)
        await loop.run_in_executor(
            None,
            lambda: _record_application(
                user_id=user_id,
                resume_uuid=resume_uuid,
                vacancy_id=vacancy_id,
                status="skipped",
                cover_letter=None,
                error="already_responded (hh)",
                employer_id=employer_id,
            ),
        )
        return "skipped"

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

    logger.info(
        "apply: submit_response user=%s vacancy=%s letter_required=%s len=%d",
        user_id, vacancy_id, letter_required, len(cover_letter),
    )
    status, error = await form_filler.submit_response(
        user_id=user_id,
        resume_id=resume_uuid,
        vacancy_id=vacancy_id,
        letter=cover_letter,
        answers=None,
    )
    if status in ("sent", "form_sent"):
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

    # A dead web session must stop the loop via the terminal path
    # (runner._disable_worker) — otherwise worker_main respawns the runner
    # every 15 s forever. Treat it like a dead token.
    if error and "web_session_expired" in error:
        logger.warning(
            "apply: user=%s web session dead on submit — marking invalid", user_id
        )
        await mark_invalid(user_id, f"web session dead on apply: {error}")
        return "token_dead"

    # hh rejected the body — map it onto the same ApplyStatus literals the
    # old POST /negotiations used.
    err_text = (error or "").lower()
    # Captcha must NOT fall through to "failed": the runner would keep applying
    # into a captcha wall while looking healthy, which is the fastest way to get
    # the account flagged. ponytail: substring probe — the web captcha body was
    # never captured in recon, tighten it once a real one is seen.
    if "captcha" in err_text:
        logger.warning("apply: user=%s vacancy=%s captcha on submit", user_id, vacancy_id)
        await loop.run_in_executor(
            None,
            lambda: _record_application(
                user_id=user_id,
                resume_uuid=resume_uuid,
                vacancy_id=vacancy_id,
                status="captcha",
                cover_letter=cover_letter or None,
                error=error,
                employer_id=employer_id,
            ),
        )
        try:
            await captcha_service.create_request(user_id, None)
        except Exception:
            logger.exception("apply: failed to create captcha_request")
        return "captcha"
    if any(m in err_text for m in _ALREADY_APPLIED_MARKERS):
        await loop.run_in_executor(None, _auto_blacklist, user_id, employer_id)
        await loop.run_in_executor(
            None,
            lambda: _record_application(
                user_id=user_id,
                resume_uuid=resume_uuid,
                vacancy_id=vacancy_id,
                status="skipped",
                cover_letter=cover_letter or None,
                error=f"already_applied: {error}",
                employer_id=employer_id,
            ),
        )
        return "skipped"
    if any(m in err_text for m in _FORM_REQUIRED_MARKERS):
        logger.info(
            "apply: user=%s vacancy=%s form_required by hh rejection marker",
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
                error=f"form_required: {error}",
                employer_id=employer_id,
            ),
        )
        return "form_required"
    if any(m in err_text for m in _BANNED_MARKERS):
        logger.error("user %s: hh submit banned — account banned", user_id)
        await mark_invalid(user_id, f"account banned (submit): {error}")
        return "account_banned"
    if any(m in err_text for m in _RESUME_GONE_MARKERS):
        logger.warning(
            "user %s: resume %s gone on hh — disabling its filters",
            user_id, resume_uuid,
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
            error=f"hh_submit_rejected: {error}",
            employer_id=employer_id,
        ),
    )
    return "failed"

