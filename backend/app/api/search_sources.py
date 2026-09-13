from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.schemas.search_sources import (
    ManualSearchRunResponse,
    SearchSourceCreate,
    SearchSourceResponse,
    SearchSourceUpdate,
    SearchURLPreviewRequest,
    SearchURLPreviewResponse,
)
from app.services import search_run_service, search_source_service

router = APIRouter(prefix="/api/search-sources", tags=["search-sources"])


@router.post("/preview-url", response_model=SearchURLPreviewResponse)
async def preview_url(
    body: SearchURLPreviewRequest,
    _: str = Depends(get_current_user),
):
    return SearchURLPreviewResponse(**(await search_source_service.preview_url(body.url)))


@router.post(
    "/run-now",
    response_model=ManualSearchRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_now(user_id: str = Depends(get_current_user)):
    """Queue the normal discovery + scoring pipeline and return immediately.

    API and worker live in separate containers, so the durable PostgreSQL job is
    the hand-off. Repeated clicks while a run is active are idempotent and return
    the same active run instead of starting overlapping HH traffic.
    """
    row, _created = await search_run_service.enqueue(user_id)
    return ManualSearchRunResponse(**row)


@router.get("/runs/{run_id}", response_model=ManualSearchRunResponse)
async def get_run(run_id: str, user_id: str = Depends(get_current_user)):
    return ManualSearchRunResponse(**(await search_run_service.get_owned(user_id, run_id)))


@router.get("", response_model=list[SearchSourceResponse])
async def list_all(user_id: str = Depends(get_current_user)):
    rows = await search_source_service.list_sources(user_id)
    return [SearchSourceResponse(**row) for row in rows]


@router.post("", response_model=SearchSourceResponse, status_code=status.HTTP_201_CREATED)
async def create(
    body: SearchSourceCreate,
    user_id: str = Depends(get_current_user),
):
    row = await search_source_service.create_source(
        user_id, body.model_dump(exclude_unset=True)
    )
    return SearchSourceResponse(**row)


@router.patch("/{source_id}", response_model=SearchSourceResponse)
async def update(
    source_id: str,
    body: SearchSourceUpdate,
    user_id: str = Depends(get_current_user),
):
    row = await search_source_service.update_source(
        user_id, source_id, body.model_dump(exclude_unset=True)
    )
    return SearchSourceResponse(**row)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(source_id: str, user_id: str = Depends(get_current_user)):
    await search_source_service.delete_source(user_id, source_id)
