from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class QueryPair(BaseModel):
    key: str
    value: str


class SearchURLPreviewRequest(BaseModel):
    url: str = Field(min_length=1)


class SearchURLPreviewResponse(BaseModel):
    raw_url: str
    host: str
    path: str
    query_pairs: list[QueryPair]
    parameters: dict[str, list[str]]
    unsupported_parameters: list[str]


class SearchSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1)
    resume_id: str | None = None
    enabled: bool = True


class SearchSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = None
    resume_id: str | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.model_dump(exclude_unset=True):
            raise ValueError("at least one field required")
        return self


class SearchSourceStats(BaseModel):
    new: int = 0
    duplicate: int = 0
    hard_filtered: int = 0
    score_error: int = 0


class SearchSourceResponse(BaseModel):
    id: str
    resume_id: str | None = None
    name: str
    source_type: Literal["search_url", "hh_autosearch", "recommendations"]
    raw_url: str | None = None
    query_pairs: list[QueryPair] = Field(default_factory=list)
    cursor: dict[str, Any] = Field(default_factory=dict)
    stats: SearchSourceStats = Field(default_factory=SearchSourceStats)
    enabled: bool = True
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


SearchRunStatus = Literal[
    "queued",
    "discovery",
    "scoring",
    "completed",
    "completed_with_errors",
    "failed",
]


class ManualSearchRunResponse(BaseModel):
    id: str
    status: SearchRunStatus
    discovery: dict[str, int] | None = None
    scoring: dict[str, int] | None = None
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
