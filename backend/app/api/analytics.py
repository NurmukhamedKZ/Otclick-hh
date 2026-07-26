"""Funnel analytics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services import analytics, negotiation_sync

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
