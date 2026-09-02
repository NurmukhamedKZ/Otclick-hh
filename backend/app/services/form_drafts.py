"""Form-draft persistence + approval workflow.

AI fills vacancy tests but does NOT submit. Answers land here as a row with
status='pending'. The user approves in the UI; `approve()` re-fetches xsrf
and posts to hh; `discard()` marks it dismissed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.db.supabase import jsonb_row, service_client
from app.services import form_filler, qa_memory

logger = logging.getLogger(__name__)


def _run(fn):
    return asyncio.get_running_loop().run_in_executor(None, fn)


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def insert_draft(
    *,
    user_id: str,
    resume_id: str,
    vacancy: dict,
    answers: list[dict],
    letter: str = "",
) -> str:
    """Upsert a pending form draft; returns the row id for callback routing."""
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
            .upsert(jsonb_row(row), on_conflict="user_id,vacancy_id")
            .execute()
        )
    res = await _run(_q)
    # upsert returns representation by default; fall back to a select.
    data = (res.data or [{}])[0] if res else {}
    draft_id = data.get("id", "")
    if draft_id:
        return draft_id
    def _sel():
        return (
            service_client.table("form_drafts")
            .select("id")
            .eq("user_id", user_id)
            .eq("vacancy_id", vacancy_id)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
    sel = await _run(_sel)
    return (sel.data or {}).get("id", "")


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
            .update(jsonb_row(patch))
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

    # Nothing enters qa_memory before the submit succeeds: the table is the
    # candidate's CONFIRMED source-of-truth, so a failed send must not leak
    # the edits into future prompts. The success branch below persists
    # everything that was actually sent (user edits included).
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
        # All answers the user just sent are confirmed source-of-truth —
        # port them into qa_memory so the AI sees them next time. Never
        # blocks a successful submit on a qa_memory failure.
        try:
            await qa_memory.save_confirmed_answers(
                user_id, final_answers, source="form", vacancy_id=draft["vacancy_id"],
            )
        except Exception:
            logger.warning(
                "form_drafts: qa_memory port failed for draft %s", draft_id, exc_info=True
            )
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
            jsonb_row({
                "user_id": user_id,
                "resume_id": resume_id,
                "vacancy_id": vacancy_id,
                "status": status,
                "applied_at": _now(),
                "form_answers": answers,
                "error": None,
            }),
            on_conflict="user_id,vacancy_id",
        ).execute()
    try:
        await _run(_q)
    except Exception:
        logger.exception("form_drafts: failed to mirror application row")
