import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

ITEMS = [
    {"id": "v1", "name": "AI Engineer", "snippet_requirement": "", "snippet_responsibility": ""},
    {"id": "v2", "name": "Sales Manager", "snippet_requirement": "", "snippet_responsibility": ""},
]


@pytest.mark.asyncio
async def test_filter_relevant_vacancies_grounds_and_classifies():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    agent.llm = MagicMock()  # ensure non-None even without API key
    with patch("app.services.form_filler.load_resume",
               new=AsyncMock(return_value={"title": "AI Engineer"})), \
         patch("app.services.form_filler._resume_summary",
               return_value="AI engineer resume"), \
         patch("app.ai.agent.filter_relevant",
               return_value=({"v1": (True, ""), "v2": (False, "sales")}, [])) as fr:
        out = await agent.filter_relevant_vacancies("r1", ITEMS)
    assert out["v2"][0] is False
    # grounded in the loaded summary
    assert fr.call_args[0][1] == "AI engineer resume"


@pytest.mark.asyncio
async def test_filter_relevant_vacancies_caches_summary_per_resume():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    agent.llm = MagicMock()
    load = AsyncMock(return_value={"title": "AI Engineer"})
    with patch("app.services.form_filler.load_resume", new=load), \
         patch("app.services.form_filler._resume_summary", return_value="sum"), \
         patch("app.ai.agent.filter_relevant", return_value=({}, [])):
        await agent.filter_relevant_vacancies("r1", ITEMS)
        await agent.filter_relevant_vacancies("r1", ITEMS)
    assert load.await_count == 1  # second call uses cached summary
