from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_candidate_context_api_returns_runtime_profile_and_facts():
    from app.api import candidate_context as api

    context = {
        "version": 1,
        "source_name": "01_Карьерное_позиционирование_CIO_CDTO(1).md",
        "profile": {
            "target_roles": [{"role": "CDTO", "priority": 1}],
            "claim_guardrails": ["не использовать неподтверждённые метрики"],
        },
        "facts": [
            {
                "fact_key": "revenue_growth",
                "category": "business_scale",
                "title": "Рост бизнеса",
                "statement": "Выручка выросла с 1,631 до 5,856 млрд ₽.",
                "metrics": {"from_billion_rub": 1.631, "to_billion_rub": 5.856},
                "tags": ["growth"],
                "source_name": "02_RFL_банк_достижений_и_фактов(1).md",
            }
        ],
    }

    with patch.object(
        api.candidate_context_service,
        "load_candidate_context",
        new=AsyncMock(return_value=context),
    ) as load:
        result = await api.get_candidate_context(user_id="u1")

    load.assert_awaited_once_with("u1")
    assert result.version == 1
    assert result.profile["target_roles"][0]["role"] == "CDTO"
    assert result.facts[0].fact_key == "revenue_growth"


@pytest.mark.asyncio
async def test_context_is_built_from_the_users_resume_and_qa_memory():
    """No bundled persona: facts must come from this account's own data and
    carry stable keys, because generated letters cite them by key."""
    from app.services import candidate_context_service as svc

    resume = {
        "title": "Инженер данных",
        "area": {"name": "Алматы"},
        "skill_set": ["SQL", "Python"],
        "skills": "<p>Строю витрины данных.</p>",
        "experience": [
            {"position": "Инженер данных", "company": "Рога", "description": "ETL", "start": "2020-01-01"},
            {"position": "Аналитик", "company": "Копыта", "description": "Отчётность", "start": "2017-01-01"},
        ],
    }
    row = {"id": "r-uuid", "hh_resume_id": "hh-1", "title": "Инженер данных", "synced_at": "2026-09-01T10:00:00+00:00"}

    with (
        patch.object(svc, "_latest_resume_row", return_value=row),
        patch("app.services.form_filler.load_resume", new=AsyncMock(return_value=resume)),
        patch.object(
            svc.qa_memory,
            "list_all",
            new=AsyncMock(return_value=[{"question": "Готовы к переезду?", "answer": "Да"}]),
        ),
    ):
        context = await svc.load_candidate_context("u1")

    keys = [f["fact_key"] for f in context["facts"]]
    assert keys == ["experience_1", "experience_2", "skills", "about", "qa_1"]
    assert len(set(keys)) == len(keys)
    assert context["source_name"] == "hh_resume:hh-1"
    assert context["profile"]["resume_id"] == "r-uuid"
    # The grounding text every LLM claim must be traceable to.
    assert "Инженер данных" in context["profile"]["resume_summary"]
    # A re-synced resume must produce a new version so fingerprints go stale.
    assert context["version"] > 1


@pytest.mark.asyncio
async def test_context_without_a_synced_resume_is_an_explicit_conflict():
    from fastapi import HTTPException

    from app.services import candidate_context_service as svc

    with patch.object(svc, "_latest_resume_row", return_value=None):
        with pytest.raises(HTTPException) as ex:
            await svc.load_candidate_context("u1")
    assert ex.value.status_code == 409
