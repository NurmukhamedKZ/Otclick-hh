from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.schemas.candidate_context import CandidateContextResponse
from app.services import candidate_context_service

router = APIRouter(prefix="/api/candidate-context", tags=["candidate-context"])


@router.get("", response_model=CandidateContextResponse)
async def get_candidate_context(user_id: str = Depends(get_current_user)):
    context = await candidate_context_service.load_candidate_context(user_id)
    return CandidateContextResponse(**context)
