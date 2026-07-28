"""Funnel analytics endpoint."""

from __future__ import annotations

import asyncio

from app.api.deps import get_current_user
from app.services import analytics, negotiation_sync, relevance
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
async def get_analytics(
    user_id: str = Depends(get_current_user),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    # hh owns the invitation/rejection state — refresh it before aggregating
    # (throttled to every 5 min inside sync_states, never raises).
    await negotiation_sync.sync_states(user_id)
    return await analytics.summary(user_id, days)


@router.get("/relevance")
async def get_relevance_log(
    user_id: str = Depends(get_current_user),
    relevant: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    """What the AI relevance filter kept (relevant=true) / dropped (false)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, relevance.list_verdicts, user_id, relevant, limit
    )
