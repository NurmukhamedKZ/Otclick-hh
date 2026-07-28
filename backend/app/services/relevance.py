"""Batch semantic relevance filter for found vacancies.

filter_relevant: pure classifier (llm + resume summary + items) → per-id verdict.
Conservative (only clear mismatches dropped) and fail-open (any failure → keep all).
Cache helpers persist verdicts in relevance_cache (service_role).
"""

from __future__ import annotations

import json
import logging
import re

from app.ai.prompts import build_relevance_prompt
from app.db.supabase import service_client

logger = logging.getLogger(__name__)

# verdict = (relevant: bool, reason: str)
Verdict = tuple[bool, str]

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


def _llm_text(llm, prompt: str) -> str:
    content = llm.invoke(prompt).content
    if isinstance(content, list):  # some models return content parts
        content = " ".join(str(c) for c in content)
    return (content or "").strip()


def filter_relevant(llm, resume_summary: str, items: list[dict]) -> dict[str, Verdict]:
    """Return {vacancy_id: (relevant, reason)} for each item.

    items carry {id, name, snippet_requirement, snippet_responsibility}.
    Conservative: an id is irrelevant only if the LLM explicitly lists it.
    Fail-open: no llm / parse error / exception → every item relevant.
    """
    if not items:
        return {}
    ids = [str(it["id"]) for it in items if it.get("id")]
    if not llm:
        return {vid: (True, "fail_open") for vid in ids}

    lines = []
    for it in items:
        vid = str(it.get("id") or "")
        if not vid:
            continue
        ctx = " ".join(filter(None, [
            it.get("name") or "",
            it.get("snippet_requirement") or "",
            it.get("snippet_responsibility") or "",
        ]))
        lines.append(f"- id={vid}: {ctx}")
    prompt = build_relevance_prompt(resume_summary, "\n".join(lines))

    try:
        raw = _llm_text(llm, prompt)
        match = _JSON_OBJ.search(raw)
        parsed = json.loads(match.group(0) if match else raw)
        irrelevant = {
            str(e["id"]): str(e.get("reason") or "")
            for e in parsed.get("irrelevant", [])
            if isinstance(e, dict) and e.get("id") is not None
        }
    except Exception:
        logger.warning("relevance: LLM parse failed — fail-open (keep all)", exc_info=True)
        return {vid: (True, "fail_open") for vid in ids}

    return {
        vid: ((False, irrelevant[vid]) if vid in irrelevant else (True, ""))
        for vid in ids
    }


def get_cached_verdicts(resume_id: str, vacancy_ids: list[str]) -> dict[str, Verdict]:
    """Read cached relevance verdicts for these vacancies. Empty on any failure."""
    if not vacancy_ids:
        return {}
    try:
        res = (
            service_client.table("relevance_cache")
            .select("vacancy_id,relevant,reason")
            .eq("resume_id", resume_id)
            .in_("vacancy_id", vacancy_ids)
            .execute()
        )
    except Exception:
        logger.warning("relevance: cache read failed — treating as miss", exc_info=True)
        return {}
    return {
        r["vacancy_id"]: (bool(r["relevant"]), r.get("reason") or "")
        for r in (res.data or [])
    }


def store_verdicts(
    user_id: str,
    resume_id: str,
    verdicts: dict[str, Verdict],
    items: list[dict] | None = None,
) -> None:
    """Persist verdicts to relevance_cache (idempotent upsert). Never raises.

    items (the judged candidates) supply vacancy/employer names for the UI log.
    """
    if not verdicts:
        return
    meta = {str(it["id"]): it for it in (items or []) if it.get("id")}
    rows = [
        {
            "user_id": user_id,
            "resume_id": resume_id,
            "vacancy_id": vid,
            "relevant": relevant,
            "reason": reason or None,
            "vacancy_name": meta.get(vid, {}).get("name") or None,
            "employer_name": meta.get(vid, {}).get("employer_name") or None,
        }
        for vid, (relevant, reason) in verdicts.items()
    ]
    try:
        service_client.table("relevance_cache").upsert(
            rows, on_conflict="resume_id,vacancy_id"
        ).execute()
    except Exception:
        logger.warning("relevance: cache write failed", exc_info=True)


def list_verdicts(user_id: str, relevant: bool | None, limit: int) -> list[dict]:
    """Recent AI verdicts for the UI log. Empty list on any failure."""
    try:
        q = (
            service_client.table("relevance_cache")
            .select("vacancy_id,vacancy_name,employer_name,relevant,reason,created_at")
            .eq("user_id", user_id)
        )
        if relevant is not None:
            q = q.eq("relevant", relevant)
        res = q.order("created_at", desc=True).limit(limit).execute()
    except Exception:
        logger.warning("relevance: log read failed", exc_info=True)
        return []
    return res.data or []
