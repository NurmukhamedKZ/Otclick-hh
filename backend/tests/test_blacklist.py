import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


def _fluent(final_data):
    chain = MagicMock()
    for m in ("select", "insert", "update", "upsert", "delete", "eq", "in_", "order"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = SimpleNamespace(data=final_data)
    return chain


@pytest.mark.asyncio
async def test_list_blacklist():
    from app.services import blacklist

    rows = [{"id": "1", "employer_id": "e1", "employer_name": "Acme", "reason": "manual"}]
    chain = _fluent(rows)
    with patch.object(blacklist.service_client, "table", return_value=chain):
        out = await blacklist.list_blacklist("u1")
    assert out == rows
    chain.eq.assert_any_call("user_id", "u1")


@pytest.mark.asyncio
async def test_add_blacklist_upserts_on_conflict():
    from app.services import blacklist

    chain = _fluent([{"id": "1", "employer_id": "e1", "reason": "manual"}])
    with patch.object(blacklist.service_client, "table", return_value=chain):
        out = await blacklist.add_blacklist("u1", "e1", "Acme")
    assert out["employer_id"] == "e1"
    _, kwargs = chain.upsert.call_args
    assert kwargs["on_conflict"] == "user_id,employer_id"


@pytest.mark.asyncio
async def test_remove_blacklist_missing_raises_404():
    from app.services import blacklist

    chain = _fluent([])  # delete returns no rows → not found
    with patch.object(blacklist.service_client, "table", return_value=chain):
        with pytest.raises(HTTPException) as ei:
            await blacklist.remove_blacklist("u1", "missing")
    assert ei.value.status_code == 404


def test_bulk_auto_blacklist_skips_empty():
    from app.services import blacklist

    chain = _fluent([])
    with patch.object(blacklist.service_client, "table", return_value=chain) as t:
        blacklist.bulk_auto_blacklist("u1", {})
    t.assert_not_called()


def test_bulk_auto_blacklist_upserts_rows():
    from app.services import blacklist

    chain = _fluent([])
    with patch.object(blacklist.service_client, "table", return_value=chain):
        blacklist.bulk_auto_blacklist("u1", {"e1": "Acme", "e2": None})
    rows, kwargs = chain.upsert.call_args[0][0], chain.upsert.call_args[1]
    assert {r["employer_id"] for r in rows} == {"e1", "e2"}
    assert all(r["reason"] == "auto_already_applied" for r in rows)
    assert kwargs["on_conflict"] == "user_id,employer_id"


@pytest.mark.asyncio
async def test_producer_skips_relations_and_blacklists_employer():
    from app.services import vacancy_producer as vp

    items = [
        {"id": "100", "employer": {"id": "e1", "name": "Acme"}, "relations": ["got_response"]},
        {"id": "101", "employer": {"id": "e2", "name": "Beta"}},  # clean → pushed
    ]

    filters = [{"id": "f1", "resume_id": "r1", "text": "py"}]

    queue = MagicMock()

    async def _put(job):
        return None

    queue.put.side_effect = _put
    queue.qsize.return_value = 1

    captured = {}

    def _bulk(user_id, entries, reason="auto_already_applied"):
        captured["entries"] = entries

    with patch.object(vp, "_load_enabled_filters", return_value=filters), \
         patch.object(vp.web, "search_vacancies", new=AsyncMock(return_value=(items, 2))), \
         patch.object(vp, "_existing_vacancy_ids", return_value=set()), \
         patch.object(vp, "_blacklisted_employer_ids", return_value=set()), \
         patch.object(vp, "get_user_queue", return_value=queue), \
         patch.object(vp, "bulk_auto_blacklist", side_effect=_bulk):
        pushed, _ = await vp.produce_jobs("u1")

    assert pushed == 1  # only the clean vacancy
    job = queue.put.call_args[0][0]
    assert job.vacancy_id == "101"
    assert captured["entries"] == {"e1": "Acme"}
