"""Captcha handoff endpoints (plan B).

The worker handles one captcha at a time per user, so both actions clear that
user's pending rows; `{request_id}` is kept for REST shape only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services import captcha as captcha_service

router = APIRouter(prefix="/api/captcha", tags=["captcha"])


class RecheckResponse(BaseModel):
    rechecking: bool


class DismissResponse(BaseModel):
    dismissed: bool


@router.get("/pending")
async def pending(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await captcha_service.get_pending(user_id)


@router.post("/{request_id}/solve", response_model=RecheckResponse)
async def solve(
    request_id: str, user_id: str = Depends(get_current_user)
) -> RecheckResponse:
    # The runner (worker container) re-probes GET /me on its own poll cycle and
    # resumes once hh lifts the captcha — this just clears the pending row.
    await captcha_service.mark_solved(user_id)
    return RecheckResponse(rechecking=True)


@router.post("/{request_id}/dismiss", response_model=DismissResponse)
async def dismiss(
    request_id: str, user_id: str = Depends(get_current_user)
) -> DismissResponse:
    # Только убирает окно: воркер остаётся на паузе и сам продолжит, когда hh
    # снимет капчу. Кнопка «закрыть» не должна выключать автоотклик целиком.
    await captcha_service.mark_solved(user_id)
    return DismissResponse(dismissed=True)
