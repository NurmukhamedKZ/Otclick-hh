import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import AsyncMock, patch

import pytest

RESUME = {
    "title": "Python-разработчик",
    "first_name": "Иван",
    "last_name": "Петров",
    "area": {"name": "Алматы"},
    "citizenship": [{"name": "Казахстан"}],
    "skill_set": ["Python", "FastAPI"],
    "contact": [
        {"type": {"id": "email"}, "value": "ivan@example.com"},
        {"type": {"id": "cell"}, "value": {"formatted": "+7 777 111 22 33"}},
    ],
}


def test_facts_extracts_contacts_and_name():
    from app.services.candidate_context import facts

    f = facts(RESUME)
    assert f["full_name"] == "Иван Петров"
    assert f["first_name"] == "Иван"
    assert f["email"] == "ivan@example.com"
    assert f["phone"] == "+7 777 111 22 33"
    assert f["city"] == "Алматы"
    assert f["title"] == "Python-разработчик"


def test_facts_drops_empty_values():
    from app.services.candidate_context import facts

    f = facts({"title": "", "first_name": "Иван"})
    assert "title" not in f
    assert f["first_name"] == "Иван"


def test_known_values_is_normalized():
    from app.services.candidate_context import facts, known_values

    kv = known_values(facts(RESUME))
    assert "ivan@example.com" in kv
    assert "иван петров" in kv


@pytest.mark.asyncio
async def test_build_joins_summary_and_qa():
    from app.services import candidate_context

    with (
        patch.object(candidate_context, "load_resume", new=AsyncMock(return_value=RESUME)),
        patch.object(
            candidate_context.qa_memory,
            "prompt_block",
            new=AsyncMock(return_value="- В: Опыт?\n  О: 5 лет"),
        ),
    ):
        text, f = await candidate_context.build("u1")
    assert "Python-разработчик" in text
    assert "5 лет" in text
    assert f["email"] == "ivan@example.com"


@pytest.mark.asyncio
async def test_build_survives_resume_failure():
    from app.services import candidate_context

    with patch.object(
        candidate_context, "load_resume", new=AsyncMock(side_effect=RuntimeError("hh down"))
    ):
        text, f = await candidate_context.build("u1")
    assert text == ""
    assert f == {}
