"""Deterministic fingerprints for score/cover context.

Fingerprints make stale AI outputs visible without mutating lifecycle state.
They contain no secrets and are safe to persist inside existing JSON metadata.
Prompt contract versions live here so writers/readers compare the same version.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.config import settings

SCORER_PROMPT_VERSION = 1
COVER_PROMPT_VERSION = 1


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def candidate_hash(context: dict) -> str:
    facts = sorted(
        [
            {
                "fact_key": fact.get("fact_key"),
                "category": fact.get("category"),
                "title": fact.get("title"),
                "statement": fact.get("statement"),
                "metrics": fact.get("metrics") or {},
                "tags": fact.get("tags") or [],
            }
            for fact in context.get("facts") or []
        ],
        key=lambda item: str(item.get("fact_key") or ""),
    )
    return digest(
        {
            "profile_version": context.get("version"),
            "profile": context.get("profile") or {},
            "facts": facts,
        }
    )


def rules_hash(rules: list[dict] | None) -> str:
    active = sorted(
        [
            {
                "id": rule.get("id"),
                "version": rule.get("version"),
                "name": rule.get("name"),
                "action": rule.get("action"),
                "match": rule.get("match") or {},
                "instruction": rule.get("instruction"),
            }
            for rule in (rules or [])
            if rule.get("active", True)
        ],
        key=lambda item: (int(item.get("version") or 0), str(item.get("id") or "")),
    )
    return digest(active)


def vacancy_hash(vacancy: dict) -> str:
    """Hash stable vacancy content used by scorer/writer, not runtime flags."""
    return digest(
        {
            "hh_vacancy_id": vacancy.get("hh_vacancy_id"),
            "title": vacancy.get("title") or vacancy.get("name"),
            "employer_id": vacancy.get("employer_id"),
            "employer_name": vacancy.get("employer_name"),
            "area_name": vacancy.get("area_name"),
            "salary": vacancy.get("salary"),
            "published_at": vacancy.get("published_at"),
            "description": str(vacancy.get("description") or "").strip(),
        }
    )


def _llm_contract(model: str) -> dict[str, str]:
    """Non-secret provider identity; changing it must make old AI output stale."""
    return {
        "model": model,
        "provider_base_url": settings.OPENAI_BASE_URL.rstrip("/"),
        "structured_output_method": settings.OPENAI_STRUCTURED_OUTPUT_METHOD,
    }


def score_context(
    *,
    context: dict,
    rules: list[dict] | None,
    vacancy: dict,
    model: str,
    prompt_version: int = SCORER_PROMPT_VERSION,
) -> dict[str, Any]:
    candidate = candidate_hash(context)
    rule_set = rules_hash(rules)
    vacancy_content = vacancy_hash(vacancy)
    payload = {
        "candidate_hash": candidate,
        "rules_hash": rule_set,
        "vacancy_hash": vacancy_content,
        **_llm_contract(model),
        "prompt_version": prompt_version,
    }
    return {**payload, "context_hash": digest(payload)}


def score_anchor_hash(vacancy: dict) -> str:
    details = vacancy.get("score_details") or {}
    return digest(
        {
            "pros": details.get("pros") or [],
            "risks": details.get("risks") or [],
            "unknowns": details.get("unknowns") or [],
            "hard_filter_reason": vacancy.get("hard_filter_reason"),
            "explanation": vacancy.get("score_explanation"),
        }
    )


def resume_hash(resume_row: dict | None) -> str:
    row = resume_row or {}
    return digest(
        {
            "id": row.get("id"),
            "hh_resume_id": row.get("hh_resume_id"),
            "title": row.get("title"),
            # A successful re-sync changes synced_at, so stale drafts are exposed
            # without an HH network request during every vacancy-list render.
            "synced_at": row.get("synced_at"),
        }
    )


def cover_context(
    *,
    context: dict,
    vacancy: dict,
    resume_row: dict,
    model: str,
    prompt_version: int = COVER_PROMPT_VERSION,
) -> dict[str, Any]:
    payload = {
        "candidate_hash": candidate_hash(context),
        "vacancy_hash": vacancy_hash(vacancy),
        "resume_hash": resume_hash(resume_row),
        "score_anchor_hash": score_anchor_hash(vacancy),
        **_llm_contract(model),
        "prompt_version": prompt_version,
    }
    return {**payload, "context_hash": digest(payload)}
