"""Recruiter-chat agent persistence + message helpers.

Shared by the chat tools (ai/recruiter_tools.py), the poller
(worker/recruiter_poll.py), and the API (api/recruiter.py). All DB writes use
the service_role client and run in an executor — never block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.db.supabase import service_client
from app.services import qa_memory
from app.services.hh_credentials import load_api_client, persist_if_refreshed

logger = logging.getLogger(__name__)


def new_employer_message(items: list[dict], last_handled_id: str | None) -> dict | None:
    """Latest employer-authored text message that the agent has not handled yet.

    Cursor-based: only messages strictly after `last_handled_id` qualify.
    `viewed_by_me` is intentionally NOT used as a trigger — that flag flips
    only when the user opens the chat on hh.ru, so relying on it would make
    the agent reply twice to the same employer message between polls.

    Returns None when every employer text message is already at/behind the
    cursor (nothing new since last reply).
    """
    start = 0
    if last_handled_id is not None:
        for i, m in enumerate(items):
            if str(m.get("id")) == str(last_handled_id):
                start = i + 1
                break
    latest = None
    for m in items[start:]:
        if (m.get("author") or {}).get("participant_type") != "employer":
            continue
        if not (m.get("text") or "").strip():
            continue
        latest = m
    return latest


def to_lc_messages(items: list[dict]) -> list[tuple[str, str]]:
    """Map hh messages to LangChain (role, content) tuples for agent context."""
    out: list[tuple[str, str]] = []
    for m in items:
        text = (m.get("text") or "").strip()
        if not text:
            continue
        role = "user" if m.get("author", {}).get("participant_type") == "employer" else "assistant"
        out.append((role, text))
    return out


# --- persistence -------------------------------------------------------------

def _run(fn):
    return asyncio.get_running_loop().run_in_executor(None, fn)


async def get_cursor(user_id: str, negotiation_id: str) -> str | None:
    def _q():
        return (
            service_client.table("recruiter_chats")
            .select("last_handled_message_id")
            .eq("user_id", user_id)
            .eq("negotiation_id", negotiation_id)
            .maybe_single()
            .execute()
        )
    res = await _run(_q)
    data = res.data if res else None
    return data.get("last_handled_message_id") if data else None


async def upsert_cursor(
    user_id: str, negotiation_id: str, message_id: str,
    vacancy_id: str | None = None, employer_name: str | None = None,
) -> None:
    row = {
        "user_id": user_id,
        "negotiation_id": negotiation_id,
        "last_handled_message_id": message_id,
        "last_polled_at": datetime.now(UTC).isoformat(),
    }
    if vacancy_id is not None:
        row["vacancy_id"] = vacancy_id
    if employer_name is not None:
        row["employer_name"] = employer_name

    def _q():
        return (
            service_client.table("recruiter_chats")
            .upsert(row, on_conflict="user_id,negotiation_id")
            .execute()
        )
    await _run(_q)


async def insert_draft(
    user_id: str, negotiation_id: str, message_id: str, draft_text: str, reason: str,
    question_text: str | None = None,
    vacancy_id: str | None = None, vacancy_title: str | None = None,
    employer_name: str | None = None,
) -> None:
    def _q():
        return service_client.table("recruiter_drafts").insert({
            "user_id": user_id,
            "negotiation_id": negotiation_id,
            "message_id": message_id,
            "draft_text": draft_text,
            "reason": reason,
            "question_text": question_text,
            "vacancy_id": vacancy_id,
            "vacancy_title": vacancy_title,
            "employer_name": employer_name,
            "status": "pending",
        }).execute()
    await _run(_q)


async def insert_question(
    user_id: str, negotiation_id: str, message_id: str, questions: list[str], reason: str,
    question_text: str | None = None,
    chat_id: str | None = None, applicant_id: str | None = None,
    vacancy_id: str | None = None, vacancy_title: str | None = None,
    employer_name: str | None = None,
) -> None:
    def _q():
        return service_client.table("recruiter_questions").insert({
            "user_id": user_id,
            "negotiation_id": negotiation_id,
            "chat_id": chat_id,
            "applicant_id": applicant_id,
            "message_id": message_id,
            "questions": questions,
            "reason": reason,
            "question_text": question_text,
            "vacancy_id": vacancy_id,
            "vacancy_title": vacancy_title,
            "employer_name": employer_name,
            "status": "pending",
        }).execute()
    await _run(_q)


# --- questions (ask-only escalation) ----------------------------------------

async def list_questions(user_id: str) -> list[dict]:
    def _q():
        return (
            service_client.table("recruiter_questions")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .execute()
        )
    res = await _run(_q)
    return res.data or []


async def list_answered_questions(user_id: str) -> list[dict]:
    def _q():
        return (
            service_client.table("recruiter_questions")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "answered")
            .order("created_at", desc=True)
            .execute()
        )
    res = await _run(_q)
    return res.data or []


async def discard_question(user_id: str, question_id: str) -> None:
    def _q():
        return (
            service_client.table("recruiter_questions")
            .update({"status": "discarded", "resolved_at": datetime.now(UTC).isoformat()})
            .eq("user_id", user_id).eq("id", question_id)
            .execute()
        )
    await _run(_q)


async def submit_answers(user_id: str, question_id: str, answers: list[str]) -> None:
    """Record the user's answers to a pending question set. Validates that the
    count matches the number of questions asked (raises ValueError otherwise)."""
    def _q():
        return (
            service_client.table("recruiter_questions")
            .select("questions")
            .eq("user_id", user_id).eq("id", question_id)
            .maybe_single()
            .execute()
        )
    res = await _run(_q)
    row = res.data if res else None
    if not row:
        raise ValueError(f"question {question_id} not found")
    if len(answers) != len(row["questions"] or []):
        raise ValueError("answer count does not match question count")

    def _upd():
        return (
            service_client.table("recruiter_questions")
            .update({"answers": answers, "status": "answered", "answered_at": datetime.now(UTC).isoformat()})
            .eq("user_id", user_id).eq("id", question_id)
            .execute()
        )
    await _run(_upd)


async def mark_question_completed(user_id: str, question_id: str) -> None:
    def _q():
        return (
            service_client.table("recruiter_questions")
            .update({"status": "completed", "resolved_at": datetime.now(UTC).isoformat()})
            .eq("user_id", user_id).eq("id", question_id)
            .execute()
        )
    await _run(_q)


async def insert_todo(
    user_id: str, negotiation_id: str, message_id: str,
    title: str, detail: str | None, link: str | None,
    vacancy_id: str | None = None, vacancy_title: str | None = None,
    employer_name: str | None = None,
) -> None:
    def _q():
        return service_client.table("recruiter_todos").insert({
            "user_id": user_id,
            "negotiation_id": negotiation_id,
            "message_id": message_id,
            "title": title,
            "detail": detail,
            "link": link,
            "vacancy_id": vacancy_id,
            "vacancy_title": vacancy_title,
            "employer_name": employer_name,
            "status": "open",
        }).execute()
    await _run(_q)


# --- query + send ------------------------------------------------------------

async def list_drafts(user_id: str) -> list[dict]:
    def _q():
        return (
            service_client.table("recruiter_drafts")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .execute()
        )
    res = await _run(_q)
    return res.data or []


async def list_todos(user_id: str) -> list[dict]:
    def _q():
        return (
            service_client.table("recruiter_todos")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "open")
            .order("created_at", desc=True)
            .execute()
        )
    res = await _run(_q)
    return res.data or []


async def discard_draft(user_id: str, draft_id: str) -> None:
    def _q():
        return (
            service_client.table("recruiter_drafts")
            .update({"status": "discarded", "resolved_at": datetime.now(UTC).isoformat()})
            .eq("user_id", user_id).eq("id", draft_id)
            .execute()
        )
    await _run(_q)


async def mark_todo(user_id: str, todo_id: str, status: str) -> None:
    def _q():
        return (
            service_client.table("recruiter_todos")
            .update({"status": status, "done_at": datetime.now(UTC).isoformat()})
            .eq("user_id", user_id).eq("id", todo_id)
            .execute()
        )
    await _run(_q)


async def _get_draft(user_id: str, draft_id: str) -> dict | None:
    def _q():
        return (
            service_client.table("recruiter_drafts")
            .select("*")
            .eq("user_id", user_id).eq("id", draft_id)
            .maybe_single()
            .execute()
        )
    res = await _run(_q)
    return res.data if res else None


async def send_draft(user_id: str, draft_id: str, message: str | None = None) -> None:
    """Send a draft reply to hh and mark it sent. `message` overrides draft_text."""
    draft = await _get_draft(user_id, draft_id)
    if not draft:
        raise ValueError(f"draft {draft_id} not found")
    text = message if message is not None else draft["draft_text"]
    nid = draft["negotiation_id"]

    # Remember only edits the user actually made — his correction on a recruiter's
    # verbatim question is the same kind of source-of-truth as an edited form answer.
    question = (draft.get("question_text") or "").strip()
    if question and text.strip() != (draft.get("draft_text") or "").strip():
        try:
            await qa_memory.upsert(
                user_id, question, text.strip(),
                source="recruiter", vacancy_id=draft.get("negotiation_id"),
            )
        except Exception:
            logger.warning("recruiter: qa_memory save failed for draft %s", draft_id, exc_info=True)

    client = await load_api_client(user_id)
    original = client.access_token
    try:
        await _run(lambda: client.post(f"negotiations/{nid}/messages", {"message": text}))
    finally:
        await persist_if_refreshed(user_id, client, original)

    def _q():
        return (
            service_client.table("recruiter_drafts")
            .update({"status": "sent", "resolved_at": datetime.now(UTC).isoformat()})
            .eq("user_id", user_id).eq("id", draft_id)
            .execute()
        )
    await _run(_q)
