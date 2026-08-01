import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


def _chain(final_data):
    c = MagicMock()
    for m in ("select", "eq", "in_", "is_"):
        getattr(c, m).return_value = c
    c.execute.return_value = SimpleNamespace(data=final_data)
    return c


@pytest.mark.asyncio
async def test_has_test_vacancy_is_queued_not_skipped():
    """Regression: has_test vacancies must reach the queue so apply_one fills
    the test (form_filler). Previously they were skipped → never filled."""
    from app.worker.queue import drop_user_queue, get_user_queue

    from app.services import vacancy_producer as vp

    drop_user_queue("u1")

    a_filter = {
        "id": "f1", "resume_id": "r1", "text": "AI engineer", "area": None,
        "experience": None, "work_format": None,
        "employment_form": None, "search_field": "name", "period": 30,
        "excluded_text": None,
    }
    filters_chain = _chain([a_filter])
    apps_chain = _chain([])       # nothing applied yet
    blacklist_chain = _chain([])  # nothing blacklisted

    def _table(name):
        return {
            "filters": filters_chain,
            "applications": apps_chain,
            "blacklist": blacklist_chain,
        }[name]

    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "items": [{"id": "v1", "has_test": True, "employer": {"id": "e1"}}],
        "found": 1,
    }

    with patch.object(vp.service_client, "table", side_effect=_table), \
         patch.object(vp, "load_api_client", new=AsyncMock(return_value=client)), \
         patch.object(vp, "persist_if_refreshed", new=AsyncMock()):
        pushed, skipped_has_test = await vp.produce_jobs("u1")

    assert pushed == 1
    assert skipped_has_test == 0
    queue = get_user_queue("u1")
    assert queue.qsize() == 1
    job = queue.get_nowait()
    assert job.vacancy_id == "v1"


def _filter_row(**over):
    base = {
        "id": "f1", "resume_id": "r1", "text": "AI engineer", "area": None,
        "experience": None, "work_format": None,
        "employment_form": None, "search_field": "name", "period": 30,
        "excluded_text": None,
        "ai_filter_enabled": True,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_relevance_drops_irrelevant():
    from app.worker.queue import drop_user_queue, get_user_queue

    from app.services import vacancy_producer as vp
    drop_user_queue("u1")

    filters_chain = _chain([_filter_row()])
    apps_chain = _chain([])
    blacklist_chain = _chain([])

    def _table(name):
        return {"filters": filters_chain, "applications": apps_chain,
                "blacklist": blacklist_chain}[name]

    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "items": [
            {"id": "v1", "name": "AI Engineer", "employer": {"id": "e1"}},
            {"id": "v2", "name": "Sales Manager", "employer": {"id": "e2"}},
        ],
        "found": 2,
    }

    agent = MagicMock()
    agent.filter_relevant_vacancies = AsyncMock(
        return_value={"v1": (True, ""), "v2": (False, "sales")}
    )

    with patch.object(vp.service_client, "table", side_effect=_table), \
         patch.object(vp.relevance, "get_cached_verdicts", return_value={}), \
         patch.object(vp.relevance, "store_verdicts"), \
         patch.object(vp, "load_api_client", new=AsyncMock(return_value=client)), \
         patch.object(vp, "persist_if_refreshed", new=AsyncMock()):
        pushed, _ = await vp.produce_jobs("u1", agent)

    assert pushed == 1
    queue = get_user_queue("u1")
    assert queue.qsize() == 1
    assert queue.get_nowait().vacancy_id == "v1"


@pytest.mark.asyncio
async def test_relevance_uses_cache_no_llm_call():
    from app.worker.queue import drop_user_queue, get_user_queue

    from app.services import vacancy_producer as vp
    drop_user_queue("u1")

    def _table(name):
        return {"filters": _chain([_filter_row()]), "applications": _chain([]),
                "blacklist": _chain([])}[name]

    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "items": [{"id": "v2", "name": "Sales Manager", "employer": {"id": "e2"}}],
        "found": 1,
    }

    agent = MagicMock()
    agent.filter_relevant_vacancies = AsyncMock(return_value={})

    with patch.object(vp.service_client, "table", side_effect=_table), \
         patch.object(vp.relevance, "get_cached_verdicts",
                      return_value={"v2": (False, "cached sales")}), \
         patch.object(vp.relevance, "store_verdicts"), \
         patch.object(vp, "load_api_client", new=AsyncMock(return_value=client)), \
         patch.object(vp, "persist_if_refreshed", new=AsyncMock()):
        pushed, _ = await vp.produce_jobs("u1", agent)

    assert pushed == 0
    agent.filter_relevant_vacancies.assert_not_awaited()  # fully served from cache
    assert get_user_queue("u1").qsize() == 0


