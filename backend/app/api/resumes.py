from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.schemas.resumes import ResumeResponse, ResumesListResponse
from app.services import resume_sync

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


@router.post("/sync", response_model=ResumesListResponse)
async def sync(user_id: str = Depends(get_current_user)):
    rows = await resume_sync.sync_resumes(user_id)
    return ResumesListResponse(items=[ResumeResponse(**r) for r in rows])


@router.get("", response_model=ResumesListResponse)
async def list_resumes(user_id: str = Depends(get_current_user)):
    rows = await resume_sync.list_resumes(user_id)
    return ResumesListResponse(items=[ResumeResponse(**r) for r in rows])
