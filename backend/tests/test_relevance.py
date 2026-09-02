import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

ITEMS = [
    {"id": "v1", "name": "AI Engineer", "snippet_requirement": "LLM, Python",
     "snippet_responsibility": "build models"},
    {"id": "v2", "name": "Sales Manager", "snippet_requirement": "продажи",
     "snippet_responsibility": "звонки клиентам"},
]


def _llm(verdict):
    chat = MagicMock()
    chat.with_structured_output.return_value.invoke.return_value = verdict
    return chat


def test_marks_listed_irrelevant_rest_relevant():
    from app.services.relevance import RelevanceVerdicts, filter_relevant
    verdict = RelevanceVerdicts.model_validate(
        {"irrelevant": [{"id": "v2", "reason": "sales, not AI"}], "uncertain": []}
    )
    verdicts, uncertain = filter_relevant(_llm(verdict), "AI engineer resume", ITEMS)
    assert verdicts["v1"][0] is True
    assert verdicts["v2"][0] is False
    assert verdicts["v2"][1] == "sales, not AI"
    assert uncertain == []


def test_uncertain_ids_returned():
    from app.services.relevance import RelevanceVerdicts, filter_relevant
    verdict = RelevanceVerdicts.model_validate(
        {"irrelevant": [{"id": "v2", "reason": "sales"}], "uncertain": [{"id": "v1"}]}
    )
    verdicts, uncertain = filter_relevant(_llm(verdict), "resume", ITEMS)
    assert uncertain == ["v1"]
    assert verdicts["v1"][0] is True  # still relevant until stage 2 says otherwise


def test_dict_output_is_accepted():
    from app.services.relevance import filter_relevant
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = {
        "irrelevant": [{"id": "v2", "reason": "sales"}], "uncertain": []
    }
    verdicts, uncertain = filter_relevant(llm, "resume", ITEMS)
    assert verdicts["v2"][0] is False
    assert uncertain == []


def test_empty_response_keeps_all():
    from app.services.relevance import RelevanceVerdicts, filter_relevant
    verdicts, _ = filter_relevant(_llm(RelevanceVerdicts()), "resume", ITEMS)
    assert all(v[0] for v in verdicts.values())


def test_malformed_output_fails_open():
    from app.services.relevance import filter_relevant
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.side_effect = ValueError("bad")
    verdicts, uncertain = filter_relevant(llm, "resume", ITEMS)
    assert all(v[0] for v in verdicts.values())
    assert verdicts["v1"][1] == "fail_open"
    assert uncertain == []


def test_no_llm_fails_open():
    from app.services.relevance import filter_relevant
    verdicts, uncertain = filter_relevant(None, "resume", ITEMS)
    assert all(v[0] for v in verdicts.values())
    assert uncertain == []


def test_empty_items_returns_empty():
    from app.services.relevance import filter_relevant
    assert filter_relevant(_llm(None), "resume", []) == ({}, [])


def test_criteria_reaches_prompt():
    from app.services.relevance import RelevanceVerdicts, filter_relevant
    llm = _llm(RelevanceVerdicts())
    filter_relevant(llm, "resume", ITEMS, criteria="только удалённо")
    prompt = llm.with_structured_output.return_value.invoke.call_args[0][0]
    assert "только удалённо" in prompt


def test_structured_rejected_falls_back_to_text_json():
    from types import SimpleNamespace as NS

    from app.services.relevance import filter_relevant
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.side_effect = RuntimeError(
        "response_format type is unavailable"
    )
    llm.invoke.return_value = NS(
        content='Вот ответ: {"irrelevant": [{"id": "v2", "reason": "продажи"}], "uncertain": []}'
    )
    verdicts, uncertain = filter_relevant(llm, "resume", ITEMS)
    assert verdicts["v2"][0] is False
    assert verdicts["v1"][0] is True
    assert uncertain == []


@pytest.mark.asyncio
async def test_recheck_uncertain_uses_full_description():
    from app.services.relevance import _RecheckVerdict, recheck_uncertain
    llm = MagicMock()
    verdict = _RecheckVerdict(irrelevant=True, reason="другая профессия")
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=verdict)
    item = {"id": "v1", "name": "AI Engineer"}
    with patch("app.hh.web.get_vacancy",
               new=AsyncMock(return_value={"description": "<p>full text</p>"})):
        out = await recheck_uncertain("u1", llm, "resume", [item])
    assert out["v1"] == (False, "другая профессия")
    prompt = llm.with_structured_output.return_value.ainvoke.call_args[0][0]
    assert "full text" in prompt  # html stripped, description included


@pytest.mark.asyncio
async def test_recheck_fetch_failure_keeps_vacancy():
    from app.services.relevance import recheck_uncertain
    llm = MagicMock()
    with patch("app.hh.web.get_vacancy",
               new=AsyncMock(side_effect=RuntimeError("blocked"))):
        out = await recheck_uncertain(
            "u1", llm, "resume", [{"id": "v1", "name": "AI Engineer"}]
        )
    assert out == {}


@pytest.mark.asyncio
async def test_recheck_caps_batch_and_no_llm():
    from app.services import relevance
    assert await relevance.recheck_uncertain("u1", None, "resume", [{"id": "v1"}]) == {}
    llm = MagicMock()
    with patch("app.hh.web.get_vacancy",
               new=AsyncMock(return_value={"description": "text"})) as gv:
        await relevance.recheck_uncertain(
            "u1", llm, "resume",
            [{"id": f"v{i}", "name": "x"} for i in range(15)],
        )
    assert gv.await_count == relevance.MAX_RECHECK_PER_PASS


def _cache_chain(final_data):
    c = MagicMock()
    for m in ("select", "eq", "in_", "upsert"):
        getattr(c, m).return_value = c
    c.execute.return_value = SimpleNamespace(data=final_data)
    return c


def test_get_cached_verdicts_maps_rows():
    from app.services import relevance
    rows = [
        {"vacancy_id": "v1", "relevant": True, "reason": ""},
        {"vacancy_id": "v2", "relevant": False, "reason": "sales"},
    ]
    chain = _cache_chain(rows)
    with patch.object(relevance.service_client, "table", return_value=chain):
        out = relevance.get_cached_verdicts("r1", ["v1", "v2"])
    assert out["v1"] == (True, "")
    assert out["v2"] == (False, "sales")


def test_get_cached_verdicts_empty_ids():
    from app.services import relevance
    assert relevance.get_cached_verdicts("r1", []) == {}


def test_store_verdicts_upserts_rows():
    from app.services import relevance
    chain = _cache_chain([])
    with patch.object(relevance.service_client, "table", return_value=chain):
        relevance.store_verdicts("u1", "r1", {"v2": (False, "sales")})
    chain.upsert.assert_called_once()
    rows = chain.upsert.call_args[0][0]
    assert rows[0]["vacancy_id"] == "v2"
    assert rows[0]["relevant"] is False
    assert rows[0]["resume_id"] == "r1"
    assert rows[0]["user_id"] == "u1"
