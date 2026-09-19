from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SendQueueItem(BaseModel):
    id: str
    vacancy_pipeline_id: str
    resume_id: str | None = None
    hh_vacancy_id: str
    approved_letter_hash: str
    batch_id: str | None = None
    status: Literal["queued", "sending", "sent", "failed", "manual_required", "cancelled"]
    attempts: int
    last_error: str | None = None
    queued_at: str
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str
    updated_at: str


class SendBatchCurrentItem(BaseModel):
    id: str
    vacancy_pipeline_id: str
    hh_vacancy_id: str
    status: str
    attempts: int = 0
    last_error: str | None = None
    queued_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class SendBatchProgress(BaseModel):
    batch_id: str | None = None
    batch_status: str | None = None
    total: int = 0
    processed: int = 0
    queued: int = 0
    sending: int = 0
    sent: int = 0
    failed: int = 0
    manual_required: int = 0
    cancelled: int = 0
    current: SendBatchCurrentItem | None = None


class SendRuntimeState(BaseModel):
    desired_state: Literal["paused", "running", "stop_after_current"]
    safety_interval_seconds: int = Field(ge=0, le=300)
    last_cycle_at: str | None = None
    last_outcome: str | None = None
    lease_active: bool = False
    runtime_wired: bool = False
    waiting_for_next_batch: int = 0
    progress: SendBatchProgress


class SendRuntimeControlRequest(BaseModel):
    action: Literal["resume", "pause", "stop_after_current", "configure"]
    safety_interval_seconds: int | None = Field(default=None, ge=0, le=300)


class BulkQueueRequest(BaseModel):
    pipeline_ids: list[str] = Field(min_length=1, max_length=100)


class BulkQueueResultItem(BaseModel):
    pipeline_id: str
    status: Literal["queued", "error"]
    job_id: str | None = None
    error: str | None = None


class BulkQueueResponse(BaseModel):
    results: list[BulkQueueResultItem]
    queued: int
    errors: int
