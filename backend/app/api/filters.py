from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.agent import HHAgent
from app.api.deps import get_current_user
from app.schemas.filters import (
    AutoFilterRequest,
    FilterCreate,
    FilterPreviewResponse,
    FilterResponse,
    FilterSuggestion,
    FilterUpdate,
)
from app.services import filters_service

router = APIRouter(prefix="/api/filters", tags=["filters"])


@router.post("/auto", response_model=list[FilterSuggestion])
async def auto(
    body: AutoFilterRequest,
    user_id: str = Depends(get_current_user),
):
    agent = HHAgent(user_id)
    if agent.llm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured",
        )
    suggestions = await agent.suggest_filters(body.resume_id)
    if not suggestions:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="не удалось сгенерировать фильтры — попробуйте ещё раз",
        )
    return [FilterSuggestion(**s) for s in suggestions]


@router.get("", response_model=list[FilterResponse])
async def list_all(user_id: str = Depends(get_current_user)):
    rows = await filters_service.list_filters(user_id)
    return [FilterResponse(**r) for r in rows]


@router.post("", response_model=FilterResponse, status_code=status.HTTP_201_CREATED)
async def create(
    body: FilterCreate,
    user_id: str = Depends(get_current_user),
):
    row = await filters_service.create_filter(user_id, body.model_dump(exclude_unset=True))
    return FilterResponse(**row)


@router.patch("/{filter_id}", response_model=FilterResponse)
async def update(
    filter_id: str,
    body: FilterUpdate,
    user_id: str = Depends(get_current_user),
):
    row = await filters_service.update_filter(
        user_id, filter_id, body.model_dump(exclude_unset=True)
    )
    return FilterResponse(**row)


@router.delete("/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(filter_id: str, user_id: str = Depends(get_current_user)):
    await filters_service.delete_filter(user_id, filter_id)


@router.get("/{filter_id}/preview", response_model=FilterPreviewResponse)
async def preview(filter_id: str, user_id: str = Depends(get_current_user)):
    data = await filters_service.preview_filter(user_id, filter_id)
    return FilterPreviewResponse(**data)
