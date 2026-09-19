"""Explicit management actions for approved selection rules."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

from app.db.supabase import service_client
from app.services import selection_rules, vacancy_pipeline

RESCORABLE_STATUSES = ("scored", "review", "score_error", "rejected_by_rule")
ARCHIVABLE_IMPACT_STATUSES = ("discovered", "scoring", "scored", "review", "score_error")


def _get_rule(user_id: str, rule_id: str) -> dict:
    res = (
        service_client.table("vacancy_selection_rules")
        .select(
            "id,proposal_id,version,name,action,match,instruction,active,"
            "deleted_at,superseded_by_rule_id,created_at,updated_at"
        )
        .eq("user_id", user_id)
        .eq("id", rule_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        raise HTTPException(status_code=404, detail="selection rule not found")
    return res.data


async def set_active(user_id: str, rule_id: str, active: bool) -> dict:
    rule = await asyncio.to_thread(_get_rule, user_id, rule_id)
    if rule.get("deleted_at") and active:
        raise HTTPException(status_code=409, detail="deleted rule cannot be activated")
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


async def soft_delete(user_id: str, rule_id: str) -> dict:
    rule = await asyncio.to_thread(_get_rule, user_id, rule_id)
    if rule.get("deleted_at"):
        return rule
    now = vacancy_pipeline._now()
    res = await asyncio.to_thread(
        lambda: service_client.table("vacancy_selection_rules")
        .update({"active": False, "deleted_at": now, "updated_at": now})
        .eq("user_id", user_id)
        .eq("id", rule_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=409, detail="selection rule changed concurrently")
    return res.data[0]


def _matching_candidates(user_id: str, rule: dict, statuses: tuple[str, ...], limit: int) -> list[dict]:
    res = (
        service_client.table("vacancy_pipeline")
        .select("id,title,employer_name,description,status,score,auto_reject_details")
        .eq("user_id", user_id)
        .in_("status", list(statuses))
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


async def requeue_impact_for_rescore(user_id: str, rule_id: str, limit: int = 300) -> dict:
    """Requeue rule-matched score states, including prior automatic rejects."""
    rule = await asyncio.to_thread(_get_rule, user_id, rule_id)
    candidates = await asyncio.to_thread(
        _matching_candidates, user_id, rule, RESCORABLE_STATUSES, limit
    )
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
            "archived",
            "sending",
            "sent",
        ],
    }


async def archive_impact(user_id: str, rule_id: str, limit: int = 300) -> dict:
    """Archive current unreviewed matches without scoring or generating proposals."""
    rule = await asyncio.to_thread(_get_rule, user_id, rule_id)
    if rule.get("deleted_at"):
        raise HTTPException(status_code=409, detail="deleted rule has no active archive impact")
    if rule.get("action") != "hard_reject":
        raise HTTPException(status_code=409, detail="only hard-reject rules can archive impact")
    candidates = await asyncio.to_thread(
        _matching_candidates,
        user_id,
        rule,
        ARCHIVABLE_IMPACT_STATUSES,
        limit,
    )
    archived = 0
    for row in candidates:
        changed = await asyncio.to_thread(
            vacancy_pipeline.transition,
            user_id=user_id,
            pipeline_id=str(row["id"]),
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
    return {
        "rule_id": rule_id,
        "rule_version": int(rule["version"]),
        "matched_archivable": len(candidates),
        "archived": archived,
        "skipped": len(candidates) - archived,
    }
