"""Cover-letter drafts for the persistent vacancy funnel.

This is a draft-only path. It never queues or submits a response to HH. Unlike
the legacy cover-letter helper, there is deliberately no generic fallback: an
LLM failure remains visible and cannot create text that looks approved.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.ai.agent import HHAgent
from app.ai.prompts import sanitize_ai_text
from app.config import settings
from app.db.supabase import service_client
from app.services import (
    candidate_context_service,
    context_fingerprints,
    vacancy_pipeline,
    vacancy_review_service,
)
from app.services.form_filler import _resume_summary, load_resume


class CoverDraftResult(BaseModel):
    draft: str = Field(min_length=500, max_length=750)
    fact_keys: list[str] = Field(default_factory=list, min_length=1, max_length=4)
    language: str = Field(min_length=2, max_length=16)


COVER_PROMPT_VERSION = 1
_ALLOWED_STATUSES = frozenset({"selected", "letter_draft"})
_GENERIC_OPENINGS = (
    "здравствуйте",
    "добрый день",
    "добрый вечер",
    "меня заинтересовала",
    "i am interested",
    "i'm interested",
    "dear hiring",
    "dear recruiter",
)


def _resolve_resume_row(user_id: str, resume_id: str | None) -> dict:
    q = (
        service_client.table("resumes")
        .select("id,hh_resume_id,title,synced_at")
        .eq("user_id", user_id)
    )
    if resume_id:
        q = q.eq("id", resume_id)
    else:
        q = q.order("synced_at", desc=True).limit(1)
    res = q.execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=409, detail="no synced resume is available")
    return rows[0]


def _validate_draft(text: str, allowed_fact_keys: set[str]) -> str:
    text = sanitize_ai_text(text).strip()
    if not 500 <= len(text) <= 750:
        raise ValueError(f"cover_letter_length_{len(text)}_outside_500_750")
    lowered = text.lower().lstrip("—-– ")
    if any(lowered.startswith(opening) for opening in _GENERIC_OPENINGS):
        raise ValueError("cover_letter_generic_opening")
    if not allowed_fact_keys:
        raise ValueError("cover_letter_has_no_confirmed_facts")
    return text


def _prompt_payload(vacancy: dict, context: dict, resume_summary: str) -> str:
    facts = [
        {
            "fact_key": fact.get("fact_key"),
            "title": fact.get("title"),
            "statement": fact.get("statement"),
            "metrics": fact.get("metrics") or {},
            "tags": fact.get("tags") or [],
        }
        for fact in context.get("facts") or []
    ]
    return json.dumps(
        {
            "vacancy": {
                "title": vacancy.get("title"),
                "employer": vacancy.get("employer_name"),
                "area": vacancy.get("area_name"),
                "salary": vacancy.get("salary"),
                "description": vacancy.get("description"),
            },
            "scoring": {
                "pros": (vacancy.get("score_details") or {}).get("pros") or [],
                "risks": (vacancy.get("score_details") or {}).get("risks") or [],
                "unknowns": (vacancy.get("score_details") or {}).get("unknowns") or [],
                "explanation": vacancy.get("score_explanation"),
            },
            "candidate_profile": context.get("profile") or {},
            "confirmed_facts": facts,
            "selected_resume": resume_summary,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _system_prompt() -> str:
    return """Ты пишешь короткое сопроводительное письмо к конкретной вакансии от лица кандидата уровня CIO/CDTO.

