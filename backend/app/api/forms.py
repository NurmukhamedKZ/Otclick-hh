"""Form-draft approval endpoints — AI-filled vacancy tests awaiting user OK."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services import form_drafts

router = APIRouter(prefix="/api/forms", tags=["forms"])


class ApproveRequest(BaseModel):
    answers: list[dict] | None = None
    letter: str | None = None


class OkResponse(BaseModel):
    ok: bool = True
    status: str | None = None
    error: str | None = None


@router.get("/drafts")
async def list_drafts(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await form_drafts.list_pending(user_id)


@router.post("/drafts/{draft_id}/approve", response_model=OkResponse)
async def approve_draft(
    draft_id: str,
    body: ApproveRequest,
    user_id: str = Depends(get_current_user),
) -> OkResponse:
    try:
        status, error = await form_drafts.approve(
            user_id, draft_id, answers=body.answers, letter=body.letter
        )
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    return OkResponse(ok=status == "form_sent", status=status, error=error)


@router.post("/drafts/{draft_id}/discard", response_model=OkResponse)
async def discard_draft(
    draft_id: str, user_id: str = Depends(get_current_user)
) -> OkResponse:
    try:
        await form_drafts.discard(user_id, draft_id)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    return OkResponse()
