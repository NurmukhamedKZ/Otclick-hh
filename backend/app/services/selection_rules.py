"""User-approved vacancy selection rules learned from review decisions.

A rejection reason is evidence for a proposal, never permission to mutate the
scorer. LLM output is persisted as pending; only explicit approval creates or
changes an active rule.
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from app.ai.agent import HHAgent
from app.db.supabase import service_client
from app.services import candidate_context_service, vacancy_pipeline, vacancy_review_service


class RuleMatch(BaseModel):
    title_any: list[str] = Field(default_factory=list, max_length=8)
    employer_any: list[str] = Field(default_factory=list, max_length=8)
    description_any: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def has_terms(self):
        if not (self.title_any or self.employer_any or self.description_any):
            raise ValueError("rule match must contain at least one term")
        return self


class RuleProposalResult(BaseModel):
    decision: Literal["rule", "change", "no_generalization"]
    name: str | None = Field(default=None, max_length=120)
    action: Literal["hard_reject", "scoring_preference"] | None = None
    match: RuleMatch | None = None
    instruction: str | None = Field(default=None, max_length=1000)
    replace_rule_id: str | None = None
    explanation: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.decision == "no_generalization":
            if self.match is not None or self.action is not None or self.instruction:
                raise ValueError("no_generalization must not carry a rule")
            return self
        if not self.name or not self.action or self.match is None or not self.instruction:
            raise ValueError("rule/change decision requires name, action, match and instruction")
        if self.decision == "change" and not self.replace_rule_id:
            raise ValueError("change decision requires replace_rule_id")
        return self


def _normalise_terms(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        term = " ".join(str(value).lower().split()).strip()
        if len(term) < 2 or term in out:
            continue
        out.append(term)
    return out


def normalise_match(match: RuleMatch | dict) -> dict[str, list[str]]:
    obj = RuleMatch.model_validate(match)
    return {
        "title_any": _normalise_terms(obj.title_any),
        "employer_any": _normalise_terms(obj.employer_any),
        "description_any": _normalise_terms(obj.description_any),
    }


def vacancy_matches(vacancy: dict, match: RuleMatch | dict) -> bool:
    """Deterministic OR matcher used for both impact preview and runtime rules."""
    terms = normalise_match(match)
    fields = {
        "title_any": str(vacancy.get("title") or vacancy.get("name") or "").lower(),
        "employer_any": str(vacancy.get("employer_name") or "").lower(),
        "description_any": str(vacancy.get("description") or "").lower(),
    }
    for key, needles in terms.items():
        haystack = fields[key]
        if any(needle in haystack for needle in needles):
            return True
    return False


def _load_active_rules(user_id: str) -> list[dict]:
    res = (
        service_client.table("vacancy_selection_rules")
        .select("id,version,name,action,match,instruction,active,created_at,updated_at")
        .eq("user_id", user_id)
        .eq("active", True)
        .order("version")
        .execute()
    )
    return res.data or []


async def load_active_rules(user_id: str) -> list[dict]:
    return await asyncio.to_thread(_load_active_rules, user_id)


def _impact_rows(user_id: str, limit: int = 300) -> list[dict]:
    res = (
        service_client.table("vacancy_pipeline")
        .select("id,title,employer_name,description,status,score")
        .eq("user_id", user_id)
        .in_(
            "status",
            [
                "discovered",
                "scoring",
                "scored",
                "review",
                "selected",
                "letter_draft",
                "approved",
                "hold",
                "rejected_by_user",
                "score_error",
            ],
        )
        .order("discovered_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def preview_impact(user_id: str, match: RuleMatch | dict) -> dict:
    rows = _impact_rows(user_id)
    matched = [row for row in rows if vacancy_matches(row, match)]
    return {
        "checked": len(rows),
        "matched_count": len(matched),
        "matched": [
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "employer_name": row.get("employer_name"),
                "status": row.get("status"),
                "score": row.get("score"),
            }
            for row in matched[:30]
        ],
        "truncated": len(matched) > 30,
    }


def _proposal_payload(vacancy: dict, reason: str, profile: dict, rules: list[dict]) -> str:
    return json.dumps(
        {
            "rejected_vacancy": {
                "id": vacancy.get("id"),
                "title": vacancy.get("title"),
                "employer": vacancy.get("employer_name"),
                "description": vacancy.get("description"),
                "score": vacancy.get("score"),
                "score_details": vacancy.get("score_details") or {},
            },
            "user_rejection_reason": reason,
            "candidate_profile": profile,
            "active_rules": rules,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _proposal_prompt() -> str:
    return """Ты анализируешь ОДНО ручное решение пользователя по вакансии и решаешь, можно ли из него вывести устойчивое правило отбора.

