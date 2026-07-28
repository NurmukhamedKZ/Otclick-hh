"""Filters CRUD + vacancy preview against hh API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException, status

from app.db.supabase import service_client
from app.services.hh_credentials import load_api_client, persist_if_refreshed

logger = logging.getLogger(__name__)

PREVIEW_PER_PAGE = 20

_FILTER_COLUMNS = (
    "id,user_id,resume_id,name,text,area,experience,work_format,"
    "employment_form,search_field,period,excluded_text,"
    "enabled,ai_filter_enabled,created_at"
)


def _check_resume_ownership(user_id: str, resume_id: str) -> None:
    res = (
        service_client.table("resumes")
        .select("id")
        .eq("user_id", user_id)
        .eq("id", resume_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="resume_id not found for this user",
        )


def _fetch_resume_for_seed(user_id: str, resume_id: str) -> dict:
    """Owned resume row (title) to seed a new filter's search text."""
    res = (
        service_client.table("resumes")
        .select("id,title")
        .eq("user_id", user_id)
        .eq("id", resume_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="resume_id not found for this user",
        )
    return res.data


async def has_active_filter(user_id: str) -> bool:
    """True if the user has ≥1 enabled filter with a resume bound — the
    minimum for the worker to produce any jobs."""
    loop = asyncio.get_running_loop()
    def _q():
        return (
            service_client.table("filters")
            .select("id")
            .eq("user_id", user_id)
            .eq("enabled", True)
            .not_.is_("resume_id", "null")
            .limit(1)
            .execute()
        )
    res = await loop.run_in_executor(None, _q)
    return bool(res.data)


async def list_filters(user_id: str) -> list[dict]:
    loop = asyncio.get_running_loop()
    def _q():
        return (
            service_client.table("filters")
            .select(_FILTER_COLUMNS)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
    res = await loop.run_in_executor(None, _q)
    return res.data or []


async def create_filter(user_id: str, payload: dict) -> dict:
    loop = asyncio.get_running_loop()
    resume_id = payload.get("resume_id")
    if resume_id:
        resume = await loop.run_in_executor(
            None, _fetch_resume_for_seed, user_id, resume_id
        )
        # Seed search from the resume so a bare filter narrows to the
        # candidate's profession instead of matching every vacancy (which
        # floods the queue with cashier/cleaner roles). Only when the client
        # left it unset.
        if not payload.get("text") and resume.get("title"):
            payload["text"] = resume["title"]
    row = {**payload, "user_id": user_id}

    def _insert():
        return (
            service_client.table("filters")
            .insert(row)
            .execute()
        )
    res = await loop.run_in_executor(None, _insert)
    if not res.data:
        raise HTTPException(status_code=500, detail="filter insert failed")
    return res.data[0]


async def update_filter(user_id: str, filter_id: str, payload: dict) -> dict:
    if not payload:
        raise HTTPException(status_code=400, detail="empty update")
    loop = asyncio.get_running_loop()
    if "resume_id" in payload and payload["resume_id"]:
        await loop.run_in_executor(
            None, _check_resume_ownership, user_id, payload["resume_id"]
        )

    def _update():
        return (
            service_client.table("filters")
            .update(payload)
            .eq("user_id", user_id)
            .eq("id", filter_id)
            .execute()
        )
    res = await loop.run_in_executor(None, _update)
    if not res.data:
        raise HTTPException(status_code=404, detail="filter not found")
    return res.data[0]


async def delete_filter(user_id: str, filter_id: str) -> None:
    loop = asyncio.get_running_loop()
    def _del():
        return (
            service_client.table("filters")
            .delete()
            .eq("user_id", user_id)
            .eq("id", filter_id)
            .execute()
        )
    res = await loop.run_in_executor(None, _del)
    if not res.data:
        raise HTTPException(status_code=404, detail="filter not found")


async def get_filter(user_id: str, filter_id: str) -> dict:
    loop = asyncio.get_running_loop()
    def _q():
        return (
            service_client.table("filters")
            .select(_FILTER_COLUMNS)
            .eq("user_id", user_id)
            .eq("id", filter_id)
            .maybe_single()
            .execute()
        )
    res = await loop.run_in_executor(None, _q)
    data = res.data if res else None
    if not data:
        raise HTTPException(status_code=404, detail="filter not found")
    return data


def _filter_to_search_params(f: dict) -> dict[str, Any]:
    params: dict[str, Any] = {
        "per_page": PREVIEW_PER_PAGE,
        "page": 0,
        "order_by": "publication_time",
    }
    if f.get("text"):
        params["text"] = f["text"]
    if f.get("area") is not None:
        params["area"] = f["area"]
    if f.get("excluded_text"):
        params["excluded_text"] = f["excluded_text"]
    if f.get("experience"):
        params["experience"] = f["experience"]
    # work_format / employment_form replace hh's deprecated schedule / employment.
    if f.get("work_format"):
        params["work_format"] = f["work_format"]
    if f.get("employment_form"):
        params["employment_form"] = f["employment_form"]
    if f.get("search_field"):
        params["search_field"] = f["search_field"]
    if f.get("period"):
        params["period"] = f["period"]
    return params


async def preview_filter(user_id: str, filter_id: str) -> dict:
    f = await get_filter(user_id, filter_id)
    client = await load_api_client(user_id)
    original_access = client.access_token
    loop = asyncio.get_running_loop()
    params = _filter_to_search_params(f)
    try:
        payload = await loop.run_in_executor(
            None, lambda: client.get("vacancies", params)
        )
    finally:
        await persist_if_refreshed(user_id, client, original_access)
    # excluded_text is applied by hh itself — nothing to filter locally.
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return {
        "found": payload.get("found", 0) if isinstance(payload, dict) else 0,
        "items": [
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "employer": (v.get("employer") or {}).get("name"),
                "area": (v.get("area") or {}).get("name"),
                "salary": v.get("salary"),
                "url": v.get("alternate_url"),
            }
            for v in items
        ],
    }
