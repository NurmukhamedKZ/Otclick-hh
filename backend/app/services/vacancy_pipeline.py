"""Persistence helpers for the vacancy discovery/review funnel."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db.supabase import service_client

PIPELINE_STATUSES = frozenset(
    {
        "discovered",
        "scoring",
        "scored",
        "review",
        "selected",
        "letter_draft",
        "approved",
        "queued_to_send",
        "sending",
        "sent",
        "rejected_by_user",
        "rejected_by_rule",
        "hold",
        "archived",
        "score_error",
        "send_error",
    }
)

SCORE_LEASE_SECONDS = 10 * 60


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _salary_snapshot(vacancy: dict) -> dict | None:
    salary = vacancy.get("salary")
    return salary if isinstance(salary, dict) else None


def _snapshot(vacancy: dict) -> dict:
    employer = vacancy.get("employer") or {}
    area = vacancy.get("area") or {}
    row: dict = {
        "title": vacancy.get("name") or "",
        "employer_id": str(employer.get("id")) if employer.get("id") else None,
        "employer_name": employer.get("name"),
        "area_name": area.get("name") if isinstance(area, dict) else None,
        "salary": _salary_snapshot(vacancy),
        "published_at": vacancy.get("published_at"),
        "vacancy_url": vacancy.get("alternate_url") or vacancy.get("url"),
        "raw_vacancy": vacancy,
    }
    description = vacancy.get("description")
    if description:
        row["description"] = description
    return row


def persist_discovered(
    *,
    user_id: str,
    resume_id: str | None,
    vacancy: dict,
    source_id: str | None = None,
) -> dict:
    """Insert a new vacancy or refresh its snapshot without resetting lifecycle."""
    hh_vacancy_id = str(vacancy.get("id") or "").strip()
    if not hh_vacancy_id:
        raise ValueError("vacancy has no HH id")

    existing = (
        service_client.table("vacancy_pipeline")
        .select("id,status,resume_id")
        .eq("user_id", user_id)
        .eq("hh_vacancy_id", hh_vacancy_id)
        .maybe_single()
        .execute()
    )
    current = existing.data if existing else None
    now = _now()
    snapshot = _snapshot(vacancy)

    if current:
        update = {**snapshot, "last_seen_at": now, "updated_at": now}
        if resume_id and not current.get("resume_id"):
            update["resume_id"] = resume_id
        res = (
            service_client.table("vacancy_pipeline")
            .update(update)
            .eq("id", current["id"])
            .eq("user_id", user_id)
            .execute()
        )
        row = (res.data or [current])[0]
        pipeline_id = current["id"]
    else:
        insert = {
            "user_id": user_id,
            "resume_id": resume_id,
            "hh_vacancy_id": hh_vacancy_id,
            "status": "discovered",
            "discovered_at": now,
            "last_seen_at": now,
            "created_at": now,
            "updated_at": now,
            **snapshot,
        }
        res = service_client.table("vacancy_pipeline").insert(insert).execute()
        if not res.data:
            raise RuntimeError("vacancy_pipeline insert returned no row")
        row = res.data[0]
        pipeline_id = row["id"]

    if source_id:
        service_client.table("vacancy_pipeline_sources").upsert(
            {
                "vacancy_id": pipeline_id,
                "source_id": source_id,
                "last_seen_at": now,
            },
            on_conflict="vacancy_id,source_id",
        ).execute()

    return row


def transition(
    *,
    user_id: str,
    pipeline_id: str,
    from_statuses: Iterable[str],
    to_status: str,
    changes: dict | None = None,
    expected_claim_token: str | None = None,
) -> bool:
    """Optimistic atomic lifecycle transition.

    When ``expected_claim_token`` is supplied, an old scorer cannot write after
    its lease was reaped and another scorer acquired the row.
    """
    allowed_from = list(dict.fromkeys(from_statuses))
    if not allowed_from:
        raise ValueError("from_statuses must not be empty")
    if to_status not in PIPELINE_STATUSES:
        raise ValueError(f"unknown pipeline status: {to_status}")
    unknown = [s for s in allowed_from if s not in PIPELINE_STATUSES]
    if unknown:
        raise ValueError(f"unknown source status(es): {', '.join(unknown)}")

    payload = {"status": to_status, "updated_at": _now(), **(changes or {})}
    if to_status != "scoring":
        payload.setdefault("score_claim_token", None)
        payload.setdefault("score_claimed_at", None)
        payload.setdefault("score_lease_expires_at", None)

    q = (
        service_client.table("vacancy_pipeline")
        .update(payload)
        .eq("id", pipeline_id)
        .eq("user_id", user_id)
        .in_("status", allowed_from)
    )
    if expected_claim_token is not None:
        q = q.eq("score_claim_token", expected_claim_token)
    res = q.execute()
    return bool(res.data)


def claim_for_scoring(
    *,
    user_id: str,
    pipeline_id: str,
    lease_seconds: int = SCORE_LEASE_SECONDS,
) -> str | None:
    """Atomically claim a discovered vacancy and return this attempt's token."""
    token = str(uuid4())
    now = datetime.now(UTC)
    claimed = transition(
        user_id=user_id,
        pipeline_id=pipeline_id,
        from_statuses=["discovered"],
        to_status="scoring",
        changes={
            "score_claim_token": token,
            "score_claimed_at": now.isoformat(),
            "score_lease_expires_at": (now + timedelta(seconds=lease_seconds)).isoformat(),
        },
    )
    return token if claimed else None


def release_scoring_claim(
    *,
    user_id: str,
    pipeline_id: str,
    claim_token: str,
    reason: str,
) -> bool:
    """Best-effort cancellation recovery for a scorer that still owns its claim."""
    return transition(
        user_id=user_id,
        pipeline_id=pipeline_id,
        from_statuses=["scoring"],
        to_status="discovered",
        expected_claim_token=claim_token,
        changes={
            "next_score_at": _now(),
            "last_score_error": reason[:2000],
        },
    )


def reap_expired_scoring() -> int:
    """Recover orphaned scoring leases, including legacy rows with no lease."""
    res = service_client.rpc("reap_expired_vacancy_scoring", {}).execute()
    value = res.data
    if isinstance(value, int):
        return value
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, int):
            return first
        if isinstance(first, dict):
            for key in ("reap_expired_vacancy_scoring", "count"):
                if key in first:
                    return int(first[key])
    return 0
