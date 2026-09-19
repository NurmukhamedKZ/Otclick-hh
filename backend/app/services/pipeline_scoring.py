"""Hard filter + structured LLM scoring for persistent vacancy_pipeline rows.

Scoring uses leased claim tokens: every terminal write must still own the same
claim, so a reaped/old scorer cannot overwrite a newer attempt or a user action.

Automatic rejects are explainable and come from the user's own data only: the
employer blacklist and ACTIVE user-approved selection rules. There is no
hardcoded profession list — the fit criteria are the account's resume.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from app.ai.agent import HHAgent
from app.config import settings
from app.db.supabase import service_client
from app.hh import web
from app.services import (
    candidate_context_service,
    context_fingerprints,
    selection_rules,
    vacancy_pipeline,
    vacancy_review_service,
)

logger = logging.getLogger(__name__)

MAX_SCORE_PER_RUN = 15
SCORER_PROMPT_VERSION = 2
MAX_TRANSIENT_SCORE_ATTEMPTS = 3
HH_CIRCUIT_BREAKER_THRESHOLD = 2
_TRANSIENT_RETRY_DELAYS_S = (60, 300)


class ScoreComponents(BaseModel):
    role_fit: int = Field(ge=0, le=25)
    seniority_scale_fit: int = Field(ge=0, le=25)
    requirements_match: int = Field(ge=0, le=25)
    context_fit: int = Field(ge=0, le=25)


class StructuredVacancyScore(BaseModel):
    components: ScoreComponents
    pros: list[str] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=8)
    unknowns: list[str] = Field(default_factory=list, max_length=8)
    confidence: int = Field(ge=0, le=100)
    explanation: str = Field(min_length=1, max_length=4000)

    @property
    def total(self) -> int:
        c = self.components
        return c.role_fit + c.seniority_scale_fit + c.requirements_match + c.context_fit


def _matching_rules(vacancy: dict, rules: list[dict] | None) -> list[dict]:
    return [
        rule
        for rule in (rules or [])
        if rule.get("active", True)
        and not rule.get("deleted_at")
        and isinstance(rule.get("match"), dict)
        and selection_rules.vacancy_matches(vacancy, rule["match"])
    ]


def _blacklisted_employer(vacancy: dict, blacklist: dict[str, str] | None) -> tuple[str, str] | None:
    """Return (employer_id, employer_name) when this employer is blacklisted."""
    employer_id = str(vacancy.get("employer_id") or "").strip()
    if not employer_id or employer_id not in (blacklist or {}):
        return None
    return employer_id, blacklist[employer_id] or str(vacancy.get("employer_name") or "")


def hard_filter_reason(
    vacancy: dict,
    rules: list[dict] | None = None,
    blacklist: dict[str, str] | None = None,
) -> str | None:
    """Compatibility summary for the first hard-reject reason."""
    for rule in _matching_rules(vacancy, rules):
        if rule.get("action") == "hard_reject":
            return f"approved_rule:{rule.get('id')}:{rule.get('name') or 'hard_reject'}"

    hit = _blacklisted_employer(vacancy, blacklist)
    if hit:
        return f"blacklisted_employer:{hit[0]}"
    return None


def hard_filter_details(
    vacancy: dict,
    rules: list[dict] | None = None,
    blacklist: dict[str, str] | None = None,
) -> list[dict]:
    """Return explainable snapshots for every automatic hard-reject condition."""
    details: list[dict] = []
    for rule in _matching_rules(vacancy, rules):
        if rule.get("action") != "hard_reject":
            continue
        details.append(
            {
                "type": "rule",
                "rule_id": str(rule.get("id") or ""),
                "version": rule.get("version"),
                "name": rule.get("name") or "hard_reject",
                "instruction": rule.get("instruction") or "",
                "matches": selection_rules.match_evidence(vacancy, rule.get("match") or {}),
            }
        )

    hit = _blacklisted_employer(vacancy, blacklist)
    if hit:
        employer_id, employer_name = hit
        details.append(
            {
                "type": "blacklist",
                "reason": "blacklisted_employer",
                "name": f"Работодатель в чёрном списке: {employer_name or employer_id}",
                "instruction": "employer is on the user blacklist",
                "matches": [{"field": "employer_id", "term": employer_id}],
            }
        )
    return details


def load_blacklist(user_id: str) -> dict[str, str]:
    """{employer_id: employer_name} — the user's existing employer blacklist."""
    res = (
        service_client.table("blacklist")
        .select("employer_id,employer_name")
        .eq("user_id", user_id)
        .execute()
    )
    return {
        str(row["employer_id"]): str(row.get("employer_name") or "")
        for row in (res.data or [])
        if row.get("employer_id")
    }


