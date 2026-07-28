"""Q&A memory endpoints — user-confirmed answers reused in every AI prompt."""

from __future__ import annotations

from app.api.deps import get_current_user
from app.services import qa_memory
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/qa", tags=["qa"])


class QAUpsert(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=4000)


class OkResponse(BaseModel):
    ok: bool = True


@router.get("")
async def list_qa(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await qa_memory.list_all(user_id)


@router.post("")
async def upsert_qa(
    body: QAUpsert, user_id: str = Depends(get_current_user)
) -> dict:
    return await qa_memory.upsert(user_id, body.question, body.answer)


@router.delete("/{qa_id}", response_model=OkResponse)
async def delete_qa(
    qa_id: str, user_id: str = Depends(get_current_user)
) -> OkResponse:
    await qa_memory.delete(user_id, qa_id)
    return OkResponse()
