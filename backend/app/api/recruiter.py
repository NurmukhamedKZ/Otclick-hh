"""Recruiter chat agent endpoints — draft approval + todo management."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.schemas.recruiter import OkResponse, SendDraftRequest
from app.services import recruiter

router = APIRouter(prefix="/api/recruiter", tags=["recruiter"])


@router.get("/drafts")
async def list_drafts(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await recruiter.list_drafts(user_id)


@router.post("/drafts/{draft_id}/send", response_model=OkResponse)
async def send_draft(
    draft_id: str, body: SendDraftRequest, user_id: str = Depends(get_current_user)
) -> OkResponse:
    await recruiter.send_draft(user_id, draft_id, message=body.message)
    return OkResponse()


@router.post("/drafts/{draft_id}/discard", response_model=OkResponse)
async def discard_draft(draft_id: str, user_id: str = Depends(get_current_user)) -> OkResponse:
    await recruiter.discard_draft(user_id, draft_id)
    return OkResponse()


@router.get("/todos")
async def list_todos(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await recruiter.list_todos(user_id)


@router.post("/todos/{todo_id}/done", response_model=OkResponse)
async def todo_done(todo_id: str, user_id: str = Depends(get_current_user)) -> OkResponse:
    await recruiter.mark_todo(user_id, todo_id, "done")
    return OkResponse()


@router.post("/todos/{todo_id}/dismiss", response_model=OkResponse)
async def todo_dismiss(todo_id: str, user_id: str = Depends(get_current_user)) -> OkResponse:
    await recruiter.mark_todo(user_id, todo_id, "dismissed")
    return OkResponse()
