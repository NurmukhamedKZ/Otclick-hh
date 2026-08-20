"""Recruiter chat agent endpoints — draft approval + todo management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.schemas.recruiter import AnswerQuestionsRequest, OkResponse, SendDraftRequest
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


@router.get("/questions")
async def list_questions(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await recruiter.list_questions(user_id)


@router.post("/questions/{question_id}/answer", response_model=OkResponse)
async def answer_questions(
    question_id: str, body: AnswerQuestionsRequest, user_id: str = Depends(get_current_user)
) -> OkResponse:
    try:
        await recruiter.submit_answers(user_id, question_id, body.answers)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return OkResponse()


@router.post("/questions/{question_id}/discard", response_model=OkResponse)
async def discard_question(
    question_id: str, user_id: str = Depends(get_current_user)
) -> OkResponse:
    await recruiter.discard_question(user_id, question_id)
    return OkResponse()
