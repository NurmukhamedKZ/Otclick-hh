"""Candidate context for the browser extension's LLM calls.

Reuses what the hh worker already has: `form_filler.load_resume` fetches the
full hh resume, `_resume_summary` renders it, `qa_memory` adds the user's
curated answers. Nothing is stored — the resume is fetched per request and the
API client caches the hh session upstream.
"""

from __future__ import annotations

import logging

from app.services import qa_memory
from app.services.form_filler import _resume_summary, load_resume

logger = logging.getLogger(__name__)


def _contact(resume: dict, type_id: str) -> str:
    for c in resume.get("contact") or []:
        if (c.get("type") or {}).get("id") != type_id:
            continue
        value = c.get("value")
        if isinstance(value, dict):
            return str(value.get("formatted") or "").strip()
        return str(value or "").strip()
    return ""


def _named(value) -> str:
    """hh returns dicts ({'name': ...}) and lists of dicts for area/citizenship."""
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    if isinstance(value, list):
        return ", ".join(x for x in (_named(v) for v in value) if x)
    return str(value or "").strip()


def facts(resume: dict) -> dict[str, str]:
    """Verbatim facts the extension may fill without asking the LLM."""
    first = str(resume.get("first_name") or "").strip()
    last = str(resume.get("last_name") or "").strip()
    out = {
        "full_name": " ".join(x for x in (first, last) if x),
        "first_name": first,
        "last_name": last,
        "email": _contact(resume, "email"),
        "phone": _contact(resume, "cell") or _contact(resume, "home"),
        "city": _named(resume.get("area")),
        "citizenship": _named(resume.get("citizenship")),
        "title": str(resume.get("title") or "").strip(),
    }
    return {k: v for k, v in out.items() if v}


def known_values(f: dict[str, str]) -> set[str]:
    return {v.strip().lower() for v in f.values() if v.strip()}


async def build(user_id: str) -> tuple[str, dict[str, str]]:
    """(context text for the prompt, verbatim facts). ('', {}) on any failure."""
    try:
        resume = await load_resume(user_id)
    except Exception:
        logger.warning("candidate_context: resume load failed for %s", user_id, exc_info=True)
        return "", {}
    parts = [_resume_summary(resume)]
    qa = await qa_memory.prompt_block(user_id)
    if qa:
        parts.append("Ранее подтверждённые ответы кандидата:\n" + qa)
    return "\n\n".join(p for p in parts if p), facts(resume)
