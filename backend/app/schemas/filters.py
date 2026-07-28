from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class FilterCreate(BaseModel):
    resume_id: str = Field(min_length=1)
    name: str | None = None
    text: str | None = None
    area: int | None = None
    experience: str | None = None
    work_format: str | None = None
    employment_form: str | None = None
    search_field: str | None = None
    period: int | None = Field(default=None, ge=1, le=30)
    excluded_text: str | None = None
    enabled: bool = True
    ai_filter_enabled: bool = False


class FilterUpdate(BaseModel):
    resume_id: str | None = None
    name: str | None = None
    text: str | None = None
    area: int | None = None
    experience: str | None = None
    work_format: str | None = None
    employment_form: str | None = None
    search_field: str | None = None
    period: int | None = Field(default=None, ge=1, le=30)
    excluded_text: str | None = None
    enabled: bool | None = None
    ai_filter_enabled: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.model_dump(exclude_unset=True):
            raise ValueError("at least one field required")
        return self


class FilterResponse(BaseModel):
    id: str
    resume_id: str | None = None
    name: str | None = None
    text: str | None = None
    area: int | None = None
    experience: str | None = None
    work_format: str | None = None
    employment_form: str | None = None
    search_field: str | None = None
    period: int | None = None
    excluded_text: str | None = None
    enabled: bool = True
    ai_filter_enabled: bool = False
    created_at: datetime | None = None


class VacancyPreviewItem(BaseModel):
    id: str | None = None
    name: str | None = None
    employer: str | None = None
    area: str | None = None
    salary: dict[str, Any] | None = None
    url: str | None = None


class FilterPreviewResponse(BaseModel):
    found: int
    items: list[VacancyPreviewItem]
