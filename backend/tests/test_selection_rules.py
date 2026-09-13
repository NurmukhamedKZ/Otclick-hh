from unittest.mock import AsyncMock, patch

import pytest


def test_rule_match_is_deterministic_case_insensitive_or_scope():
    from app.services.selection_rules import vacancy_matches

    match = {
        "title_any": ["инфраструктур"],
        "employer_any": ["нежелательная компания"],
        "description_any": ["дежурств"],
    }
    assert vacancy_matches({"title": "Директор по ИНФРАСТРУКТУРЕ"}, match) is True
    assert vacancy_matches({"title": "CIO", "employer_name": "Нежелательная Компания"}, match) is True
    assert vacancy_matches({"title": "CIO", "description": "Нужны дежурства 24/7"}, match) is True
    assert vacancy_matches({"title": "CDTO", "employer_name": "Другой", "description": "Трансформация"}, match) is False


def test_approved_hard_rule_can_override_strategic_title_escape():
    from app.services.pipeline_scoring import hard_filter_reason

    rule = {
        "id": "r1",
        "version": 3,
        "name": "Не рассматривать конкретную компанию",
        "action": "hard_reject",
        "active": True,
        "match": {"title_any": [], "employer_any": ["acme"], "description_any": []},
        "instruction": "Не рассматривать вакансии Acme.",
    }
    reason = hard_filter_reason(
        {"title": "CIO / Digital Transformation", "employer_name": "ACME Group"},
        [rule],
    )
    assert reason == "approved_rule:r1:Не рассматривать конкретную компанию"


def test_unmatched_approved_rule_does_not_change_builtin_result():
    from app.services.pipeline_scoring import hard_filter_reason

    rule = {
        "id": "r1",
        "version": 1,
        "name": "Only Acme",
        "action": "hard_reject",
        "active": True,
        "match": {"title_any": [], "employer_any": ["acme"], "description_any": []},
        "instruction": "Не рассматривать Acme.",
    }
    assert hard_filter_reason({"title": "CDTO", "employer_name": "Other"}, [rule]) is None


@pytest.mark.asyncio
async def test_score_one_passes_only_matching_scoring_preferences_to_llm():
    from app.services import pipeline_scoring as svc

    vacancy = {
        "id": "p1",
        "hh_vacancy_id": "123",
        "title": "CIO",
        "employer_name": "Industrial Co",
        "description": "Основная задача — цифровая трансформация производства.",
        "sources": [],
    }
    matching = {
        "id": "r1",
        "version": 2,
        "name": "Производственная трансформация",
        "action": "scoring_preference",
        "active": True,
        "match": {"title_any": [], "employer_any": [], "description_any": ["цифровая трансформация"]},
        "instruction": "Повышать fit при реальном трансформационном мандате.",
    }
    unrelated = {
        "id": "r2",
        "version": 3,
        "name": "Retail",
        "action": "scoring_preference",
        "active": True,
        "match": {"title_any": [], "employer_any": ["retail"], "description_any": []},
        "instruction": "Снижать fit standalone retail.",
    }
    result = svc.StructuredVacancyScore.model_validate(
        {
            "components": {
                "role_fit": 20,
                "scale_fit": 20,
                "transformation_mandate": 22,
                "industry_business_context": 18,
            },
            "pros": [],
            "risks": [],
            "unknowns": [],
            "confidence": 80,
            "explanation": "fit",
        }
    )
    transitions = [True, True]
    with (
        patch.object(svc.vacancy_pipeline, "transition", side_effect=lambda **_: transitions.pop(0)) as transition,
        patch.object(
            svc.vacancy_review_service,
            "enrich",
            new=AsyncMock(return_value=(vacancy, {"archived": False, "already_responded": False})),
        ),
        patch.object(svc, "_score_with_llm", new=AsyncMock(return_value=result)) as llm_score,
    ):
        outcome = await svc.score_one(
            "u1",
            {"id": "p1"},
            context={"version": 1, "profile": {}, "facts": []},
            llm=object(),
            rules=[matching, unrelated],
        )

    assert outcome == "scored"
    assert llm_score.await_args.args[3] == [matching]
    details = transition.call_args_list[-1].kwargs["changes"]["score_details"]
    assert details["applied_rule_versions"] == [2]
    assert details["applied_rule_ids"] == ["r1"]
