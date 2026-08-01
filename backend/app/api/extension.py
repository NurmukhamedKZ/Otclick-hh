"""Browser-extension endpoints: form autofill + chat, grounded in the hh resume.

The extension never submits a form — these endpoints only decide values and hand
them back for the user to review.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.ai.agent import HHAgent
from app.api.deps import get_current_user
from app.services import candidate_context, extension_resume, qa_memory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extension", tags=["extension"])

MAX_FIELDS_PER_FRAME = 500
MAX_FRAMES = 20
MAX_PAGE_TEXT = 40_000


class FrameSnapshot(BaseModel):
    frame_id: int
    snapshot: list[dict] = Field(max_length=MAX_FIELDS_PER_FRAME)


class FillRequest(BaseModel):
    url: str = Field(max_length=2000)
    page_text: str = Field(default="", max_length=MAX_PAGE_TEXT)
    frames: list[FrameSnapshot] = Field(max_length=MAX_FRAMES)


class ChatMessage(BaseModel):
    role: str
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(max_length=60)
    page_text: str | None = Field(default=None, max_length=MAX_PAGE_TEXT)


class QAItem(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=4000)


class QARequest(BaseModel):
    items: list[QAItem] = Field(max_length=100)


@router.get("/context")
async def get_context(user_id: str = Depends(get_current_user)) -> dict:
    """Verbatim facts for deterministic fill + whether a PDF resume exists."""
    _, facts = await candidate_context.build(user_id)
    pdf = await extension_resume.fetch_resume_pdf(user_id)
    return {
        "facts": facts,
        "has_resume_file": pdf is not None,
        "resume_filename": pdf[1] if pdf else None,
    }


@router.post("/fill")
async def fill(body: FillRequest, user_id: str = Depends(get_current_user)) -> dict:
    """Decide values for every frame's fields. Never submits anything."""
    context, facts = await candidate_context.build(user_id)
    known = candidate_context.known_values(facts)
    agent = HHAgent(user_id)
    out = []
    for frame in body.frames:
        fields = await agent.fill_form_fields(
            context, body.page_text, frame.snapshot, known=known
        )
        for f in fields:
            f["frame_id"] = frame.frame_id
        out.append({"frame_id": frame.frame_id, "fields": fields})
    return {"frames": out}


@router.post("/chat")
async def chat(body: ChatRequest, user_id: str = Depends(get_current_user)) -> dict:
    context, _ = await candidate_context.build(user_id)
    answer = await HHAgent(user_id).chat(
        context, [m.model_dump() for m in body.messages], page_text=body.page_text
    )
    return {"answer": answer}


@router.post("/qa")
async def save_qa(body: QARequest, user_id: str = Depends(get_current_user)) -> dict:
    """Persist the answers the user edited, so the next form reuses them."""
    saved = 0
    for item in body.items:
        question, answer = item.question.strip(), item.answer.strip()
        if not question or not answer:
            continue
        try:
            await qa_memory.upsert(user_id, question, answer, source="form")
            saved += 1
        except Exception:
            logger.warning("extension qa: upsert failed for %s", question[:60], exc_info=True)
    return {"saved": saved}


@router.get("/resume-file")
async def resume_file(user_id: str = Depends(get_current_user)) -> Response:
    pdf = await extension_resume.fetch_resume_pdf(user_id)
    if pdf is None:
        raise HTTPException(status_code=404, detail="no resume file")
    content, name = pdf
    # hh names resumes after the candidate, so the filename is routinely
    # non-ASCII — headers are latin-1, hence RFC 5987 encoding.
    disposition = f"inline; filename*=UTF-8''{quote(name)}"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )
