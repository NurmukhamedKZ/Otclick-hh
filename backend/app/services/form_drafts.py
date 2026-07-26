"""Form-draft persistence + approval workflow.

AI fills vacancy tests but does NOT submit. Answers land here as a row with
status='pending'. The user approves in the UI; `approve()` re-fetches xsrf
and posts to hh; `discard()` marks it dismissed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.db.supabase import service_client
from app.services import form_filler, qa_memory

logger = logging.getLogger(__name__)


def _run(fn):
    return asyncio.get_running_loop().run_in_executor(None, fn)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def insert_draft(
    *,
    user_id: str,
    resume_id: str,
    vacancy: dict,
    answers: list[dict],
    letter: str = "",
) -> None:
    vacancy_id = str(vacancy.get("id") or "")
    emp = vacancy.get("employer") if isinstance(vacancy, dict) else None
    row = {
        "user_id": user_id,
        "resume_id": resume_id,
        "vacancy_id": vacancy_id,
        "vacancy_title": vacancy.get("name"),
        "employer_name": (emp or {}).get("name") if isinstance(emp, dict) else None,
        "vacancy_url": vacancy.get("alternate_url"),
        "answers": answers,
        "letter": letter,
        "status": "pending",
    }

    def _q():
        return (
            service_client.table("form_drafts")
            .upsert(row, on_conflict="user_id,vacancy_id")
            .execute()
        )
    await _run(_q)


async def list_pending(user_id: str) -> list[dict]:
    def _q():
        return (
            service_client.table("form_drafts")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .execute()
        )
    res = await _run(_q)
    return res.data or []


async def _get(user_id: str, draft_id: str) -> dict | None:
    def _q():
        return (
            service_client.table("form_drafts")
            .select("*")
            .eq("user_id", user_id).eq("id", draft_id)
            .maybe_single()
            .execute()
        )
    res = await _run(_q)
    return res.data if res else None


async def _update(draft_id: str, patch: dict) -> None:
    def _q():
        return (
            service_client.table("form_drafts")
            .update(patch)
            .eq("id", draft_id)
            .execute()
        )
    await _run(_q)


async def approve(
    user_id: str, draft_id: str,
    answers: list[dict] | None = None,
    letter: str | None = None,
) -> tuple[str, str | None]:
    """Submit a pending draft to hh. `answers`/`letter` override stored values
    (user may edit before approving). Returns (status, error)."""
    draft = await _get(user_id, draft_id)
    if not draft:
        raise ValueError(f"form_draft {draft_id} not found")
    if draft["status"] != "pending":
        raise ValueError(f"form_draft {draft_id} already {draft['status']}")

    final_answers = answers if answers is not None else draft["answers"]
    final_letter = letter if letter is not None else (draft.get("letter") or "")

    # Remember only what the user actually edited — those corrections are the
    # source of truth for future forms and recruiter replies.
    if answers is not None:
        await qa_memory.save_edited(
            user_id, draft["answers"], final_answers, vacancy_id=draft["vacancy_id"]
        )

    status, error = await form_filler.submit_prepared_form(
        user_id=user_id,
        resume_id=draft["resume_id"],
        vacancy_id=draft["vacancy_id"],
        answers=final_answers,
        letter=final_letter,
    )

    patch: dict = {
        "answers": final_answers,
        "letter": final_letter,
        "resolved_at": _now(),
    }
    if status == "form_sent":
        patch["status"] = "sent"
        patch["error"] = None
        await _update(draft_id, patch)
        await _mirror_application(
            user_id, draft["resume_id"], draft["vacancy_id"],
            status="form_sent", answers=final_answers,
        )
    else:
        patch["status"] = "failed"
        patch["error"] = error
        await _update(draft_id, patch)

    return status, error


async def discard(user_id: str, draft_id: str) -> None:
    draft = await _get(user_id, draft_id)
    if not draft:
        raise ValueError(f"form_draft {draft_id} not found")
    await _update(draft_id, {"status": "discarded", "resolved_at": _now()})


async def _mirror_application(
    user_id: str, resume_id: str, vacancy_id: str,
    status: str, answers: list[dict],
) -> None:
    """After successful submit, update the applications row to form_sent."""
    def _q():
        return service_client.table("applications").upsert(
            {
                "user_id": user_id,
                "resume_id": resume_id,
                "vacancy_id": vacancy_id,
                "status": status,
                "applied_at": _now(),
                "form_answers": answers,
                "error": None,
            },
            on_conflict="user_id,vacancy_id",
        ).execute()
    try:
        await _run(_q)
    except Exception:
        logger.exception("form_drafts: failed to mirror application row")
