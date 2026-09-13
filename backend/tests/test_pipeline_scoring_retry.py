from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_transient_hh_failure_requeues_vacancy_instead_of_score_error():
    from app.hh import web
    from app.services import pipeline_scoring as svc

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
            new=AsyncMock(side_effect=web.HHTransientError("HH temporarily unavailable")),
        ),
    ):
        outcome = await svc.score_one(
            "u1",
            {"id": "p1", "score_attempts": 0},
            context={"version": 1, "profile": {}, "facts": []},
            llm=object(),
        )

    assert outcome == "retryable"
    final = transition.call_args_list[-1].kwargs
    assert final["from_statuses"] == ["scoring"]
    assert final["to_status"] == "discovered"
    assert final["changes"]["score_attempts"] == 1
    assert final["changes"]["next_score_at"] is not None
    assert final["changes"]["score_details"]["transient_hh"] is True


@pytest.mark.asyncio
async def test_third_independent_transient_hh_failure_becomes_terminal_score_error():
    from app.hh import web
    from app.services import pipeline_scoring as svc

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
            new=AsyncMock(side_effect=web.HHTransientError("HH still unavailable")),
        ),
    ):
        outcome = await svc.score_one(
            "u1",
            {"id": "p1", "score_attempts": 2},
            context={"version": 1, "profile": {}, "facts": []},
            llm=object(),
        )

    assert outcome == "transient_error"
    final = transition.call_args_list[-1].kwargs
    assert final["to_status"] == "score_error"
    assert final["changes"]["score_attempts"] == 3
    assert final["changes"]["score_details"]["exhausted"] is True


@pytest.mark.asyncio
async def test_scoring_batch_opens_circuit_after_two_consecutive_hh_failures():
    from app.services import pipeline_scoring as svc

    rows = [
        {"id": f"p{i}", "score_attempts": 0}
        for i in range(5)
    ]
    fake_agent = MagicMock()
    fake_agent.llm = object()

    with (
        patch.object(svc, "_load_discovered", return_value=rows),
        patch.object(
            svc.candidate_context_service,
            "load_candidate_context",
            new=AsyncMock(return_value={"version": 1, "profile": {}, "facts": []}),
        ),
        patch.object(
            svc.selection_rules,
            "load_active_rules",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(svc, "HHAgent", return_value=fake_agent),
        patch.object(
            svc,
            "score_one",
            new=AsyncMock(side_effect=["retryable", "retryable"]),
        ) as score_one,
    ):
        summary = await svc.score_user("u1")

    assert score_one.await_count == 2
    assert summary["retryable_errors"] == 2
    assert summary["circuit_breaker"] == 1
    assert summary["errors"] == 0