def _load_discovered(user_id: str, limit: int) -> list[dict]:
    due = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    res = (
        service_client.table("vacancy_pipeline")
        .select("id,hh_vacancy_id,title,employer_name,status,score_attempts,next_score_at")
        .eq("user_id", user_id)
        .eq("status", "discovered")
        .or_(f"next_score_at.is.null,next_score_at.lte.{due}")
        .order("discovered_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def _context_for_prompt(context: dict) -> str:
    facts = [
        {
            "fact_key": fact.get("fact_key"),
            "category": fact.get("category"),
            "title": fact.get("title"),
            "statement": fact.get("statement"),
            "metrics": fact.get("metrics") or {},
            "tags": fact.get("tags") or [],
        }
        for fact in context.get("facts") or []
    ]
    return json.dumps(
        {
            "profile_version": context.get("version"),
            "profile": context.get("profile") or {},
            "confirmed_facts": facts,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _rules_for_prompt(rules: list[dict]) -> str:
    return json.dumps(
        [
            {
                "id": rule.get("id"),
                "version": rule.get("version"),
                "name": rule.get("name"),
                "instruction": rule.get("instruction"),
            }
            for rule in rules
            if rule.get("action") == "scoring_preference"
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _vacancy_for_prompt(vacancy: dict) -> str:
    return json.dumps(
        {
            "hh_vacancy_id": vacancy.get("hh_vacancy_id"),
            "title": vacancy.get("title"),
            "employer": vacancy.get("employer_name"),
            "area": vacancy.get("area_name"),
            "salary": vacancy.get("salary"),
            "description": vacancy.get("description"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _system_prompt() -> str:
    return """Ты оцениваешь, насколько вакансия подходит конкретному кандидату.
Не продавай кандидата и не пиши сопроводительное письмо. Нужна строгая оценка fit.

Правила:
1. Факты о вакансии бери только из VACANCY. Не угадывай отрасль, размер компании, подчинение, задачи или компенсацию по названию бренда.
2. Факты о кандидате бери только из CANDIDATE (резюме и подтверждённые факты аккаунта). Не усиливай, не округляй и не додумывай опыт.
3. APPROVED_SCORING_RULES — явно одобренные пользователем предпочтения, match которых уже сработал на этой вакансии. Учитывай их в оценке; scoring preference не превращается в автоматический отказ.
4. Unknown не равен mismatch. Если требование, масштаб или отрасль не указаны, добавь это в unknowns и не занижай оценку только из-за отсутствия данных.
5. Отличай совпадение названия должности от совпадения содержания: одна и та же должность в разных компаниях может означать разный уровень и круг задач.
6. Компоненты по 0..25 каждая, итог считает приложение как их сумму:
   - role_fit: насколько роль и её задачи совпадают с тем, что кандидат реально делал;
   - seniority_scale_fit: уровень ответственности, размер команды/бюджета/бизнеса относительно опыта кандидата;
   - requirements_match: покрытие заявленных требований, стека и обязанностей опытом и навыками из резюме;
   - context_fit: отрасль, город/релокация, формат работы, занятость и условия относительно резюме.
7. confidence 0..100 отражает полноту данных, а не привлекательность вакансии.
8. pros/risks/unknowns — короткие конкретные пункты со ссылкой на факты, без общих фраз.
9. explanation — короткое обоснование итоговой оценки на русском языке.
"""


async def _score_with_llm(
    llm,
    context: dict,
    vacancy: dict,
    matched_rules: list[dict] | None = None,
) -> StructuredVacancyScore:
    if llm is None:
        raise RuntimeError("llm_not_configured")
    model = llm.with_structured_output(StructuredVacancyScore)
    scoring_rules = [
        rule for rule in (matched_rules or []) if rule.get("action") == "scoring_preference"
    ]
    result = await model.ainvoke(
        [
            ("system", _system_prompt()),
            (
                "human",
                "CANDIDATE:\n"
                + _context_for_prompt(context)
                + "\n\nAPPROVED_SCORING_RULES:\n"
                + _rules_for_prompt(scoring_rules)
                + "\n\nVACANCY:\n"
                + _vacancy_for_prompt(vacancy),
            ),
        ]
    )
    return StructuredVacancyScore.model_validate(result) if isinstance(result, dict) else result


async def _mark_error(
    user_id: str,
    pipeline_id: str,
    claim_token: str,
    error: Exception | str,
    *,
    extra_changes: dict | None = None,
) -> bool:
    message = str(error)[:2000] or "unknown_scoring_error"
    return await asyncio.to_thread(
        vacancy_pipeline.transition,
        user_id=user_id,
        pipeline_id=pipeline_id,
        from_statuses=["scoring"],
        to_status="score_error",
        expected_claim_token=claim_token,
        changes={
            "score": None,
            "score_details": {"error": message},
            "score_explanation": message,
            "next_score_at": None,
            "last_score_error": message,
            **(extra_changes or {}),
        },
    )


async def _mark_transient_hh_error(
    user_id: str,
    row: dict,
    claim_token: str,
    error: Exception | str,
) -> str:
    pipeline_id = str(row["id"])
    message = str(error)[:2000] or "transient_hh_error"
    attempt = int(row.get("score_attempts") or 0) + 1

    if attempt >= MAX_TRANSIENT_SCORE_ATTEMPTS:
        changed = await _mark_error(
            user_id,
            pipeline_id,
            claim_token,
            error,
            extra_changes={
                "score_attempts": attempt,
                "score_details": {
                    "error": message,
                    "transient_hh": True,
                    "attempt": attempt,
                    "exhausted": True,
                },
            },
        )
        return "transient_error" if changed else "skipped"

    delay_s = _TRANSIENT_RETRY_DELAYS_S[min(attempt - 1, len(_TRANSIENT_RETRY_DELAYS_S) - 1)]
    next_score_at = (datetime.now(UTC) + timedelta(seconds=delay_s)).isoformat()
    changed = await asyncio.to_thread(
        vacancy_pipeline.transition,
        user_id=user_id,
        pipeline_id=pipeline_id,
        from_statuses=["scoring"],
        to_status="discovered",
        expected_claim_token=claim_token,
        changes={
            "score": None,
            "score_attempts": attempt,
            "next_score_at": next_score_at,
            "last_score_error": message,
            "score_details": {
                "retryable_error": message,
                "transient_hh": True,
                "attempt": attempt,
                "next_score_at": next_score_at,
            },
            "score_explanation": None,
        },
    )
    return "retryable" if changed else "skipped"


async def score_one(
    user_id: str,
    row: dict,
    *,
    context: dict,
    llm,
    rules: list[dict] | None = None,
    blacklist: dict[str, str] | None = None,
) -> str:
    pipeline_id = str(row["id"])
    claim_token = await asyncio.to_thread(
        vacancy_pipeline.claim_for_scoring,
        user_id=user_id,
        pipeline_id=pipeline_id,
    )
    if not claim_token:
        return "skipped"

    try:
        vacancy, enrichment_state = await vacancy_review_service.enrich(
            user_id,
            pipeline_id,
            expected_score_claim_token=claim_token,
        )
        if enrichment_state["archived"]:
            return "archived"
        if vacancy.get("status") != "scoring":
            return "skipped"

        score_fp = context_fingerprints.score_context(
            context=context,
            rules=rules,
            vacancy=vacancy,
            model=settings.OPENAI_MODEL,
            prompt_version=SCORER_PROMPT_VERSION,
        )
        matched_rules = _matching_rules(vacancy, rules)
        reject_details = hard_filter_details(vacancy, matched_rules, blacklist)
        applied_versions = [
            int(rule["version"])
            for rule in matched_rules
            if rule.get("version") is not None
        ]
        if reject_details:
            reason = hard_filter_reason(vacancy, matched_rules, blacklist) or str(
                reject_details[0].get("reason") or "hard_reject"
            )
            changed = await asyncio.to_thread(
                vacancy_pipeline.transition,
                user_id=user_id,
                pipeline_id=pipeline_id,
                from_statuses=["scoring"],
                to_status="rejected_by_rule",
                expected_claim_token=claim_token,
                changes={
                    "score": 0,
                    "hard_filter_reason": reason,
                    "auto_reject_details": reject_details,
                    "score_details": {
                        "hard_filter": True,
                        "profile_version": context.get("version"),
                        "applied_rule_versions": applied_versions,
                        "applied_rule_ids": [str(rule.get("id")) for rule in matched_rules if rule.get("id")],
                        "auto_rejects": reject_details,
                        **score_fp,
                    },
                    "score_explanation": "Автоматически отклонена: " + "; ".join(
                        str(item.get("name") or item.get("reason") or "hard reject") for item in reject_details
                    ),
                    "score_attempts": 0,
                    "next_score_at": None,
                    "last_score_error": None,
                    "score_lease_failures": 0,
                },
            )
            return "hard_filtered" if changed else "skipped"

        result = await _score_with_llm(llm, context, vacancy, matched_rules)
        details = {
            "components": result.components.model_dump(),
            "pros": result.pros,
            "risks": result.risks,
            "unknowns": result.unknowns,
            "confidence": result.confidence,
            "profile_version": context.get("version"),
            "model": settings.OPENAI_MODEL,
            "applied_rule_versions": applied_versions,
            "applied_rule_ids": [str(rule.get("id")) for rule in matched_rules if rule.get("id")],
            **score_fp,
        }
        changed = await asyncio.to_thread(
            vacancy_pipeline.transition,
            user_id=user_id,
            pipeline_id=pipeline_id,
            from_statuses=["scoring"],
            to_status="scored",
            expected_claim_token=claim_token,
            changes={
                "score": result.total,
                "score_details": details,
                "score_explanation": result.explanation,
                "hard_filter_reason": None,
                "auto_reject_details": None,
                "score_attempts": 0,
                "next_score_at": None,
                "last_score_error": None,
                "score_lease_failures": 0,
            },
        )
        return "scored" if changed else "skipped"
    except asyncio.CancelledError:
        await asyncio.to_thread(
            vacancy_pipeline.release_scoring_claim,
            user_id=user_id,
            pipeline_id=pipeline_id,
            claim_token=claim_token,
            reason="scoring cancelled",
        )
        raise
    except web.HHTransientError as ex:
        logger.warning(
            "transient HH scoring failure user=%s vacancy=%s error=%s",
            user_id,
            pipeline_id,
            ex,
        )
        return await _mark_transient_hh_error(user_id, row, claim_token, ex)
    except Exception as ex:
        logger.warning("scoring failed user=%s vacancy=%s", user_id, pipeline_id, exc_info=True)
        changed = await _mark_error(user_id, pipeline_id, claim_token, ex)
        return "error" if changed else "skipped"
    finally:
        # Harmless after a successful terminal transition; essential if a code
        # path returned while this exact claim was still left in `scoring`.
        try:
            await asyncio.to_thread(
                vacancy_pipeline.release_scoring_claim,
                user_id=user_id,
                pipeline_id=pipeline_id,
                claim_token=claim_token,
                reason="scoring ended without terminal transition",
            )
        except Exception:
            logger.exception("failed to release scoring claim user=%s vacancy=%s", user_id, pipeline_id)


async def reap_stale_scoring() -> int:
    return await asyncio.to_thread(vacancy_pipeline.reap_expired_scoring)


async def score_user(user_id: str, limit: int = MAX_SCORE_PER_RUN) -> dict[str, int]:
    rows = await asyncio.to_thread(_load_discovered, user_id, limit)
    summary = {
        "found": len(rows),
        "scored": 0,
        "hard_filtered": 0,
        "archived": 0,
        "errors": 0,
        "retryable_errors": 0,
        "skipped": 0,
        "circuit_breaker": 0,
    }
    if not rows:
        return summary

    try:
        context, rules, blacklist = await asyncio.gather(
            candidate_context_service.load_candidate_context(user_id),
            selection_rules.load_active_rules(user_id),
            asyncio.to_thread(load_blacklist, user_id),
        )
    except Exception as ex:
        logger.warning("candidate context/rules unavailable user=%s", user_id, exc_info=True)
        for row in rows:
            pipeline_id = str(row["id"])
            token = await asyncio.to_thread(
                vacancy_pipeline.claim_for_scoring,
                user_id=user_id,
                pipeline_id=pipeline_id,
            )
            if token:
                if await _mark_error(user_id, pipeline_id, token, ex):
                    summary["errors"] += 1
                else:
                    summary["skipped"] += 1
            else:
                summary["skipped"] += 1
        return summary

    llm = HHAgent(user_id).llm
    transient_streak = 0
    for row in rows:
        outcome = await score_one(
            user_id, row, context=context, llm=llm, rules=rules, blacklist=blacklist
        )
        if outcome == "scored":
            summary["scored"] += 1
            transient_streak = 0
        elif outcome == "hard_filtered":
            summary["hard_filtered"] += 1
            transient_streak = 0
        elif outcome == "archived":
            summary["archived"] += 1
            transient_streak = 0
        elif outcome == "retryable":
            summary["retryable_errors"] += 1
            transient_streak += 1
        elif outcome == "transient_error":
            summary["errors"] += 1
            transient_streak += 1
        elif outcome == "error":
            summary["errors"] += 1
            transient_streak = 0
        else:
            summary["skipped"] += 1
            transient_streak = 0

        if transient_streak >= HH_CIRCUIT_BREAKER_THRESHOLD:
            summary["circuit_breaker"] = 1
            logger.warning(
                "HH scoring circuit open user=%s after %s consecutive transient failures",
                user_id,
                transient_streak,
            )
            break

    logger.info("scoring user=%s summary=%s", user_id, summary)
    return summary
