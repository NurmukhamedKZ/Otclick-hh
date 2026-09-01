import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


@pytest.mark.asyncio
async def test_suggest_filters_whitelists_and_caps():
    from app.ai.agent import _FilterSuggestion, _FilterSuggestions
    plan = _FilterSuggestions(filters=[
        _FilterSuggestion(
            name="Широкий", text="Data Scientist", area=113,
            experience="between1And3", work_format="REMOTE",
            employment_form="FULL", period=14, excluded_text="преподаватель",
        ),
        # hallucinated literals → degrade to None
        _FilterSuggestion(name="Мусор", text="DS", area=999, experience="wizard",
                          work_format="MARS", period=999),
        _FilterSuggestion(name="Пустой", text=""),  # dropped: no text
        _FilterSuggestion(name="Четвёртый", text="Analytics"),  # dropped: cap 3
    ])
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    agent.llm = MagicMock()
    with patch("app.services.form_filler.load_resume",
               new=AsyncMock(return_value={"title": "AI Engineer"})), \
         patch("app.services.form_filler._resume_summary", return_value="sum"), \
         patch.object(agent.llm, "with_structured_output") as wso:
        wso.return_value.ainvoke = AsyncMock(return_value=plan)
        out = await agent.suggest_filters("r1")
    assert len(out) == 2
    assert out[0]["text"] == "Data Scientist"
    assert out[0]["area"] == 113
    assert out[0]["experience"] == "between1And3"
    assert out[0]["work_format"] == "REMOTE"
    assert out[0]["employment_form"] == "FULL"
    assert out[0]["period"] == 14
    assert out[0]["excluded_text"] == "преподаватель"
    assert out[0]["search_field"] == "name"
    assert out[1]["area"] is None
    assert out[1]["experience"] is None
    assert out[1]["work_format"] is None
    assert out[1]["period"] is None


@pytest.mark.asyncio
async def test_suggest_filters_no_llm_returns_empty():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    agent.llm = None
    assert await agent.suggest_filters("r1") == []


@pytest.mark.asyncio
async def test_suggest_filters_llm_failure_returns_empty():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    agent.llm = MagicMock()
    with patch.object(agent.llm, "with_structured_output") as wso:
        wso.return_value.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        assert await agent.suggest_filters("r1") == []


@pytest.mark.asyncio
async def test_suggest_filters_falls_back_to_text_json():
    from types import SimpleNamespace as NS

    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    agent.llm = MagicMock()
    payload = (
        '{"filters": [{"name": "Узкий", "text": "Data Scientist", "area": 40,'
        ' "experience": null, "work_format": null, "employment_form": null,'
        ' "period": null, "excluded_text": null}]}'
    )
    with patch("app.services.form_filler.load_resume",
               new=AsyncMock(return_value={"title": "AI Engineer"})), \
         patch("app.services.form_filler._resume_summary", return_value="sum"), \
         patch.object(agent.llm, "with_structured_output") as wso, \
         patch.object(agent.llm, "ainvoke",
                      new=AsyncMock(return_value=NS(content=f"Ответ: {payload}"))):
        wso.return_value.ainvoke = AsyncMock(side_effect=RuntimeError("400 response_format"))
        out = await agent.suggest_filters("r1")
    assert len(out) == 1
    assert out[0]["text"] == "Data Scientist"
    assert out[0]["area"] == 40
