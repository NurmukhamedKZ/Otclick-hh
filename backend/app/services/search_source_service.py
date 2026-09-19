"""CRUD and preview for persistent vacancy Search Sources."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.db.supabase import service_client
from app.services.search_sources import InvalidHHSearchURL, parse_hh_search_url

_SOURCE_COLUMNS = (
    "id,user_id,resume_id,name,source_type,raw_url,query_pairs,cursor,stats,enabled,"
    "last_checked_at,last_success_at,last_error,created_at,updated_at"
)

_OUTCOME_BATCH_SIZE = 50


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _owned_resume(user_id: str, resume_id: str) -> bool:
    res = (
        service_client.table("resumes")
        .select("id")
        .eq("user_id", user_id)
        .eq("id", resume_id)
        .maybe_single()
        .execute()
    )
    return bool(res and res.data)


def _parse_or_400(url: str):
    try:
        return parse_hh_search_url(url)
    except InvalidHHSearchURL as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex


def _outcome_counts(source_id: str) -> dict[str, int]:
    links = (
        service_client.table("vacancy_pipeline_sources")
        .select("vacancy_id")
        .eq("source_id", source_id)
        .execute()
    )
    vacancy_ids = [str(row["vacancy_id"]) for row in (links.data or []) if row.get("vacancy_id")]
    if not vacancy_ids:
        return {"hard_filtered": 0, "score_error": 0}
    data: list[dict] = []
    for start in range(0, len(vacancy_ids), _OUTCOME_BATCH_SIZE):
        batch = vacancy_ids[start : start + _OUTCOME_BATCH_SIZE]
        rows = (
            service_client.table("vacancy_pipeline")
            .select("id,status,hard_filter_reason")
            .in_("id", batch)
            .execute()
        )
        data.extend(rows.data or [])
    return {
        "hard_filtered": sum(1 for row in data if row.get("hard_filter_reason")),
        "score_error": sum(1 for row in data if row.get("status") == "score_error"),
    }


def _with_outcome_stats(source: dict) -> dict:
    row = dict(source)
    stored = row.get("stats") or {}
    outcomes = _outcome_counts(str(row["id"]))
    row["stats"] = {
        "new": int(stored.get("new") or 0),
        "duplicate": int(stored.get("duplicate") or 0),
        **outcomes,
    }
    return row


async def preview_url(url: str) -> dict:
    parsed = _parse_or_400(url)
    return {
        "raw_url": parsed.raw_url,
        "host": parsed.host,
        "path": parsed.path,
        "query_pairs": parsed.query_pairs_json(),
        "parameters": {key: list(values) for key, values in parsed.parameters.items()},
        "unsupported_parameters": list(parsed.unsupported_parameters),
    }


async def list_sources(user_id: str) -> list[dict]:
    def _query():
        return (
            service_client.table("vacancy_search_sources")
            .select(_SOURCE_COLUMNS)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )

    res = await asyncio.to_thread(_query)
    return await asyncio.gather(
        *(asyncio.to_thread(_with_outcome_stats, row) for row in (res.data or []))
    )


async def get_source(user_id: str, source_id: str) -> dict:
    def _query():
        return (
            service_client.table("vacancy_search_sources")
            .select(_SOURCE_COLUMNS)
            .eq("user_id", user_id)
            .eq("id", source_id)
            .maybe_single()
            .execute()
        )

    res = await asyncio.to_thread(_query)
    if not (res and res.data):
        raise HTTPException(status_code=404, detail="search source not found")
    return await asyncio.to_thread(_with_outcome_stats, res.data)


async def create_source(user_id: str, payload: dict) -> dict:
    parsed = _parse_or_400(payload["url"])
    resume_id = payload.get("resume_id")
    if resume_id and not await asyncio.to_thread(_owned_resume, user_id, resume_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="resume_id not found for this user",
        )

    row = {
        "user_id": user_id,
        "resume_id": resume_id,
        "name": payload["name"].strip(),
        "source_type": "search_url",
        "raw_url": parsed.raw_url,
        "query_pairs": parsed.query_pairs_json(),
        "cursor": {},
        "enabled": payload.get("enabled", True),
    }

    def _insert():
        return service_client.table("vacancy_search_sources").insert(row).execute()

    res = await asyncio.to_thread(_insert)
    if not res.data:
        raise HTTPException(status_code=500, detail="search source insert failed")
    return res.data[0]


async def update_source(user_id: str, source_id: str, payload: dict) -> dict:
    if not payload:
        raise HTTPException(status_code=400, detail="empty update")

    update = dict(payload)
    if "url" in update:
        parsed = _parse_or_400(update.pop("url"))
        update["raw_url"] = parsed.raw_url
        update["query_pairs"] = parsed.query_pairs_json()
        # A changed query is a new stream. Never reuse the old cursor.
        update["cursor"] = {}
        update["last_checked_at"] = None
        update["last_success_at"] = None
        update["last_error"] = None

    if update.get("resume_id") and not await asyncio.to_thread(
        _owned_resume, user_id, update["resume_id"]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="resume_id not found for this user",
        )

    if "name" in update and update["name"] is not None:
        update["name"] = update["name"].strip()
    update["updated_at"] = _now()

    def _update():
        return (
            service_client.table("vacancy_search_sources")
            .update(update)
            .eq("user_id", user_id)
            .eq("id", source_id)
            .execute()
        )

    res = await asyncio.to_thread(_update)
    if not res.data:
        raise HTTPException(status_code=404, detail="search source not found")
    return await asyncio.to_thread(_with_outcome_stats, res.data[0])


async def delete_source(user_id: str, source_id: str) -> None:
    def _delete():
        return (
            service_client.table("vacancy_search_sources")
            .delete()
            .eq("user_id", user_id)
            .eq("id", source_id)
            .execute()
        )

    res = await asyncio.to_thread(_delete)
    if not res.data:
        raise HTTPException(status_code=404, detail="search source not found")
