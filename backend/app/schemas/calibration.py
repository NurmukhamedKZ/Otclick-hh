from __future__ import annotations

from pydantic import BaseModel, Field


class CalibrationBand(BaseModel):
    label: str
    min_score: int
    max_score: int
    positive: int = 0
    rejected: int = 0
    total: int = 0


class CalibrationDecisionItem(BaseModel):
    pipeline_id: str
    hh_vacancy_id: str
    title: str
    employer_name: str | None = None
    lifecycle_status: str
    decision: str
    score: int | None = None
    score_stale: bool | None = None
    user_decision_reason: str | None = None
    discovered_at: str


class CalibrationReport(BaseModel):
    reviewed: int = 0
    positive: int = 0
    rejected: int = 0
    with_score: int = 0
    stale_scores: int = 0
    fresh_scored_decisions: int = 0
    average_positive_score: float | None = None
    average_rejected_score: float | None = None
    bands: list[CalibrationBand] = Field(default_factory=list)
    decisions: list[CalibrationDecisionItem] = Field(default_factory=list)
