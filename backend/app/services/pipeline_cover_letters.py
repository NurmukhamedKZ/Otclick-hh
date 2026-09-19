"""Cover-letter drafts for the persistent vacancy funnel.

This draft-only path never submits a response to HH. Generation is structured so
an LLM cannot satisfy the contract with two short sentences: the application
assembles the final letter from explicit executive-level blocks and confirmed
candidate facts.
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
    language: str = Field(min_length=2, max_length=16)
    greeting: str = Field(min_length=2, max_length=100)
    opening: str = Field(min_length=100, max_length=700)
    profile: str = Field(min_length=120, max_length=900)
    achievements: list[str] = Field(min_length=4, max_length=6)
    bridge: str = Field(min_length=80, max_length=650)
    cta: str = Field(min_length=30, max_length=350)
    signature: str | None = Field(default=None, max_length=220)
    fact_keys: list[str] = Field(default_factory=list, min_length=2, max_length=8)


COVER_PROMPT_VERSION = 2
MIN_GENERATED_LENGTH = 1400
MAX_GENERATED_LENGTH = 3500
_ALLOWED_STATUSES = frozenset({"selected", "letter_draft"})


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


def _clean_block(value: str) -> str:
    return " ".join(sanitize_ai_text(value).strip().split())


def _results_heading(language: str) -> str:
    return "Наиболее релевантные результаты:" if language.lower().startswith("ru") else "Most relevant results:"


def _assemble_draft(result: CoverDraftResult) -> str:
    achievements = [_clean_block(item).lstrip("-–—• ") for item in result.achievements]
    if len(achievements) < 4 or any(not item for item in achievements):
        raise ValueError("cover_letter_requires_4_to_6_achievements")

    blocks = [
        _clean_block(result.greeting),
        _clean_block(result.opening),
        _clean_block(result.profile),
        _results_heading(result.language) + "\n" + "\n".join(f"- {item}" for item in achievements),
        _clean_block(result.bridge),
        _clean_block(result.cta),
    ]
    if result.signature and _clean_block(result.signature):
        blocks.append(_clean_block(result.signature))
    return "\n\n".join(blocks).strip()


def _validate_draft(text: str, allowed_fact_keys: set[str]) -> str:
    text = sanitize_ai_text(text).strip()
    if not MIN_GENERATED_LENGTH <= len(text) <= MAX_GENERATED_LENGTH:
        raise ValueError(
            f"cover_letter_length_{len(text)}_outside_{MIN_GENERATED_LENGTH}_{MAX_GENERATED_LENGTH}"
        )
    if _results_heading("ru") not in text and _results_heading("en") not in text:
        raise ValueError("cover_letter_missing_results_block")
    bullet_count = sum(1 for line in text.splitlines() if line.startswith("- "))
    if not 4 <= bullet_count <= 6:
        raise ValueError("cover_letter_requires_4_to_6_achievements")
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
    return """Ты пишешь содержательное сопроводительное письмо к конкретной вакансии от лица кандидата уровня CIO/CDTO.
Верни structured result по заданной схеме; приложение само соберёт финальный текст.

Цель финального письма: примерно 1600–3000 знаков, предметный уровень топ-менеджера, без воды и без выдуманных фактов.

Обязательная структура:
1. greeting — отдельное короткое приветствие на языке вакансии; для русского «Добрый день!».
2. opening — 2–3 предложения: интерес к конкретной роли, понимание ключевых бизнес-задач вакансии и связь с опытом кандидата. Не копируй описание вакансии дословно.
3. profile — базовый профиль и масштаб ответственности. Используй только подтверждённые в SOURCE_DATA факты. Если подтверждены 20+ лет опыта — допустима формулировка «Более 20 лет работаю на стыке бизнеса и технологий». Если вакансия существенно связана с продажами и подтверждены 12+ лет — допустимо «Более 12 лет развивал продажи».
4. achievements — РОВНО 4–6 коротких самостоятельных достижений. Каждый пункт по возможности: управленческое действие → масштаб/изменение → бизнес-результат. Не добавляй общие пункты ради количества.
5. bridge — короткий абзац, связывающий эти результаты с ключевыми задачами вакансии.
6. cta — конкретное «Готов обсудить, как ...» с привязкой к задаче роли, без просительного тона.
7. signature — если имя кандидата однозначно есть в данных, «С уважением, <имя фамилия>», иначе null.

Фактическая строгость:
- Все цифры, сроки, названия компаний, роли, масштабы и результаты кандидата должны буквально следовать из confirmed_facts или selected_resume. Не округляй и не усиливай.
- Верни в fact_keys все confirmed fact_key, которые реально использовал; минимум 2.
- Соблюдай claim_guardrails из candidate_profile. Факты, требующие уточнения, не используй.
- Не используй числовой score вакансии как аргумент и не упоминай скоринг.
- Не перечисляй технологии без связи с бизнес-задачей/результатом.
- Не повторяй одну мысль в нескольких блоках.
- Не используй Markdown внутри полей; achievements верни без маркеров «-», их добавит приложение.
"""


async def _generate_with_llm(llm, payload: str) -> CoverDraftResult:
    if llm is None:
        raise RuntimeError("llm_not_configured")
    structured = llm.with_structured_output(CoverDraftResult)
    result = await structured.ainvoke(
        [("system", _system_prompt()), ("human", "SOURCE_DATA:\n" + payload)]
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

    resume_row = await asyncio.to_thread(_resolve_resume_row, user_id, vacancy.get("resume_id"))
    resume = await load_resume(user_id, str(resume_row["id"]))
    resume_summary = _resume_summary(resume)
    context = await candidate_context_service.load_candidate_context(user_id)
    allowed_keys = {
        str(f.get("fact_key")) for f in context.get("facts") or [] if f.get("fact_key")
    }

    result = await _generate_with_llm(
        HHAgent(user_id).llm,
        _prompt_payload(vacancy, context, resume_summary),
    )
    selected_keys = [key for key in result.fact_keys if key in allowed_keys]
    if len(selected_keys) != len(result.fact_keys) or len(set(selected_keys)) < 2:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="cover letter referenced unknown or insufficient candidate facts",
        )
    try:
        draft = _validate_draft(_assemble_draft(result), set(selected_keys))
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
        "fact_keys": list(dict.fromkeys(selected_keys)),
        "language": result.language,
        "profile_version": context.get("version"),
        "resume_id": str(resume_row["id"]),
        "resume_synced_at": resume_row.get("synced_at"),
        "edited_by_user": False,
        "structure": "rich-v2",
        "achievement_count": len(result.achievements),
        **cover_fp,
    }
    changes: dict[str, Any] = {
        "resume_id": str(resume_row["id"]),
        "cover_letter_draft": draft,
        "cover_letter_meta": meta,
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
    if len(clean) > 6000:
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
