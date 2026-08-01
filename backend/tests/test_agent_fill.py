import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import MagicMock

import pytest

SNAPSHOT = [
    {"ref": "f1", "selector": "#name", "label": "Ваше имя", "field_type": "text", "required": True},
    {
        "ref": "f2",
        "selector": "#city",
        "label": "Город",
        "field_type": "select",
        "options": ["Алматы", "Астана"],
    },
]


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def test_snap_to_option_exact_and_case_insensitive():
    from app.ai.agent import snap_to_option

    assert snap_to_option("Алматы", ["Алматы", "Астана"]) == "Алматы"
    assert snap_to_option("  астана ", ["Алматы", "Астана"]) == "Астана"


def test_snap_to_option_returns_none_when_no_match():
    from app.ai.agent import snap_to_option

    assert snap_to_option("Караганда", ["Алматы", "Астана"]) is None


@pytest.mark.asyncio
async def test_fill_form_fields_without_llm_returns_empty():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = None
    assert await agent.fill_form_fields("ctx", "page", SNAPSHOT) == []


@pytest.mark.asyncio
async def test_fill_form_fields_maps_refs_and_snaps_options():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = MagicMock()
    agent.llm.with_structured_output.return_value.ainvoke = _async_return(
        {
            "fields": [
                {"ref": "f1", "value": "Иван Петров", "source": "profile"},
                {"ref": "f2", "value": "астана", "source": "ai"},
            ]
        }
    )
    out = await agent.fill_form_fields("ctx", "page", SNAPSHOT, known={"иван петров"})
    by_ref = {f["ref"]: f for f in out}
    assert by_ref["f1"]["value"] == "Иван Петров"
    assert by_ref["f1"]["source"] == "profile"
    assert by_ref["f2"]["value"] == "Астана"  # snapped to a real option
    assert by_ref["f1"]["field_type"] == "text"
    assert by_ref["f1"]["selector"] == "#name"


@pytest.mark.asyncio
async def test_fill_form_fields_demotes_unknown_profile_value():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = MagicMock()
    agent.llm.with_structured_output.return_value.ainvoke = _async_return(
        {"fields": [{"ref": "f1", "value": "Сергей Выдуманный", "source": "profile"}]}
    )
    out = await agent.fill_form_fields("ctx", "page", SNAPSHOT, known={"иван петров"})
    assert out[0]["source"] == "ai"


@pytest.mark.asyncio
async def test_fill_form_fields_drops_empty_and_unsnappable():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = MagicMock()
    agent.llm.with_structured_output.return_value.ainvoke = _async_return(
        {
            "fields": [
                {"ref": "f1", "value": "   ", "source": "ai"},
                {"ref": "f2", "value": "Караганда", "source": "ai"},
                {"ref": "нет-такого", "value": "x", "source": "ai"},
            ]
        }
    )
    assert await agent.fill_form_fields("ctx", "page", SNAPSHOT) == []


@pytest.mark.asyncio
async def test_fill_form_fields_survives_llm_error():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = MagicMock()

    async def boom(*a, **kw):
        raise RuntimeError("openai down")

    agent.llm.with_structured_output.return_value.ainvoke = boom
    assert await agent.fill_form_fields("ctx", "page", SNAPSHOT) == []
