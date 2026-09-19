from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.schemas.send_queue import (
    BulkQueueRequest,
    BulkQueueResponse,
    SendQueueItem,
    SendRuntimeControlRequest,
    SendRuntimeState,
)
from app.services import bulk_send_queue, send_queue_service, send_runtime_control

router = APIRouter(prefix="/api/send-queue", tags=["send-queue"])


@router.get("/control", response_model=SendRuntimeState)
async def get_control(user_id: str = Depends(get_current_user)):
    state = await send_runtime_control.get_state(user_id)
    return SendRuntimeState(**state)


@router.post("/control", response_model=SendRuntimeState)
async def set_control(
    body: SendRuntimeControlRequest,
    user_id: str = Depends(get_current_user),
):
    state = await send_runtime_control.set_control(
        user_id,
        action=body.action,
        safety_interval_seconds=body.safety_interval_seconds,
    )
    return SendRuntimeState(**state)


@router.get("", response_model=list[SendQueueItem])
async def list_all(
    status: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    user_id: str = Depends(get_current_user),
):
    rows = await send_queue_service.list_queue(user_id, statuses=status, limit=limit)
    return [SendQueueItem(**row) for row in rows]


@router.post("/bulk", response_model=BulkQueueResponse)
async def queue_bulk(
    body: BulkQueueRequest,
    user_id: str = Depends(get_current_user),
):
    return BulkQueueResponse(**(await bulk_send_queue.queue_many(user_id, body.pipeline_ids)))


@router.post("/{pipeline_id}/reset", response_model=SendQueueItem)
async def reset_failed(
    pipeline_id: str,
    user_id: str = Depends(get_current_user),
):
    row = await send_queue_service.reset_failed(user_id, pipeline_id)
    return SendQueueItem(**row)


@router.post("/{pipeline_id}", response_model=SendQueueItem)
async def queue_one(
    pipeline_id: str,
    user_id: str = Depends(get_current_user),
):
    row = await send_queue_service.queue_approved(user_id, pipeline_id)
    return SendQueueItem(**row)


@router.delete("/{pipeline_id}", response_model=SendQueueItem)
async def cancel_one(
    pipeline_id: str,
    user_id: str = Depends(get_current_user),
):
    row = await send_queue_service.cancel_queued(user_id, pipeline_id)
    return SendQueueItem(**row)
