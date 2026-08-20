from __future__ import annotations

from pydantic import BaseModel


class SendDraftRequest(BaseModel):
    message: str | None = None


class AnswerQuestionsRequest(BaseModel):
    answers: list[str]


class OkResponse(BaseModel):
    ok: bool = True
