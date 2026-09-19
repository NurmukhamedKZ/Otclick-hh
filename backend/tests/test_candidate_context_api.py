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


def test_prepared_candidate_context_still_contains_exactly_22_active_facts():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "candidate" / "confirmed_facts.json"
    document = json.loads(path.read_text(encoding="utf-8"))

    assert len(document["facts"]) == 22
    assert all(str(fact.get("key") or "").strip() for fact in document["facts"])
    assert isinstance(document.get("guardrails"), list)
    assert document["guardrails"]
