"""Debug endpoints — toggle credentials / counters / fire notifications.

Mounted only when settings.DEBUG_ENDPOINTS=True. NEVER expose in production.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.api.deps import get_current_user
from app.config import settings
from app.db.supabase import service_client
from app.services.notifications import notify
from app.worker.limiter import DAILY_LIMIT, DEFAULT_TZ
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api/_debug", tags=["debug"])


def _ensure_enabled() -> None:
    if not settings.DEBUG_ENDPOINTS:
        raise HTTPException(status_code=404, detail="not found")


@router.post("/token/invalid")
async def mark_token_invalid(user_id: str = Depends(get_current_user)) -> dict:
    _ensure_enabled()
    loop = asyncio.get_running_loop()

    def _do() -> None:
        service_client.table("hh_credentials").update(
            {
                "invalid_at": datetime.now(UTC).isoformat(),
                "invalid_reason": "debug: manual",
            }
        ).eq("user_id", user_id).execute()

    await loop.run_in_executor(None, _do)
    return {"ok": True, "invalid_at": "now"}


@router.post("/token/restore")
async def restore_token(user_id: str = Depends(get_current_user)) -> dict:
    _ensure_enabled()
    loop = asyncio.get_running_loop()

    def _do() -> None:
        service_client.table("hh_credentials").update(
            {"invalid_at": None, "invalid_reason": None}
        ).eq("user_id", user_id).execute()

    await loop.run_in_executor(None, _do)
    return {"ok": True}


@router.post("/counter/saturate")
async def saturate_counter(user_id: str = Depends(get_current_user)) -> dict:
    _ensure_enabled()
    loop = asyncio.get_running_loop()

    def _do() -> str:
        res = (
            service_client.table("profiles")
            .select("timezone")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        tz_name = (res.data or {}).get("timezone") if res else None
        tz = ZoneInfo(tz_name or DEFAULT_TZ)
        local_date = datetime.now(tz).date().isoformat()
        service_client.table("apply_counters").upsert(
            {"user_id": user_id, "date": local_date, "count": DAILY_LIMIT},
            on_conflict="user_id,date",
        ).execute()
        return local_date

    local_date = await loop.run_in_executor(None, _do)
    return {"ok": True, "date": local_date, "count": DAILY_LIMIT}


@router.post("/counter/reset")
async def reset_counter(user_id: str = Depends(get_current_user)) -> dict:
    _ensure_enabled()
    loop = asyncio.get_running_loop()

    def _do() -> None:
        service_client.table("apply_counters").delete().eq("user_id", user_id).execute()

    await loop.run_in_executor(None, _do)
    return {"ok": True}


@router.post("/notify")
async def fire_notification(
    type_: str = "captcha", user_id: str = Depends(get_current_user)
) -> dict:
    _ensure_enabled()
    allowed = {
        "captcha",
        "worker_stop",
        "limit_reached",
        "token_dead",
        "resume_missing",
        "recruiter_todo",
        "recruiter_draft",
        "form_approval",
        "cover_letter_written",
    }
    if type_ not in allowed:
        raise HTTPException(status_code=400, detail=f"type must be one of {sorted(allowed)}")
    await notify(user_id, type_, {"source": "debug"})  # type: ignore[arg-type]
    return {"ok": True, "type": type_}