Верни structured result. Принципы:
1. Не активируй правило — ты только предлагаешь.
2. `no_generalization`, если причина разовая, ситуативная, слишком узкая, неоднозначная или не выражает устойчивое предпочтение.
3. `hard_reject` только когда причина явно означает абсолютное «никогда/не рассматриваю» для такого класса вакансий. Во всех остальных случаях используй `scoring_preference`.
4. Не делай employer-wide правило из отказа по одной вакансии, если пользователь прямо не написал, что не хочет именно эту компанию.
5. Не превращай неизвестные данные (нет зарплаты, выручки, подчинения) в hard reject.
6. Match должен быть простым и проверяемым приложением: case-insensitive substring terms только в title/employer/description. Не используй regex и логические выражения.
7. Match должен отражать смысл причины пользователя, а не случайные слова вакансии. Для semantic/сложного предпочтения лучше `scoring_preference` с консервативным scope.
8. Если новое решение уточняет уже существующее active rule, верни `change` и точный `replace_rule_id`; иначе `rule`.
9. instruction — короткое правило для scorer на русском языке. Для hard_reject формулируй абсолютное условие, для scoring_preference — направленность оценки.
10. Не делай выводов из того, что работодатель когда-либо отклонил кандидата; здесь учитывается только user_rejection_reason.
"""


async def generate_proposal(user_id: str, pipeline_id: str) -> dict:
    vacancy = await vacancy_review_service.get_vacancy(user_id, pipeline_id)
    if vacancy.get("status") != "rejected_by_user":
        raise HTTPException(status_code=409, detail="rule proposal requires a user-rejected vacancy")
    reason = str(vacancy.get("user_decision_reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=409, detail="rejected vacancy has no user reason")

    context, rules = await asyncio.gather(
        candidate_context_service.load_candidate_context(user_id),
        load_active_rules(user_id),
    )
    llm = HHAgent(user_id).llm
    if llm is None:
        raise HTTPException(status_code=503, detail="llm_not_configured")
    structured = llm.with_structured_output(RuleProposalResult)
    try:
        raw = await structured.ainvoke(
            [
                ("system", _proposal_prompt()),
                ("human", _proposal_payload(vacancy, reason, context.get("profile") or {}, rules)),
            ]
        )
        proposal = RuleProposalResult.model_validate(raw) if isinstance(raw, dict) else raw
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"rule proposal failed: {ex}") from ex

    proposed_rule = None
    impact = {"checked": 0, "matched_count": 0, "matched": [], "truncated": False}
    if proposal.decision != "no_generalization":
        match = normalise_match(proposal.match)
        if not any(match.values()):
            raise HTTPException(status_code=502, detail="proposed rule has no usable match terms")
        proposed_rule = {
            "name": proposal.name,
            "action": proposal.action,
            "match": match,
            "instruction": proposal.instruction,
            "replace_rule_id": proposal.replace_rule_id,
        }
        impact = await asyncio.to_thread(preview_impact, user_id, match)

    row = {
        "user_id": user_id,
        "source_vacancy_id": pipeline_id,
        "source_reason": reason,
        "decision": proposal.decision,
        "proposed_rule": proposed_rule,
        "explanation": proposal.explanation,
        "impact_preview": impact,
        "status": "pending",
    }
    res = await asyncio.to_thread(
        lambda: service_client.table("vacancy_rule_proposals").insert(row).execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="failed to persist rule proposal")
    return res.data[0]


def _get_proposal(user_id: str, proposal_id: str) -> dict:
    res = (
        service_client.table("vacancy_rule_proposals")
        .select("id,user_id,source_vacancy_id,source_reason,decision,proposed_rule,explanation,impact_preview,status,created_at,resolved_at,updated_at")
        .eq("user_id", user_id)
        .eq("id", proposal_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        raise HTTPException(status_code=404, detail="rule proposal not found")
    return res.data


def _next_version(user_id: str) -> int:
    res = (
        service_client.table("vacancy_selection_rules")
        .select("version")
        .eq("user_id", user_id)
        .order("version", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return (int(rows[0]["version"]) + 1) if rows else 1


async def resolve_proposal(user_id: str, proposal_id: str, approve: bool) -> dict:
    proposal = await asyncio.to_thread(_get_proposal, user_id, proposal_id)
    if proposal["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"proposal already {proposal['status']}")

    created_rule = None
    if approve and proposal["decision"] != "no_generalization":
        rule = proposal.get("proposed_rule") or {}
        replace_id = rule.get("replace_rule_id")
        if proposal["decision"] == "change":
            old = (
                service_client.table("vacancy_selection_rules")
                .select("id")
                .eq("user_id", user_id)
                .eq("id", replace_id)
                .eq("active", True)
                .maybe_single()
                .execute()
            )
            if not (old and old.data):
                raise HTTPException(status_code=409, detail="rule to replace is not active")

        version = await asyncio.to_thread(_next_version, user_id)
        payload = {
            "user_id": user_id,
            "proposal_id": proposal_id,
            "version": version,
            "name": rule["name"],
            "action": rule["action"],
            "match": normalise_match(rule["match"]),
            "instruction": rule["instruction"],
            "active": True,
        }
        inserted = await asyncio.to_thread(
            lambda: service_client.table("vacancy_selection_rules").insert(payload).execute()
        )
        if not inserted.data:
            raise HTTPException(status_code=500, detail="failed to create approved rule")
        created_rule = inserted.data[0]
        if proposal["decision"] == "change" and replace_id:
            await asyncio.to_thread(
                lambda: service_client.table("vacancy_selection_rules")
                .update({"active": False, "updated_at": vacancy_pipeline._now()})
                .eq("user_id", user_id)
                .eq("id", replace_id)
                .execute()
            )

    new_status = "approved" if approve else "rejected"
    updated = await asyncio.to_thread(
        lambda: service_client.table("vacancy_rule_proposals")
        .update({
            "status": new_status,
            "resolved_at": vacancy_pipeline._now(),
            "updated_at": vacancy_pipeline._now(),
        })
        .eq("user_id", user_id)
        .eq("id", proposal_id)
        .eq("status", "pending")
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=409, detail="proposal changed concurrently")
    return {"proposal": updated.data[0], "rule": created_rule}


async def list_proposals(user_id: str, status: str | None = None) -> list[dict]:
    def _query():
        q = (
            service_client.table("vacancy_rule_proposals")
            .select("id,source_vacancy_id,source_reason,decision,proposed_rule,explanation,impact_preview,status,created_at,resolved_at,updated_at")
            .eq("user_id", user_id)
        )
        if status:
            if status not in {"pending", "approved", "rejected"}:
                raise HTTPException(status_code=400, detail="unknown proposal status")
            q = q.eq("status", status)
        return q.order("created_at", desc=True).execute()

    res = await asyncio.to_thread(_query)
    return res.data or []


async def list_rules(user_id: str, active_only: bool = False) -> list[dict]:
    def _query():
        q = (
            service_client.table("vacancy_selection_rules")
            .select("id,proposal_id,version,name,action,match,instruction,active,created_at,updated_at")
            .eq("user_id", user_id)
        )
        if active_only:
            q = q.eq("active", True)
        return q.order("version", desc=True).execute()

    res = await asyncio.to_thread(_query)
    return res.data or []
