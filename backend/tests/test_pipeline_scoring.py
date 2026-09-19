import asyncio
from unittest.mock import AsyncMock, patch

import pytest

_REJECT_RULE = {
    "id": "rule-1",
    "version": 3,
    "name": "Без выездной работы",
    "action": "hard_reject",
    "active": True,
    "instruction": "отклонять разъездные вакансии",
    "match": {"title_any": ["разъездной"]},
}


def test_hard_filter_reason_comes_from_approved_rules_only():
    from app.services.pipeline_scoring import hard_filter_reason

    vacancy = {"title": "Разъездной инженер"}
    assert hard_filter_reason(vacancy) is None
    assert hard_filter_reason(vacancy, [_REJECT_RULE]) == "approved_rule:rule-1:Без выездной работы"


def test_hard_filter_ignores_rules_that_do_not_match_and_inactive_ones():
    from app.services.pipeline_scoring import hard_filter_reason

    assert hard_filter_reason({"title": "Инженер"}, [_REJECT_RULE]) is None
    assert hard_filter_reason({"title": "Разъездной инженер"}, [{**_REJECT_RULE, "active": False}]) is None
    assert hard_filter_reason({"title": "Разъездной инженер"}, [{**_REJECT_RULE, "deleted_at": "2026-01-01"}]) is None


def test_blacklisted_employer_is_an_explainable_hard_reject():
    from app.services.pipeline_scoring import hard_filter_details, hard_filter_reason

    vacancy = {"title": "Инженер", "employer_id": "42", "employer_name": "Рога"}
    assert hard_filter_reason(vacancy, [], {"42": "Рога"}) == "blacklisted_employer:42"
    assert hard_filter_reason(vacancy, [], {"7": "Копыта"}) is None

    detail = hard_filter_details(vacancy, [], {"42": "Рога"})[0]
    assert detail["type"] == "blacklist"
    assert detail["matches"] == [{"field": "employer_id", "term": "42"}]


def test_structured_score_total_is_sum_of_components():
    from app.services.pipeline_scoring import StructuredVacancyScore

    score = StructuredVacancyScore.model_validate(
        {
            "components": {
                "role_fit": 23,
                "seniority_scale_fit": 18,
                "requirements_match": 22,
                "context_fit": 17,
            },
            "pros": ["роль совпадает с последним местом работы"],
            "risks": [],
            "unknowns": ["не указан размер команды"],
            "confidence": 75,
            "explanation": "Требования покрыты, масштаб требует уточнения.",
        }
    )
    assert score.total == 80


@pytest.mark.asyncio
async def test_hard_filtered_vacancy_becomes_explainable_rule_reject_without_llm_call():
    from app.services import pipeline_scoring as svc

    enriched = {
        "id": "p1",
        "status": "scoring",
        "hh_vacancy_id": "123",
        "title": "Разъездной инженер",
        "employer_id": "42",
        "description": "Работа с выездами к клиентам.",
        "sources": [],
    }
    with (
        patch.object(svc.vacancy_pipeline, "claim_for_scoring", return_value="claim-1"),
        patch.object(svc.vacancy_pipeline, "release_scoring_claim", return_value=False),
        patch.object(svc.vacancy_pipeline, "transition", return_value=True) as transition,
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
            blacklist={"42": "Рога"},
        )

    assert outcome == "hard_filtered"
    llm_score.assert_not_awaited()
    final = transition.call_args.kwargs
    assert final["to_status"] == "rejected_by_rule"
    assert final["expected_claim_token"] == "claim-1"
    assert final["changes"]["score"] == 0
    assert final["changes"]["hard_filter_reason"] == "blacklisted_employer:42"
    assert final["changes"]["auto_reject_details"][0]["type"] == "blacklist"
    assert final["changes"]["auto_reject_details"][0]["matches"][0]["field"] == "employer_id"


@pytest.mark.asyncio
async def test_llm_failure_becomes_score_error_not_positive_match():
    from app.services import pipeline_scoring as svc

    enriched = {
        "id": "p1",
        "status": "scoring",
        "hh_vacancy_id": "123",
        "title": "Инженер",
        "description": "Поддержка внутренних сервисов.",
        "sources": [],
    }
    with (
        patch.object(svc.vacancy_pipeline, "claim_for_scoring", return_value="claim-1"),
        patch.object(svc.vacancy_pipeline, "release_scoring_claim", return_value=False),
        patch.object(svc.vacancy_pipeline, "transition", return_value=True) as transition,
        patch.object(
            svc.vacancy_review_service,
            "enrich",
            new=AsyncMock(return_value=(enriched, {"archived": False, "already_responded": False})),
        ),
        patch.object(svc, "_score_with_llm", new=AsyncMock(side_effect=RuntimeError("model unavailable"))),
    ):
        outcome = await svc.score_one(
            "u1",
            {"id": "p1"},
            context={"version": 1, "profile": {}, "facts": []},
            llm=object(),
        )

    assert outcome == "error"
    final = transition.call_args.kwargs
    assert final["to_status"] == "score_error"
    assert final["expected_claim_token"] == "claim-1"
    assert final["changes"]["score"] is None
    assert "model unavailable" in final["changes"]["score_explanation"]


@pytest.mark.asyncio
async def test_cancelled_scoring_releases_exact_claim_and_propagates_cancel():
    from app.services import pipeline_scoring as svc

    with (
        patch.object(svc.vacancy_pipeline, "claim_for_scoring", return_value="claim-cancel"),
        patch.object(svc.vacancy_pipeline, "release_scoring_claim", return_value=True) as release,
        patch.object(
            svc.vacancy_review_service,
            "enrich",
            new=AsyncMock(side_effect=asyncio.CancelledError()),
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await svc.score_one(
                "u1",
                {"id": "p1"},
                context={"version": 1, "profile": {}, "facts": []},
                llm=object(),
            )

    assert release.call_count >= 1
    first = release.call_args_list[0].kwargs
    assert first["pipeline_id"] == "p1"
    assert first["claim_token"] == "claim-cancel"
