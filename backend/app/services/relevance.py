"""Batch semantic relevance filter for found vacancies.

Stage 1 (`filter_relevant`): pure classifier (llm + resume summary + snippet
items) → per-id verdict + borderline list. Structured output instead of
hand-rolled JSON parsing.
Stage 2 (`recheck_uncertain`): borderline vacancies are reclassified against
their full description (fetched over the web session). Fail-open: no llm /
error → keep all. Verdicts persist in relevance_cache (service_role).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.ai.prompts import (
    build_relevance_prompt,
    build_relevance_recheck_prompt,
)
from app.ai.structured import structured_call, structured_call_sync
from app.db.supabase import service_client

logger = logging.getLogger(__name__)

# verdict = (relevant: bool, reason: str)
Verdict = tuple[bool, str]

# Stage-2 cap per producer pass: full-description fetches go through the
# rate-limited web session, so the batch must stay small.
MAX_RECHECK_PER_PASS = 10


class _Flag(BaseModel):
    id: str
    reason: str = ""


class RelevanceVerdicts(BaseModel):
    """Stage-1 structured output. Ids absent from both lists are relevant."""

    irrelevant: list[_Flag] = Field(default_factory=list)
    uncertain: list[_Flag] = Field(default_factory=list)


class _RecheckVerdict(BaseModel):
    irrelevant: bool = False
    reason: str = ""


def filter_relevant(
    llm,
    resume_summary: str,
    items: list[dict],
    criteria: str | None = None,
) -> tuple[dict[str, Verdict], list[str]]:
    """Stage 1. Return ({vacancy_id: (relevant, reason)}, [uncertain ids]).

    items carry {id, name, snippet_requirement, snippet_responsibility}.
    Conservative: an id is irrelevant only if the LLM explicitly lists it.
    Uncertain ids go to stage 2 (or stay relevant if stage 2 is unavailable).
    Fail-open: no llm / parse error / exception → every item relevant.
    """
    ids = [str(it["id"]) for it in items if it.get("id")]
    if not items:
        return {}, []
    if not llm:
        return {vid: (True, "fail_open") for vid in ids}, []

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
    prompt = build_relevance_prompt(resume_summary, "\n".join(lines), criteria)

    try:
        parsed = structured_call_sync(llm, RelevanceVerdicts, prompt)
        irrelevant = {str(f.id): str(f.reason or "") for f in parsed.irrelevant}
        uncertain = [str(f.id) for f in parsed.uncertain]
    except Exception:
        logger.warning("relevance: LLM parse failed — fail-open (keep all)", exc_info=True)
        return {vid: (True, "fail_open") for vid in ids}, []

    uncertain = [vid for vid in uncertain if vid not in irrelevant]
    verdicts = {
        vid: ((False, irrelevant[vid]) if vid in irrelevant else (True, ""))
        for vid in ids
    }
    return verdicts, uncertain


async def recheck_uncertain(
    user_id: str,
    llm,
    resume_summary: str,
    items: list[dict],
    criteria: str | None = None,
) -> dict[str, Verdict]:
    """Stage 2. Reclassify borderline vacancies against the full description.

    Each vacancy is fetched over the stored web session (rate-limited by
    web._get). A vacancy that cannot be fetched or classified stays relevant
    (absent from the result → the caller's fail-open default)."""
    if not llm or not items:
        return {}
    if len(items) > MAX_RECHECK_PER_PASS:
        items = items[:MAX_RECHECK_PER_PASS]

    from app.hh import web  # local: web imports form_filler, avoid a cycle

    out: dict[str, Verdict] = {}
    for it in items:
        vid = str(it.get("id") or "")
        if not vid:
            continue
        try:
            vacancy = await web.get_vacancy(user_id, vid)
        except Exception:
            logger.warning(
                "relevance: recheck fetch failed for %s/%s — keeping",
                user_id, vid, exc_info=True,
            )
            continue
        prompt = build_relevance_recheck_prompt(
            resume_summary, it, str(vacancy.get("description") or ""), criteria
        )
        try:
            parsed = await structured_call(llm, _RecheckVerdict, prompt)
        except Exception:
            logger.warning(
                "relevance: recheck LLM failed for %s/%s — keeping",
                user_id, vid, exc_info=True,
            )
            continue
        out[vid] = (not parsed.irrelevant, str(parsed.reason or ""))
    return out


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
            # без названия строка выглядит как "вакансия 135546768" — прячем её
            .not_.is_("vacancy_name", "null")
        )
        if relevant is not None:
            q = q.eq("relevant", relevant)
        res = q.order("created_at", desc=True).limit(limit).execute()
    except Exception:
        logger.warning("relevance: log read failed", exc_info=True)
        return []
    return res.data or []
