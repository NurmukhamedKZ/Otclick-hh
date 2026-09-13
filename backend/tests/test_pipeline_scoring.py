from unittest.mock import AsyncMock, patch

import pytest


def test_hard_filter_rejects_explicit_non_target_title():
    from app.services.pipeline_scoring import hard_filter_reason

    assert (
        hard_filter_reason({"title": "Руководитель инфраструктуры"})
        == "role_mismatch_infrastructure"
    )
    assert (
        hard_filter_reason({"title": "Ведущий разработчик"})
        == "role_mismatch_hands_on_development"
    )


def test_hard_filter_does_not_reject_explicit_strategic_role():
    from app.services.pipeline_scoring import hard_filter_reason

    assert hard_filter_reason({"title": "CIO / Руководитель инфраструктуры"}) is None
    assert hard_filter_reason({"title": "CDTO"}) is None
    assert (
        hard_filter_reason({"title": "Директор по инфраструктуре и цифровой трансформации"})
        is None
    )


def test_cto_acronym_does_not_match_inside_generic_director_word():
    from app.services.pipeline_scoring import hard_filter_reason

    assert (
        hard_filter_reason({"title": "Infrastructure Director / Head of Infrastructure"})
        == "role_mismatch_infrastructure"
    )
    assert hard_filter_reason({"title": "CTO / Head of Infrastructure"}) is None


def test_structured_score_total_is_sum_of_components():
    from app.services.pipeline_scoring import StructuredVacancyScore

    score = StructuredVacancyScore.model_validate(
        {
            "components": {
                "role_fit": 23,
                "scale_fit": 18,
                "transformation_mandate": 22,
                "industry_business_context": 17,
            },
            "pros": ["роль уровня CIO"],
            "risks": [],
            "unknowns": ["не указана выручка"],
            "confidence": 75,
            "explanation": "Сильный трансформационный мандат, масштаб требует уточнения.",
        }
    )

    assert score.total == 80


@pytest.mark.asyncio
async def test_hard_filtered_vacancy_is_scored_zero_without_llm_call():
    from app.services import pipeline_scoring as svc

    enriched = {
        "id": "p1",
        "hh_vacancy_id": "123",
        "title": "Руководитель инфраструктуры",
        "description": "Эксплуатация инфраструктуры.",
        "sources": [],
    }
    transition_results = [True, True]

    with (
        patch.object(
            svc.vacancy_pipeline,
            "transition",
            side_effect=lambda **_: transition_results.pop(0),
        ) as transition,
        patch.object(
            svc.vacancy_review_service,
            "enrich",
            new=AsyncMock(return_value=(enriched, {"archived": False, "already_responded": False})),
        ),
        patch.object(svc, "_score_with_llm", new=AsyncMock()) as llm_score,
    ):
        outcome = await svc.score_one(
            "u1",
            {"id": "p1"},
            context={"version": 1, "profile": {}, "facts": []},
            llm=object(),
        )

    assert outcome == "hard_filtered"
    llm_score.assert_not_awaited()
    final = transition.call_args_list[-1].kwargs
    assert final["to_status"] == "scored"
    assert final["changes"]["score"] == 0
    assert final["changes"]["hard_filter_reason"] == "role_mismatch_infrastructure"


@pytest.mark.asyncio
async def test_llm_failure_becomes_score_error_not_positive_match():
    from app.services import pipeline_scoring as svc

    enriched = {
        "id": "p1",
        "hh_vacancy_id": "123",
        "title": "CIO",
        "description": "Трансформация бизнеса и IT.",
        "sources": [],
    }
    transition_results = [True, True]

    with (
        patch.object(
            svc.vacancy_pipeline,
            "transition",
            side_effect=lambda **_: transition_results.pop(0),
        ) as transition,
        patch.object(
            svc.vacancy_review_service,
            "enrich",
            new=AsyncMock(return_value=(enriched, {"archived": False, "already_responded": False})),
        ),
        patch.object(
            svc,
            "_score_with_llm",
            new=AsyncMock(side_effect=RuntimeError("model unavailable")),
        ),
    ):
        outcome = await svc.score_one(
            "u1",
            {"id": "p1"},
            context={"version": 1, "profile": {}, "facts": []},
            llm=object(),
        )

    assert outcome == "error"
    final = transition.call_args_list[-1].kwargs
    assert final["to_status"] == "score_error"
    assert final["changes"]["score"] is None
    assert "model unavailable" in final["changes"]["score_explanation"]