Строгие правила:
1. Письмо 500–750 символов с пробелами. Не сокращай факты так, чтобы менялся их смысл.
2. Пиши на языке вакансии.
3. Не начинай с приветствия, «меня заинтересовала вакансия», представления себя или пересказа названия роли.
4. Первый тезис — конкретное релевантное кандидату наблюдение/опыт, которое сразу связывает его с задачей вакансии.
5. Используй 1–2 наиболее близких подтверждённых кейса. Возвращай их fact_key в fact_keys.
6. Все числовые и фактические утверждения о кандидате должны буквально следовать из confirmed_facts или selected_resume. Ничего не округляй, не усиливай и не придумывай.
7. Соблюдай claim_guardrails из candidate_profile. Если факт отмечен как требующий уточнения — не используй его.
8. Не перечисляй стек и обязанности вакансии. Покажи соответствие через бизнес-результат: рост, скорость запуска, производительность, архитектурный/операционный эффект.
9. Не используй числовой score вакансии как аргумент и вообще не упоминай оценку/скоринг.
10. Финал — короткое предложение обсудить конкретную задачу/мандат роли, без шаблонных фраз «буду рад пообщаться подробнее».
11. Не обещай того, чего нет в подтверждённых фактах.
"""


async def _generate_with_llm(llm, payload: str) -> CoverDraftResult:
    if llm is None:
        raise RuntimeError("llm_not_configured")
    structured = llm.with_structured_output(CoverDraftResult)
    result = await structured.ainvoke(
        [
            ("system", _system_prompt()),
            ("human", "SOURCE_DATA:\n" + payload),
        ]
    )
    return CoverDraftResult.model_validate(result) if isinstance(result, dict) else result


async def generate_draft(user_id: str, pipeline_id: str) -> dict:
    vacancy = await vacancy_review_service.get_vacancy(user_id, pipeline_id)
    if vacancy["status"] not in _ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cover letter can only be generated from selected/draft, not {vacancy['status']}",
        )

    if not vacancy.get("description"):
        vacancy, enrichment = await vacancy_review_service.enrich(user_id, pipeline_id)
        if enrichment["archived"]:
            raise HTTPException(status_code=409, detail="vacancy is archived on HH")

    resume_row = await asyncio.to_thread(
        _resolve_resume_row,
        user_id,
        vacancy.get("resume_id"),
    )
    resume = await load_resume(user_id, str(resume_row["id"]))
    resume_summary = _resume_summary(resume)
    context = await candidate_context_service.load_candidate_context(user_id)
    allowed_keys = {
        str(f.get("fact_key"))
        for f in context.get("facts") or []
        if f.get("fact_key")
    }

    llm = HHAgent(user_id).llm
    result = await _generate_with_llm(
        llm,
        _prompt_payload(vacancy, context, resume_summary),
    )

    selected_keys = [key for key in result.fact_keys if key in allowed_keys]
    if not selected_keys or len(selected_keys) != len(result.fact_keys):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="cover letter referenced an unknown candidate fact",
        )
    try:
        draft = _validate_draft(result.draft, set(selected_keys))
    except ValueError as ex:
        raise HTTPException(status_code=502, detail=str(ex)) from ex

    cover_fp = context_fingerprints.cover_context(
        context=context,
        vacancy=vacancy,
        resume_row=resume_row,
        model=settings.OPENAI_MODEL,
        prompt_version=COVER_PROMPT_VERSION,
    )
    meta = {
        "fact_keys": selected_keys,
        "language": result.language,
        "profile_version": context.get("version"),
        "resume_id": str(resume_row["id"]),
        "resume_synced_at": resume_row.get("synced_at"),
        "edited_by_user": False,
        **cover_fp,
    }
    changes: dict[str, Any] = {
        "resume_id": str(resume_row["id"]),
        "cover_letter_draft": draft,
        "cover_letter_meta": meta,
        # Any new draft is unapproved by definition. Approval/hash is a later
        # explicit user action and must never survive regeneration.
        "approved_letter_hash": None,
        "approved_at": None,
    }
    if vacancy["status"] == "selected":
        changed = await asyncio.to_thread(
            vacancy_pipeline.transition,
            user_id=user_id,
            pipeline_id=pipeline_id,
            from_statuses=["selected"],
            to_status="letter_draft",
            changes=changes,
        )
        if not changed:
            raise HTTPException(status_code=409, detail="vacancy changed concurrently")
    else:
        res = (
            service_client.table("vacancy_pipeline")
            .update({**changes, "updated_at": vacancy_pipeline._now()})
            .eq("id", pipeline_id)
            .eq("user_id", user_id)
            .eq("status", "letter_draft")
            .execute()
        )
        if not (res and res.data):
            raise HTTPException(status_code=409, detail="vacancy changed concurrently")

    return await vacancy_review_service.get_vacancy(user_id, pipeline_id)


def _active_send_job(user_id: str, pipeline_id: str) -> dict | None:
    res = (
        service_client.table("application_send_queue")
        .select("id,status")
        .eq("user_id", user_id)
        .eq("vacancy_pipeline_id", pipeline_id)
        .maybe_single()
        .execute()
    )
    row = res.data if res and res.data else None
    if row and row.get("status") != "cancelled":
        return row
    return None


async def save_draft(user_id: str, pipeline_id: str, text: str) -> dict:
    vacancy = await vacancy_review_service.get_vacancy(user_id, pipeline_id)
    if vacancy["status"] not in {"letter_draft", "approved"}:
        raise HTTPException(
            status_code=409,
            detail=f"draft can only be edited from letter_draft/approved, not {vacancy['status']}",
        )
    if vacancy["status"] == "approved":
        active = await asyncio.to_thread(_active_send_job, user_id, pipeline_id)
        if active:
            raise HTTPException(
                status_code=409,
                detail=f"approved letter cannot be edited while send job is {active['status']}",
            )

    clean = sanitize_ai_text(text).strip()
    if not clean:
        raise HTTPException(status_code=400, detail="cover letter draft cannot be empty")
    if len(clean) > 4000:
        raise HTTPException(status_code=400, detail="cover letter draft is too long")

    meta = dict(vacancy.get("cover_letter_meta") or {})
    meta["edited_by_user"] = True
    changes = {
        "cover_letter_draft": clean,
        "cover_letter_meta": meta,
        "approved_letter_hash": None,
        "approved_at": None,
    }
    if vacancy["status"] == "approved":
        changed = await asyncio.to_thread(
            vacancy_pipeline.transition,
            user_id=user_id,
            pipeline_id=pipeline_id,
            from_statuses=["approved"],
            to_status="letter_draft",
            changes=changes,
        )
        if not changed:
            raise HTTPException(status_code=409, detail="vacancy changed concurrently")
    else:
        res = (
            service_client.table("vacancy_pipeline")
            .update({**changes, "updated_at": vacancy_pipeline._now()})
            .eq("id", pipeline_id)
            .eq("user_id", user_id)
            .eq("status", "letter_draft")
            .execute()
        )
        if not (res and res.data):
            raise HTTPException(status_code=409, detail="vacancy changed concurrently")
    return await vacancy_review_service.get_vacancy(user_id, pipeline_id)