@pytest.mark.asyncio
async def test_round_robin_interleaves_filters():
    """Two enabled filters must take turns — order is f1,f2,f1,f2,... — so a
    busy first filter can't starve the second out of the shared budget."""
    from app.worker.queue import drop_user_queue, get_user_queue

    from app.services import vacancy_producer as vp
    drop_user_queue("u1")

    f1 = _filter_row(id="f1", text="A", ai_filter_enabled=False)
    f2 = _filter_row(id="f2", text="B", ai_filter_enabled=False)

    def _table(name):
        return {"filters": _chain([f1, f2]), "applications": _chain([]),
                "blacklist": _chain([])}[name]

    def _get(path, params):
        if params.get("text") == "A":
            return {"items": [{"id": f"a{i}", "employer": {"id": f"ea{i}"}}
                              for i in range(3)], "found": 3}
        return {"items": [{"id": f"b{i}", "employer": {"id": f"eb{i}"}}
                          for i in range(3)], "found": 3}

    client = MagicMock()
    client.access_token = "tok"
    client.get.side_effect = _get

    with patch.object(vp.service_client, "table", side_effect=_table), \
         patch.object(vp, "load_api_client", new=AsyncMock(return_value=client)), \
         patch.object(vp, "persist_if_refreshed", new=AsyncMock()):
        pushed, _ = await vp.produce_jobs("u1")

    assert pushed == 6
    queue = get_user_queue("u1")
    order = [queue.get_nowait().vacancy_id for _ in range(6)]
    assert order == ["a0", "b0", "a1", "b1", "a2", "b2"]


@pytest.mark.asyncio
async def test_overlapping_filters_queue_each_vacancy_once():
    """Two filters over the same role (different region) return overlapping
    pages. Queuing the same vacancy twice burns a push slot for nothing —
    apply_one would just answer 'skipped' on the second copy."""
    from app.worker.queue import drop_user_queue, get_user_queue

    from app.services import vacancy_producer as vp
    drop_user_queue("u1")

    f1 = _filter_row(id="f1", text="A", ai_filter_enabled=False)
    f2 = _filter_row(id="f2", text="B", ai_filter_enabled=False)

    def _table(name):
        return {"filters": _chain([f1, f2]), "applications": _chain([]),
                "blacklist": _chain([])}[name]

    def _get(path, params):
        # both filters see v1; only the second also sees v2
        ids = ["v1"] if params.get("text") == "A" else ["v1", "v2"]
        return {"items": [{"id": i, "employer": {"id": f"e{i}"}} for i in ids],
                "found": len(ids)}

    client = MagicMock()
    client.access_token = "tok"
    client.get.side_effect = _get

    with patch.object(vp.service_client, "table", side_effect=_table), \
         patch.object(vp, "load_api_client", new=AsyncMock(return_value=client)), \
         patch.object(vp, "persist_if_refreshed", new=AsyncMock()):
        pushed, _ = await vp.produce_jobs("u1")

    assert pushed == 2
    queue = get_user_queue("u1")
    assert sorted(queue.get_nowait().vacancy_id for _ in range(2)) == ["v1", "v2"]


@pytest.mark.asyncio
async def test_ai_filter_disabled_bypasses_relevance():
    from app.worker.queue import drop_user_queue, get_user_queue

    from app.services import vacancy_producer as vp
    drop_user_queue("u1")

    def _table(name):
        return {"filters": _chain([_filter_row(ai_filter_enabled=False)]),
                "applications": _chain([]), "blacklist": _chain([])}[name]

    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "items": [{"id": "v2", "name": "Sales Manager", "employer": {"id": "e2"}}],
        "found": 1,
    }

    agent = MagicMock()
    agent.filter_relevant_vacancies = AsyncMock(return_value={})

    with patch.object(vp.service_client, "table", side_effect=_table), \
         patch.object(vp.relevance, "get_cached_verdicts", return_value={}), \
         patch.object(vp.relevance, "store_verdicts"), \
         patch.object(vp, "load_api_client", new=AsyncMock(return_value=client)), \
         patch.object(vp, "persist_if_refreshed", new=AsyncMock()):
        pushed, _ = await vp.produce_jobs("u1", agent)

    assert pushed == 1  # not filtered
    agent.filter_relevant_vacancies.assert_not_awaited()
    assert get_user_queue("u1").qsize() == 1
