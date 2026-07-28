"""User-curated Q&A memory.

Rows land here two ways:
  1. the user EDITED an AI answer while approving a form draft (`save_edited`)
  2. manual entry from the account page (`upsert`)

`prompt_block(user_id)` renders them for injection into any prompt that needs
facts about the candidate (form tests, recruiter chat).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.db.supabase import service_client

logger = logging.getLogger(__name__)

MAX_PROMPT_ITEMS = 40  # ponytail: newest-N cap, add relevance ranking if it overflows


def _run(fn):
    return asyncio.get_running_loop().run_in_executor(None, fn)


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def list_all(user_id: str) -> list[dict]:
    def _q():
        return (
            service_client.table("qa_memory")
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
    res = await _run(_q)
    return res.data or []


async def upsert(
    user_id: str, question: str, answer: str,
    source: str = "manual", vacancy_id: str | None = None,
) -> dict:
    row = {
        "user_id": user_id,
        "question": question.strip(),
        "answer": answer.strip(),
        "source": source,
        "vacancy_id": vacancy_id,
        "updated_at": _now(),
    }

    def _q():
        return (
            service_client.table("qa_memory")
            .upsert(row, on_conflict="user_id,question")
            .execute()
        )
    res = await _run(_q)
    return (res.data or [row])[0]


async def delete(user_id: str, qa_id: str) -> None:
    def _q():
        return (
            service_client.table("qa_memory")
            .delete()
            .eq("user_id", user_id).eq("id", qa_id)
            .execute()
        )
    await _run(_q)


async def save_edited(
    user_id: str,
    original: list[dict] | None,
    final: list[dict] | None,
    vacancy_id: str | None = None,
) -> int:
    """Persist only the answers the user changed. Returns how many were saved.

    Matched by task_id (falls back to question text). Never raises — a failure
    here must not block a successful form submit.
    """
    if not original or not final:
        return 0

    def _key(a: dict) -> str:
        return str(a.get("task_id") or a.get("question") or "")

    before = {_key(a): a for a in original}
    saved = 0
    for a in final:
        prev = before.get(_key(a))
        question = (a.get("question") or "").strip()
        answer = (a.get("answer") or "").strip()
        if not question or not answer:
            continue
        if prev and (prev.get("answer") or "").strip() == answer:
            continue  # untouched by the user
        try:
            await upsert(user_id, question, answer, source="form", vacancy_id=vacancy_id)
            saved += 1
        except Exception:
            logger.warning("qa_memory: upsert failed for %s", question[:60], exc_info=True)
    return saved


async def prompt_block(user_id: str) -> str:
    """Rendered Q&A for prompt injection. '' when the user has none."""
    try:
        rows = await list_all(user_id)
    except Exception:
        logger.warning("qa_memory: load failed for %s", user_id, exc_info=True)
        return ""
    return render_block(rows)


def render_block(rows: list[dict]) -> str:
    items = [
        f"- В: {r['question']}\n  О: {r['answer']}"
        for r in rows[:MAX_PROMPT_ITEMS]
        if r.get("question") and r.get("answer")
    ]
    if not items:
        return ""
    return (
        "Проверенные ответы кандидата (он подтвердил их сам - это "
        "приоритетный источник правды, важнее резюме; если вопрос совпадает "
        "по смыслу, отвечай так же):\n" + "\n".join(items)
    )
