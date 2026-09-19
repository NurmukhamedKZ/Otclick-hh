from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CandidateFactResponse(BaseModel):
    fact_key: str
    category: str
    title: str
    statement: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    source_name: str | None = None


class CandidateContextResponse(BaseModel):
    version: int
    source_name: str
    profile: dict[str, Any]
    facts: list[CandidateFactResponse] = Field(default_factory=list)
