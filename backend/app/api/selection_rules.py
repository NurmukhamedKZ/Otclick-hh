from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.schemas.selection_rules import (
    RuleActiveUpdate,
    RuleProposalResolutionResponse,
    RuleProposalResolve,
    RuleProposalResponse,
    RuleRescoreResponse,
    SelectionRuleResponse,
)
from app.services import selection_rule_actions, selection_rules

router = APIRouter(prefix="/api/selection-rules", tags=["selection-rules"])


@router.get("/proposals", response_model=list[RuleProposalResponse])
async def list_proposals(
    status: str | None = Query(default=None),
    user_id: str = Depends(get_current_user),
):
    rows = await selection_rules.list_proposals(user_id, status=status)
    return [RuleProposalResponse(**row) for row in rows]


@router.post("/proposals/from-vacancy/{pipeline_id}", response_model=RuleProposalResponse)
async def generate_from_vacancy(
    pipeline_id: str,
    user_id: str = Depends(get_current_user),
):
    row = await selection_rules.generate_proposal(user_id, pipeline_id)
    return RuleProposalResponse(**row)


@router.post(
    "/proposals/{proposal_id}/resolve",
    response_model=RuleProposalResolutionResponse,
)
async def resolve_proposal(
    proposal_id: str,
    body: RuleProposalResolve,
    user_id: str = Depends(get_current_user),
):
    result = await selection_rules.resolve_proposal(user_id, proposal_id, body.approve)
    return RuleProposalResolutionResponse(
        proposal=RuleProposalResponse(**result["proposal"]),
        rule=SelectionRuleResponse(**result["rule"]) if result.get("rule") else None,
    )


@router.post("/{rule_id}/rescore-impact", response_model=RuleRescoreResponse)
async def rescore_impact(
    rule_id: str,
    user_id: str = Depends(get_current_user),
):
    return RuleRescoreResponse(
        **(await selection_rule_actions.requeue_impact_for_rescore(user_id, rule_id))
    )


@router.patch("/{rule_id}", response_model=SelectionRuleResponse)
async def set_rule_active(
    rule_id: str,
    body: RuleActiveUpdate,
    user_id: str = Depends(get_current_user),
):
    row = await selection_rule_actions.set_active(user_id, rule_id, body.active)
    return SelectionRuleResponse(**row)


@router.get("", response_model=list[SelectionRuleResponse])
async def list_rules(
    active_only: bool = Query(default=False),
    user_id: str = Depends(get_current_user),
):
    rows = await selection_rules.list_rules(user_id, active_only=active_only)
    return [SelectionRuleResponse(**row) for row in rows]
