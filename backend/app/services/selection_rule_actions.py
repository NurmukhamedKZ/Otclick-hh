"""Explicit management actions for approved selection rules.

Rule activation/deactivation never rewrites historical decisions. Selective
rescore is a separate user action and only requeues non-decided score states.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

from app.db.supabase import service_client
from app.services import selection_rules, vacancy_pipeline

RESCORABLE_STATUSES = ("scored", "review", "score_error")


def _get_rule(user_id: str, rule_id: str) -> dict:
    res = (
        service_client.table("vacancy_selection_rules")
        .select("id,proposal_id,version,name,action,match,instruction,active,created_at,updated_at")
        .eq("user_id", user_id)
        .eq("id", rule_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        raise HTTPException(status_code=404, detail="selection rule not found")
    return res.data


async def set_active(user_id: str, rule_id: str, active: bool) -> dict:
    await asyncio.to_thread(_get_rule, user_id, rule_id)
    res = await asyncio.to_thread(
        lambda: service_client.table("vacancy_selection_rules")
        .update({"active": active, "updated_at": vacancy_pipeline._now()})
        .eq("user_id", user_id)
        .eq("id", rule_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=409, detail="selection rule changed concurrently")
    return res.data[0]


def _rescore_candidates(user_id: str, rule: dict, limit: int) -> list[dict]:
    res = (
        service_client.table("vacancy_pipeline")
        .select("id,title,employer_name,description,status,score")
        .eq("user_id", user_id)
        .in_("status", list(RESCORABLE_STATUSES))
        .order("discovered_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [
        row
        for row in (res.data or [])
        if selection_rules.vacancy_matches(row, rule.get("match") or {})
    ]


def _requeue_one(user_id: str, row: dict) -> bool:
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


async def requeue_impact_for_rescore(user_id: str, rule_id: str, limit: int = 300) -> dict:
    """Mark matched non-decided vacancies for the normal scoring worker.

    Selected/draft/approved/queued/hold/rejected/sent states are intentionally
    excluded even if the rule matches them; impact on those remains informational.
    """
    rule = await asyncio.to_thread(_get_rule, user_id, rule_id)
    candidates = await asyncio.to_thread(_rescore_candidates, user_id, rule, limit)
    queued = 0
    for row in candidates:
        if await asyncio.to_thread(_requeue_one, user_id, row):
            queued += 1
    return {
        "rule_id": rule_id,
        "rule_version": int(rule["version"]),
        "matched_rescorable": len(candidates),
        "queued_for_rescore": queued,
        "protected_statuses_unchanged": [
            "selected",
            "letter_draft",
            "approved",
            "queued_to_send",
            "hold",
            "rejected_by_user",
            "sending",
            "sent",
        ],
    }
