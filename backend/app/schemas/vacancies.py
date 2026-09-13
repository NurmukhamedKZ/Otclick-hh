from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class VacancySourceRef(BaseModel):
    id: str
    name: str
    source_type: str


class VacancyPipelineResponse(BaseModel):
    id: str
    resume_id: str | None = None
    hh_vacancy_id: str
    vacancy_url: str | None = None
    title: str
    employer_id: str | None = None
    employer_name: str | None = None
    area_name: str | None = None
    salary: dict[str, Any] | None = None
    published_at: str | None = None
    discovered_at: str
    last_seen_at: str
    description: str | None = None
    status: str
    score: int | None = None
    score_details: dict[str, Any] | None = None
    score_explanation: str | None = None
    score_stale: bool | None = None
    hard_filter_reason: str | None = None
    user_decision_reason: str | None = None
    cover_letter_draft: str | None = None
    cover_letter_meta: dict[str, Any] = Field(default_factory=dict)
    cover_stale: bool | None = None
    approved_letter_hash: str | None = None
    approved_at: str | None = None
    created_at: str
    updated_at: str
    sources: list[VacancySourceRef] = Field(default_factory=list)


class VacancyDecisionRequest(BaseModel):
    action: Literal["select", "reject", "hold", "review"]
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalise_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class CoverLetterDraftUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def normalise_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("cover letter draft cannot be empty")
        return value


class VacancyEnrichmentResponse(BaseModel):
    vacancy: VacancyPipelineResponse
    already_responded: bool = False
    archived: bool = False


class PipelineMaintenanceStatus(BaseModel):
    stale_scores: int = 0
    stale_covers_safe_to_regenerate: int = 0
    score_limit: int
    cover_limit: int
    protected_states: list[str] = Field(default_factory=list)


class ScoringRunSummary(BaseModel):
    found: int = 0
    scored: int = 0
    hard_filtered: int = 0
    archived: int = 0
    errors: int = 0
    skipped: int = 0


class StaleRescoreResponse(BaseModel):
    matched_stale: int
    requeued: int
    scoring: ScoringRunSummary


class MaintenanceErrorItem(BaseModel):
    pipeline_id: str
    error: str


class StaleCoverRegenerateResponse(BaseModel):
    matched_stale: int
    regenerated: int
    errors: list[MaintenanceErrorItem] = Field(default_factory=list)
