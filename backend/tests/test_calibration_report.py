from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_calibration_report_uses_only_fresh_scores_in_aggregates():
    from app.services import calibration_report

    rows = [
        {
            "id": "p1",
            "hh_vacancy_id": "101",
            "title": "CIO",
            "employer_name": "A",
            "status": "selected",
            "score": 82,
            "score_stale": False,
            "user_decision_reason": None,
            "discovered_at": "2026-09-01T10:00:00Z",
        },
        {
            "id": "p2",
            "hh_vacancy_id": "102",
            "title": "IT Director",
            "employer_name": "B",
            "status": "rejected_by_user",
            "score": 55,
            "score_stale": False,
            "user_decision_reason": "слишком операционная роль",
            "discovered_at": "2026-09-02T10:00:00Z",
        },
        {
            "id": "p3",
            "hh_vacancy_id": "103",
            "title": "CTO",
            "employer_name": "C",
            "status": "approved",
            "score": 91,
            "score_stale": True,
            "user_decision_reason": None,
            "discovered_at": "2026-09-03T10:00:00Z",
        },
    ]

    with patch.object(
        calibration_report.vacancy_review_service,
        "list_vacancies",
        new=AsyncMock(return_value=rows),
    ) as list_vacancies:
        report = await calibration_report.build_report("u1")

    list_vacancies.assert_awaited_once()
    assert report["reviewed"] == 3
    assert report["positive"] == 2
    assert report["rejected"] == 1
    assert report["with_score"] == 3
    assert report["stale_scores"] == 1
    assert report["fresh_scored_decisions"] == 2
    assert report["average_positive_score"] == 82.0
    assert report["average_rejected_score"] == 55.0

    bands = {item["label"]: item for item in report["bands"]}
    assert bands["40–59"]["rejected"] == 1
    assert bands["80–100"]["positive"] == 1
    assert bands["80–100"]["total"] == 1
    assert report["decisions"][2]["score_stale"] is True


@pytest.mark.asyncio
async def test_calibration_api_returns_schema():
    from app.api import vacancies as api

    payload = {
        "reviewed": 1,
        "positive": 1,
        "rejected": 0,
        "with_score": 1,
        "stale_scores": 0,
        "fresh_scored_decisions": 1,
        "average_positive_score": 88.0,
        "average_rejected_score": None,
        "bands": [
            {
                "label": "80–100",
                "min_score": 80,
                "max_score": 100,
                "positive": 1,
                "rejected": 0,
                "total": 1,
            }
        ],
        "decisions": [
            {
                "pipeline_id": "p1",
                "hh_vacancy_id": "101",
                "title": "CIO",
                "employer_name": "A",
                "lifecycle_status": "selected",
                "decision": "positive",
                "score": 88,
                "score_stale": False,
                "user_decision_reason": None,
                "discovered_at": "2026-09-01T10:00:00Z",
            }
        ],
    }

    with patch.object(
        api.calibration_report,
        "build_report",
        new=AsyncMock(return_value=payload),
    ) as build:
        result = await api.calibration(user_id="u1")

    build.assert_awaited_once_with("u1")
    assert result.reviewed == 1
    assert result.bands[0].positive == 1
    assert result.decisions[0].score == 88
