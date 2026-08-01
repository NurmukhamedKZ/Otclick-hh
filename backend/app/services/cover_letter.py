"""Cover letter generator with Postgres cache.

- Cache key: (vacancy_id, resume_id). Hit → skip OpenAI.
- Miss → caller's llm.ainvoke; on failure → rand_text fallback template.
- All writes via service_role (RLS deny-all on table).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.prompts import COVER_LETTER_SYSTEM_PROMPT, sanitize_ai_text
from app.config import settings
from app.db.supabase import service_client

logger = logging.getLogger(__name__)


FALLBACK_TEMPLATE = (
    "{Здравствуйте|Добрый день}! Меня заинтересовала вакансия "
    "«%(vacancy_name)s» в компании %(employer_name)s. Мой опыт по резюме "
    "«%(resume_title)s» {соответствует|подходит под} требованиям, "
    "{буду рад|готов} {обсудить детали|пообщаться подробнее}."
)


def rand_text(s: str) -> str:
    """Resolve {a|b|c} alternations randomly. Ported from hh-applicant-tool."""
    while (
        temp := re.sub(
            r"\{([^{}]+)\}",
            lambda m: random.choice(m.group(1).split("|")),
            s,
        )
    ) != s:
        s = temp
    return s


def _build_fallback(vacancy: dict, resume: dict) -> str:
    placeholders = {
        "vacancy_name": vacancy.get("name") or "вакансию",
        "employer_name": (vacancy.get("employer") or {}).get("name") or "",
        "resume_title": resume.get("title") or "",
    }
    return rand_text(FALLBACK_TEMPLATE) % placeholders


def _build_prompt(vacancy: dict, resume: dict) -> str:
    from app.services.form_filler import _resume_summary

    parts = [
        f"Вакансия: {vacancy.get('name', '')}",
        f"Компания: {(vacancy.get('employer') or {}).get('name', '')}",
    ]
    desc = vacancy.get("description") or ""
    if desc:
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        parts.append(f"Описание: {desc}")
    snippet = vacancy.get("snippet") or {}
    req = snippet.get("requirement") or ""
    if req:
        parts.append(f"Требования: {re.sub(r'<[^>]+>', '', req)}")
    parts.append("Резюме кандидата:\n" + _resume_summary(resume))
    return "\n".join(parts)


def _cache_get(vacancy_id: str, resume_uuid: str) -> str | None:
    res = (
        service_client.table("cover_letters_cache")
        .select("text")
        .eq("vacancy_id", vacancy_id)
        .eq("resume_id", resume_uuid)
        .maybe_single()
        .execute()
    )
    row = res.data if res else None
    return row["text"] if row else None


def _cache_put(
    *,
    user_id: str,
    vacancy_id: str,
    resume_uuid: str,
    text: str,
    model: str | None,
    source: str,
) -> None:
    try:
        service_client.table("cover_letters_cache").upsert(
            {
                "user_id": user_id,
                "vacancy_id": vacancy_id,
                "resume_id": resume_uuid,
                "text": text,
                "model": model,
                "source": source,
            },
            on_conflict="vacancy_id,resume_id",
        ).execute()
    except Exception:  # pragma: no cover
        logger.exception("cover_letter: cache write failed")


async def generate(
    llm: BaseChatModel,
    *,
    user_id: str,
    vacancy: dict,
    resume: dict,
    resume_uuid: str,
) -> str:
    """Return cover letter text. Hits cache, then `llm`, then fallback template.

    `llm` is the caller's shared HHAgent model — no client built here.
    """
    loop = asyncio.get_running_loop()
    vacancy_id = str(vacancy.get("id") or "")
    if not vacancy_id:
        return _build_fallback(vacancy, resume)

    cached = await loop.run_in_executor(
        None, _cache_get, vacancy_id, resume_uuid
    )
    if cached:
        logger.debug("cover_letter: cache hit vacancy=%s", vacancy_id)
        return sanitize_ai_text(cached)

    text: str | None = None
    source = "fallback"
    model: str | None = None

    if settings.OPENAI_API_KEY:
        prompt = _build_prompt(vacancy, resume)
        try:
            resp = await llm.ainvoke([
                SystemMessage(COVER_LETTER_SYSTEM_PROMPT),
                HumanMessage(prompt),
            ])
            content = resp.content
            if isinstance(content, list):  # some models return content parts
                content = " ".join(str(c) for c in content)
            text = sanitize_ai_text(content) or None
            if text:
                source = "ai"
                model = settings.OPENAI_MODEL
        except Exception as ex:
            logger.warning(
                "cover_letter: LLM failed for vacancy=%s: %s", vacancy_id, ex
            )

    if not text:
        text = _build_fallback(vacancy, resume)

    await loop.run_in_executor(
        None,
        lambda: _cache_put(
            user_id=user_id,
            vacancy_id=vacancy_id,
            resume_uuid=resume_uuid,
            text=text,
            model=model,
            source=source,
        ),
    )
    return text
