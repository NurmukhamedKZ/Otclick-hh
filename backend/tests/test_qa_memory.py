import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


ORIGINAL = [
    {"task_id": 1, "question": "Желаемый доход?", "answer": "200 000"},
    {"task_id": 2, "question": "Готов к переезду?", "answer": "Да"},
]


@pytest.mark.asyncio
async def test_save_edited_persists_only_changed_answers():
    from app.services import qa_memory

    final = [
        {"task_id": 1, "question": "Желаемый доход?", "answer": "350 000"},  # edited
        {"task_id": 2, "question": "Готов к переезду?", "answer": "Да"},     # untouched
    ]
    with patch.object(qa_memory, "upsert", new=AsyncMock()) as up:
        saved = await qa_memory.save_edited("u1", ORIGINAL, final, vacancy_id="v9")

    assert saved == 1
    up.assert_awaited_once_with(
        "u1", "Желаемый доход?", "350 000", source="form", vacancy_id="v9"
    )


@pytest.mark.asyncio
async def test_save_edited_skips_empty_and_unchanged():
    from app.services import qa_memory

    final = [
        {"task_id": 1, "question": "Желаемый доход?", "answer": "  200 000 "},  # same
        {"task_id": 2, "question": "Готов к переезду?", "answer": ""},          # empty
    ]
    with patch.object(qa_memory, "upsert", new=AsyncMock()) as up:
        assert await qa_memory.save_edited("u1", ORIGINAL, final) == 0
    up.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_edited_survives_upsert_failure():
    from app.services import qa_memory

    final = [{"task_id": 1, "question": "Желаемый доход?", "answer": "350 000"}]
    with patch.object(qa_memory, "upsert", new=AsyncMock(side_effect=RuntimeError("db"))):
        assert await qa_memory.save_edited("u1", ORIGINAL, final) == 0


def test_render_block_empty_and_populated():
    from app.services import qa_memory

    assert qa_memory.render_block([]) == ""
    block = qa_memory.render_block([{"question": "Доход?", "answer": "350 000"}])
    assert "В: Доход?" in block and "О: 350 000" in block


@pytest.mark.asyncio
async def test_save_confirmed_answers_persists_all_pairs():
    from app.services import qa_memory

    pairs = [
        {"question": "Доход?", "answer": "300 000"},
        {"question": "Переезд?", "answer": "Да"},
    ]
    with patch.object(qa_memory, "upsert", new=AsyncMock()) as up:
        saved = await qa_memory.save_confirmed_answers("u1", pairs, source="form", vacancy_id="v1")
    assert saved == 2
    assert up.await_count == 2


@pytest.mark.asyncio
async def test_save_confirmed_answers_skips_empty():
    from app.services import qa_memory

    pairs = [
        {"question": "Доход?", "answer": "300 000"},
        {"question": "", "answer": "Да"},
        {"question": "Переезд?", "answer": ""},
    ]
    with patch.object(qa_memory, "upsert", new=AsyncMock()) as up:
        saved = await qa_memory.save_confirmed_answers("u1", pairs, source="chat")
    assert saved == 1
    assert up.await_count == 1


@pytest.mark.asyncio
async def test_save_confirmed_answers_survives_failure():
    from app.services import qa_memory

    pairs = [{"question": "Доход?", "answer": "300 000"}]
    with patch.object(qa_memory, "upsert", new=AsyncMock(side_effect=RuntimeError("db"))):
        assert await qa_memory.save_confirmed_answers("u1", pairs, source="form") == 0
