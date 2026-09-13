"""Persistence helpers for the vacancy discovery/review funnel."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

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
        "hold",
        "archived",
        "score_error",
        "send_error",
    }
)


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
    """Insert a new vacancy or refresh its snapshot without resetting lifecycle.

    Dedup is per user + HH vacancy id. Seeing an already reviewed/selected item in
    another search only updates last_seen/source attribution; it never moves the
    item back to discovered.
    """
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
        # Do not erase a previously chosen resume when a source is generic.
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
) -> bool:
    """Optimistic atomic lifecycle transition.

    PostgreSQL performs the conditional UPDATE atomically. False means another
    actor already moved the row or the caller supplied a stale state.
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
    res = (
        service_client.table("vacancy_pipeline")
        .update(payload)
        .eq("id", pipeline_id)
        .eq("user_id", user_id)
        .in_("status", allowed_from)
        .execute()
    )
    return bool(res.data)
