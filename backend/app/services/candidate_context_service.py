"""Runtime access to curated candidate positioning and confirmed facts."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

from app.db.supabase import service_client


def _load(user_id: str) -> dict:
    profile_res = (
        service_client.table("candidate_profiles")
        .select("version,source_name,data")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not (profile_res and profile_res.data):
        raise HTTPException(status_code=409, detail="candidate profile is not loaded")

    facts_res = (
        service_client.table("candidate_facts")
        .select("fact_key,category,title,statement,metrics,tags,source_name")
        .eq("user_id", user_id)
        .eq("active", True)
        .order("fact_key")
        .execute()
    )
    return {
        "version": int(profile_res.data["version"]),
        "source_name": profile_res.data["source_name"],
        "profile": profile_res.data["data"],
        "facts": facts_res.data or [],
    }


async def load_candidate_context(user_id: str) -> dict:
    return await asyncio.to_thread(_load, user_id)
