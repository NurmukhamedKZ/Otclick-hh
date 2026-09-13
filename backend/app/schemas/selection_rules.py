from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RuleProposalResolve(BaseModel):
    approve: bool


class RuleActiveUpdate(BaseModel):
    active: bool


class RuleProposalResponse(BaseModel):
    id: str
    source_vacancy_id: str | None = None
    source_reason: str
    decision: str
    proposed_rule: dict[str, Any] | None = None
    explanation: str | None = None
    impact_preview: dict[str, Any]
    status: str
    created_at: str
    resolved_at: str | None = None
    updated_at: str


class SelectionRuleResponse(BaseModel):
    id: str
    proposal_id: str | None = None
    version: int
    name: str
    action: str
    match: dict[str, Any]
    instruction: str
    active: bool
    created_at: str
    updated_at: str


class RuleProposalResolutionResponse(BaseModel):
    proposal: RuleProposalResponse
    rule: SelectionRuleResponse | None = None


class RuleRescoreResponse(BaseModel):
    rule_id: str
    rule_version: int
    matched_rescorable: int
    queued_for_rescore: int
    protected_statuses_unchanged: list[str]
