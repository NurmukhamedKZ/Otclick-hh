from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def test_generated_draft_rejects_generic_opening():
    from app.services.pipeline_cover_letters import _validate_draft

    text = "Здравствуйте! " + ("Релевантный опыт трансформации бизнеса. " * 20)
    text = text[:600]

    with pytest.raises(ValueError, match="generic_opening"):
        _validate_draft(text, {"fact-1"})


def test_generated_draft_requires_target_length():
    from app.services.pipeline_cover_letters import _validate_draft

    with pytest.raises(ValueError, match="outside_500_750"):
        _validate_draft("Опыт трансформации бизнеса." * 5, {"fact-1"})


def test_generated_draft_accepts_grounded_non_generic_text_in_range():
    from app.services.pipeline_cover_letters import _validate_draft

    text = ("В быстрорастущем 3PL-бизнесе я перестраивал ИТ вокруг скорости запуска клиентов и прозрачности операций. " * 6)[:620]
    assert _validate_draft(text, {"fact-1"}) == text.strip()


@pytest.mark.asyncio
async def test_llm_failure_does_not_create_fallback_draft():
    from app.services import pipeline_cover_letters as svc

    vacancy = {
        "id": "p1",
        "status": "selected",
        "resume_id": "r1",
        "title": "CIO",
        "employer_name": "Example",
        "description": "Нужен CIO для цифровой трансформации.",
        "score_details": {},
        "score_explanation": None,
    }
    context = {
        "version": 1,
        "profile": {},
        "facts": [{"fact_key": "fact-1", "statement": "Подтверждённый факт"}],
    }
    fake_agent = MagicMock()
    fake_agent.llm = object()

    with (
        patch.object(svc.vacancy_review_service, "get_vacancy", new=AsyncMock(return_value=vacancy)),
        patch.object(svc, "_resolve_resume_row", return_value={"id": "r1", "hh_resume_id": "hh-r1"}),
        patch.object(svc, "load_resume", new=AsyncMock(return_value={"title": "CIO"})),
        patch.object(svc, "_resume_summary", return_value="Желаемая должность: CIO"),
        patch.object(svc.candidate_context_service, "load_candidate_context", new=AsyncMock(return_value=context)),
        patch.object(svc, "HHAgent", return_value=fake_agent),
        patch.object(svc, "_generate_with_llm", new=AsyncMock(side_effect=RuntimeError("model unavailable"))),
        patch.object(svc.vacancy_pipeline, "transition") as transition,
    ):
        with pytest.raises(RuntimeError, match="model unavailable"):
            await svc.generate_draft("u1", "p1")

    transition.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_fact_key_is_not_persisted_as_draft():
    from app.services import pipeline_cover_letters as svc

    vacancy = {
        "id": "p1",
        "status": "selected",
        "resume_id": "r1",
        "title": "CIO",
        "employer_name": "Example",
        "description": "Нужен CIO для цифровой трансформации.",
        "score_details": {},
        "score_explanation": None,
    }
    context = {
        "version": 1,
        "profile": {},
        "facts": [{"fact_key": "known", "statement": "Подтверждённый факт"}],
    }
    result = svc.CoverDraftResult(
        draft=("В быстрорастущем бизнесе я перестраивал ИТ вокруг скорости запуска и прозрачности операций. " * 7)[:620],
        fact_keys=["invented"],
        language="ru",
    )
    fake_agent = MagicMock()
    fake_agent.llm = object()

    with (
        patch.object(svc.vacancy_review_service, "get_vacancy", new=AsyncMock(return_value=vacancy)),
        patch.object(svc, "_resolve_resume_row", return_value={"id": "r1", "hh_resume_id": "hh-r1"}),
        patch.object(svc, "load_resume", new=AsyncMock(return_value={"title": "CIO"})),
        patch.object(svc, "_resume_summary", return_value="Желаемая должность: CIO"),
        patch.object(svc.candidate_context_service, "load_candidate_context", new=AsyncMock(return_value=context)),
        patch.object(svc, "HHAgent", return_value=fake_agent),
        patch.object(svc, "_generate_with_llm", new=AsyncMock(return_value=result)),
        patch.object(svc.vacancy_pipeline, "transition") as transition,
    ):
        with pytest.raises(HTTPException) as exc:
            await svc.generate_draft("u1", "p1")

    assert exc.value.status_code == 502
    transition.assert_not_called()
