"""Candidate context for the vacancy funnel, grounded in the user's own data.

Upstream this was a curated single-candidate JSON bundle. Here the product is
multi-user, so the context is derived from what each account already has: the
hh resume (`form_filler.load_resume`, the same payload cover letters use) and
the curated Q&A memory. No new tables, nothing to seed, nothing to keep in sync.

Shape is the contract every consumer relies on (scoring, cover letters,
fingerprints, /api/candidate-context):
    {"version": int, "source_name": str, "profile": dict, "facts": [ ... ]}
A fact always carries a stable `fact_key` so a generated letter can cite it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import HTTPException

from app.db.supabase import service_client
from app.services import qa_memory

logger = logging.getLogger(__name__)


def _latest_resume_row(user_id: str) -> dict | None:
    res = (
        service_client.table("resumes")
        .select("id,hh_resume_id,title,synced_at")
        .eq("user_id", user_id)
        .order("synced_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def _version_from(synced_at: str | None) -> int:
    """Bump the context version whenever the resume was re-synced.

    Fingerprints embed this, so a re-synced resume correctly marks old scores
    and cover letters stale instead of silently keeping them.
    """
    if not synced_at:
        return 1
    try:
        return max(1, int(datetime.fromisoformat(synced_at.replace("Z", "+00:00")).timestamp()))
    except ValueError:
        return 1


def _text(value) -> str:
    from app.services.form_filler import _strip_tags

    return _strip_tags(value if isinstance(value, str) else None)


def _facts_from_resume(resume: dict, source_name: str) -> list[dict]:
    facts: list[dict] = []

    for index, item in enumerate(resume.get("experience") or [], start=1):
        if not isinstance(item, dict):
            continue
        position = str(item.get("position") or "").strip()
        company = str(item.get("company") or "").strip()
        statement = _text(item.get("description"))
        if not (position or statement):
            continue
        start, end = item.get("start") or "", item.get("end") or "наст.вр."
        facts.append(
            {
                "fact_key": f"experience_{index}",
                "category": "experience",
                "title": " @ ".join(p for p in (position, company) if p) or f"Опыт {index}",
                "statement": statement or f"{position} в {company}",
                "metrics": {"start": start, "end": end},
                "tags": [t for t in (company,) if t],
                "source_name": source_name,
            }
        )

    skills = [str(s) for s in (resume.get("skill_set") or []) if s]
    if skills:
        facts.append(
            {
                "fact_key": "skills",
                "category": "skills",
                "title": "Ключевые навыки",
                "statement": ", ".join(skills),
                "metrics": {"count": len(skills)},
                "tags": skills[:12],
                "source_name": source_name,
            }
        )

    about = _text(resume.get("skills"))
    if about:
        facts.append(
            {
                "fact_key": "about",
                "category": "about",
                "title": "О себе",
                "statement": about,
                "metrics": {},
                "tags": [],
                "source_name": source_name,
            }
        )
    return facts


def _facts_from_qa(rows: list[dict]) -> list[dict]:
    facts: list[dict] = []
    for index, row in enumerate(rows, start=1):
        question = str(row.get("question") or "").strip()
        answer = str(row.get("answer") or "").strip()
        if not (question and answer):
            continue
        facts.append(
            {
                "fact_key": f"qa_{index}",
                "category": "qa_memory",
                "title": question[:200],
                "statement": answer,
                "metrics": {},
                "tags": [],
                "source_name": "qa_memory",
            }
        )
    return facts


async def load_candidate_context(user_id: str) -> dict:
    """Build the candidate context from the user's newest resume + Q&A memory."""
    from app.services.form_filler import _resume_summary, load_resume

    row = await asyncio.to_thread(_latest_resume_row, user_id)
    if not row:
        raise HTTPException(
            status_code=409,
            detail="no synced resume: sync a resume from hh before using the funnel",
        )

    try:
        resume = await load_resume(user_id, str(row["id"]))
    except Exception as ex:
        logger.warning("candidate context: resume load failed user=%s", user_id, exc_info=True)
        raise HTTPException(status_code=409, detail=f"resume is unavailable: {ex}") from ex

    source_name = f"hh_resume:{row.get('hh_resume_id') or row['id']}"
    qa_rows = await qa_memory.list_all(user_id)
    facts = _facts_from_resume(resume, source_name) + _facts_from_qa(qa_rows)

    profile = {
        "resume_id": str(row["id"]),
        "title": resume.get("title") or row.get("title"),
        "area": (resume.get("area") or {}).get("name") if isinstance(resume.get("area"), dict) else resume.get("area"),
        "total_experience": (resume.get("total_experience") or {}).get("months")
        if isinstance(resume.get("total_experience"), dict)
        else resume.get("total_experience"),
        "salary": resume.get("salary"),
        # The full grounding text: every claim an LLM may make must be in here.
        "resume_summary": _resume_summary(resume),
    }

    return {
        "version": _version_from(row.get("synced_at")),
        "source_name": source_name,
        "profile": profile,
        "facts": facts,
    }
