"""Explicit maintenance actions for vacancy scoring and cover outputs.

All actions protect user-decided/send states. Archive is deliberately non-learning:
it only changes lifecycle state and never calls an LLM or creates a rule proposal.
"""

from __future__ import annotations

import asyncio

from app.ai.agent import HHAgent
from app.db.supabase import service_client
from app.services import (
    candidate_context_service,
    pipeline_cover_letters,
    pipeline_scoring,
    selection_rules,
    vacancy_pipeline,
    vacancy_review_service,
)

SAFE_SCORE_STATUSES = ("scored", "review", "score_error", "rejected_by_rule")
INCOMPLETE_STATUSES = ("discovered", "score_error", "scored", "review")
ARCHIVABLE_STATUSES = ("discovered", "scoring", "scored", "review", "score_error")
SAFE_COVER_STATUS = "letter_draft"
MAX_SCORE_MAINTENANCE = 50
MAX_COVER_MAINTENANCE = 25
MAX_BULK_ARCHIVE = 200


def _requeue_score(user_id: str, row: dict) -> bool:
    res = (
        service_client.table("vacancy_pipeline")
        .update(
            {
                "status": "discovered",
                "score": None,
                "score_details": None,
                "score_explanation": None,
                "hard_filter_reason": None,
                "auto_reject_details": None,
                "score_attempts": 0,
                "next_score_at": None,
                "last_score_error": None,
                "score_claim_token": None,
                "score_claimed_at": None,
                "score_lease_expires_at": None,
                "updated_at": vacancy_pipeline._now(),
            }
        )
        .eq("user_id", user_id)
        .eq("id", row["id"])
        .eq("status", row["status"])
        .execute()
    )
    return bool(res.data)


async def _stale_score_rows(user_id: str, limit: int = MAX_SCORE_MAINTENANCE) -> list[dict]:
    rows = await vacancy_review_service.list_vacancies(
        user_id,
        statuses=list(SAFE_SCORE_STATUSES),
        limit=limit,
        offset=0,
        include_stale=True,
    )
    return [row for row in rows if row.get("score_stale") is True]


async def _stale_cover_rows(user_id: str, limit: int = MAX_COVER_MAINTENANCE) -> list[dict]:
    rows = await vacancy_review_service.list_vacancies(
        user_id,
        statuses=[SAFE_COVER_STATUS],
        limit=limit,
        offset=0,
        include_stale=True,
    )
    return [
        row
        for row in rows
        if row.get("cover_stale") is True
        and not (row.get("cover_letter_meta") or {}).get("edited_by_user")
    ]


