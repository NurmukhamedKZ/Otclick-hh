"""Explicit maintenance actions for stale score/cover outputs.

Nothing in this module is automatic. Score maintenance is limited to the same
non-decided states used by selective rule rescore. Cover regeneration is even
stricter: only stale `letter_draft` rows that have never been edited by the
user. Approved/queued/selected/hold/rejected/sent states are never rewritten.
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

SAFE_SCORE_STATUSES = ("scored", "review", "score_error")
SAFE_COVER_STATUS = "letter_draft"
MAX_SCORE_MAINTENANCE = 50
MAX_COVER_MAINTENANCE = 25


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


async def get_status(user_id: str) -> dict:
    score_rows, cover_rows = await asyncio.gather(
        _stale_score_rows(user_id),
        _stale_cover_rows(user_id),
    )
    return {
        "stale_scores": len(score_rows),
        "stale_covers_safe_to_regenerate": len(cover_rows),
        "score_limit": MAX_SCORE_MAINTENANCE,
        "cover_limit": MAX_COVER_MAINTENANCE,
        "protected_states": [
            "selected",
            "approved",
            "queued_to_send",
            "sending",
            "sent",
            "hold",
            "rejected_by_user",
        ],
    }


async def rescore_stale(user_id: str) -> dict:
    rows = await _stale_score_rows(user_id)
    if not rows:
        return {
            "matched_stale": 0,
            "requeued": 0,
            "scoring": {
                "found": 0,
                "scored": 0,
                "hard_filtered": 0,
                "archived": 0,
                "errors": 0,
                "skipped": 0,
            },
        }

    # Load all scoring dependencies before mutating lifecycle. If context/model
    # setup is unavailable, stale rows remain untouched instead of being left in
    # a half-maintained state.
    context, rules = await asyncio.gather(
        candidate_context_service.load_candidate_context(user_id),
        selection_rules.load_active_rules(user_id),
    )
    llm = HHAgent(user_id).llm

    requeued_rows: list[dict] = []
    for row in rows:
        if await asyncio.to_thread(_requeue_score, user_id, row):
            requeued_rows.append({**row, "status": "discovered"})

    scoring = {
        "found": len(requeued_rows),
        "scored": 0,
        "hard_filtered": 0,
        "archived": 0,
        "errors": 0,
        "skipped": 0,
    }
    for row in requeued_rows:
        outcome = await pipeline_scoring.score_one(
            user_id,
            row,
            context=context,
            llm=llm,
            rules=rules,
        )
        if outcome == "scored":
            scoring["scored"] += 1
        elif outcome == "hard_filtered":
            scoring["hard_filtered"] += 1
        elif outcome == "archived":
            scoring["archived"] += 1
        elif outcome == "error":
            scoring["errors"] += 1
        else:
            scoring["skipped"] += 1

    return {
        "matched_stale": len(rows),
        "requeued": len(requeued_rows),
        "scoring": scoring,
    }


async def regenerate_stale_covers(user_id: str) -> dict:
    rows = await _stale_cover_rows(user_id)
    regenerated = 0
    errors: list[dict[str, str]] = []
    for row in rows:
        pipeline_id = str(row["id"])
        try:
            # generate_draft itself re-checks lifecycle and clears approval. We
            # only call it for letter_draft, never approved/queued rows.
            await pipeline_cover_letters.generate_draft(user_id, pipeline_id)
        except Exception as ex:
            errors.append({"pipeline_id": pipeline_id, "error": str(ex)[:500]})
        else:
            regenerated += 1
    return {
        "matched_stale": len(rows),
        "regenerated": regenerated,
        "errors": errors,
    }
