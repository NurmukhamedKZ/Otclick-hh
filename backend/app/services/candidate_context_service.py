"""Runtime access to curated candidate positioning and confirmed facts."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import HTTPException

from app.db.supabase import service_client

logger = logging.getLogger(__name__)

_DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _seed_default_profile(user_id: str) -> None:
    """Give a freshly registered account the install's candidate data.

    Prefers the per-install `candidate-local` copy over the bundled example.
    """
    from scripts.load_candidate_data import apply

    local = _DATA_ROOT / "candidate-local"
    data_dir = local if (local / "candidate_profile.json").is_file() else _DATA_ROOT / "candidate"
    apply(user_id, data_dir)
    logger.info("seeded candidate context user=%s from %s", user_id, data_dir.name)


def _load(user_id: str) -> dict:
    profile_res = (
        service_client.table("candidate_profiles")
        .select("version,source_name,data")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not (profile_res and profile_res.data):
        try:
            _seed_default_profile(user_id)
        except Exception:
            logger.exception("candidate context seeding failed user=%s", user_id)
            raise HTTPException(status_code=409, detail="candidate profile is not loaded") from None
        return _load(user_id)

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