def _incomplete_rows(user_id: str, limit: int = MAX_SCORE_MAINTENANCE) -> list[dict]:
    res = (
        service_client.table("vacancy_pipeline")
        .select("id,status,score,score_details,score_attempts,next_score_at")
        .eq("user_id", user_id)
        .in_("status", list(INCOMPLETE_STATUSES))
        .order("discovered_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = res.data or []
    out: list[dict] = []
    for row in rows:
        status = row.get("status")
        details = row.get("score_details") or {}
        if status in {"discovered", "score_error"}:
            out.append(row)
        elif status in {"scored", "review"} and (
            row.get("score") is None or bool(details.get("error"))
        ):
            out.append(row)
    return out


def _empty_scoring_summary(found: int = 0) -> dict[str, int]:
    return {
        "found": found,
        "scored": 0,
        "hard_filtered": 0,
        "archived": 0,
        "errors": 0,
        "retryable_errors": 0,
        "skipped": 0,
        "circuit_breaker": 0,
    }


def _count_outcome(summary: dict[str, int], outcome: str) -> None:
    if outcome == "scored":
        summary["scored"] += 1
    elif outcome == "hard_filtered":
        summary["hard_filtered"] += 1
    elif outcome == "archived":
        summary["archived"] += 1
    elif outcome == "retryable":
        summary["retryable_errors"] += 1
    elif outcome in {"error", "transient_error"}:
        summary["errors"] += 1
    else:
        summary["skipped"] += 1


async def get_status(user_id: str) -> dict:
    score_rows, cover_rows = await asyncio.gather(
        _stale_score_rows(user_id),
        _stale_cover_rows(user_id),
    )
    incomplete = await asyncio.to_thread(_incomplete_rows, user_id)
    return {
        "stale_scores": len(score_rows),
        "incomplete_scores": len(incomplete),
        "stale_covers_safe_to_regenerate": len(cover_rows),
        "score_limit": MAX_SCORE_MAINTENANCE,
        "cover_limit": MAX_COVER_MAINTENANCE,
        "protected_states": [
            "selected",
            "letter_draft",
            "approved",
            "queued_to_send",
            "sending",
            "sent",
            "hold",
            "rejected_by_user",
            "archived",
        ],
    }


async def rescore_stale(user_id: str) -> dict:
    rows = await _stale_score_rows(user_id)
    if not rows:
        return {"matched_stale": 0, "requeued": 0, "scoring": _empty_scoring_summary()}

    context, rules = await asyncio.gather(
        candidate_context_service.load_candidate_context(user_id),
        selection_rules.load_active_rules(user_id),
    )
    llm = HHAgent(user_id).llm

    requeued_rows: list[dict] = []
    for row in rows:
        if await asyncio.to_thread(_requeue_score, user_id, row):
            requeued_rows.append({**row, "status": "discovered"})

    scoring = _empty_scoring_summary(len(requeued_rows))
    for row in requeued_rows:
        outcome = await pipeline_scoring.score_one(
            user_id,
            row,
            context=context,
            llm=llm,
            rules=rules,
        )
        _count_outcome(scoring, outcome)
    return {"matched_stale": len(rows), "requeued": len(requeued_rows), "scoring": scoring}


async def retry_incomplete(user_id: str) -> dict:
    """Recover expired claims and immediately retry non-decided incomplete rows."""
    recovered = await pipeline_scoring.reap_stale_scoring()
    rows = await asyncio.to_thread(_incomplete_rows, user_id)
    if not rows:
        return {
            "recovered_stuck": recovered,
            "matched_incomplete": 0,
            "requeued": 0,
            "scoring": _empty_scoring_summary(),
        }

    # Resolve dependencies before rewriting score_error/inconsistent rows.
    context, rules = await asyncio.gather(
        candidate_context_service.load_candidate_context(user_id),
        selection_rules.load_active_rules(user_id),
    )
    llm = HHAgent(user_id).llm

    ready: list[dict] = []
    requeued = 0
    for row in rows:
        if row["status"] == "discovered":
            ready.append(row)
            continue
        if await asyncio.to_thread(_requeue_score, user_id, row):
            ready.append({**row, "status": "discovered"})
            requeued += 1

    scoring = _empty_scoring_summary(len(ready))
    for row in ready:
        outcome = await pipeline_scoring.score_one(
            user_id,
            row,
            context=context,
            llm=llm,
            rules=rules,
        )
        _count_outcome(scoring, outcome)

    return {
        "recovered_stuck": recovered,
        "matched_incomplete": len(rows),
        "requeued": requeued,
        "scoring": scoring,
    }


async def archive_many(user_id: str, pipeline_ids: list[str]) -> dict:
    """Archive unreviewed vacancies without LLM/rule side effects."""
    ids = list(dict.fromkeys(str(item) for item in pipeline_ids if item))[:MAX_BULK_ARCHIVE]
    if not ids:
        return {"requested": 0, "archived": 0, "skipped": 0}
    res = (
        service_client.table("vacancy_pipeline")
        .select("id,status")
        .eq("user_id", user_id)
        .in_("id", ids)
        .execute()
    )
    by_id = {str(row["id"]): row for row in (res.data or [])}
    archived = 0
    skipped = 0
    for pipeline_id in ids:
        row = by_id.get(pipeline_id)
        if not row or row.get("status") not in ARCHIVABLE_STATUSES:
            skipped += 1
            continue
        changed = await asyncio.to_thread(
            vacancy_pipeline.transition,
            user_id=user_id,
            pipeline_id=pipeline_id,
            from_statuses=[row["status"]],
            to_status="archived",
            changes={
                "user_decision_reason": None,
                "next_score_at": None,
                "last_score_error": None,
            },
        )
        if changed:
            archived += 1
        else:
            skipped += 1
    return {"requested": len(ids), "archived": archived, "skipped": skipped}


async def regenerate_stale_covers(user_id: str) -> dict:
    rows = await _stale_cover_rows(user_id)
    regenerated = 0
    errors: list[dict[str, str]] = []
    for row in rows:
        pipeline_id = str(row["id"])
        try:
            await pipeline_cover_letters.generate_draft(user_id, pipeline_id)
        except Exception as ex:
            errors.append({"pipeline_id": pipeline_id, "error": str(ex)[:500]})
        else:
            regenerated += 1
    return {"matched_stale": len(rows), "regenerated": regenerated, "errors": errors}
