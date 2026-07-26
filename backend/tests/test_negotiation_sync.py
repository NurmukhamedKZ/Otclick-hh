import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from app.services import negotiation_sync as ns  # noqa: E402


def test_rows_from_items_extracts_state_and_viewed():
    rows = ns._rows_from_items([
        {
            "state": {"id": "invitation"},
            "viewed_by_opponent": True,
            "vacancy": {"id": 111, "employer": {"name": "Acme"}},
        },
        {"state": {"id": "discard"}, "vacancy": {}},  # no vacancy id → dropped
    ])
    assert rows == [
        {"vacancy_id": "111", "state": "invitation", "viewed": True, "employer_name": "Acme"}
    ]


def _select_chain(data):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.execute.return_value = SimpleNamespace(data=data)
    return chain


def test_persist_updates_only_changed_rows():
    select = _select_chain([
        {"vacancy_id": "1", "hh_state": "response", "hh_viewed": False, "employer_name": None},
        {"vacancy_id": "2", "hh_state": "invitation", "hh_viewed": True, "employer_name": "B"},
    ])
    update = MagicMock()
    update.update.return_value = update
    update.eq.return_value = update

    calls = {"n": 0}

    def table(_name):
        # first call in _persist is the select, all later ones are updates
        calls["n"] += 1
        return select if calls["n"] == 1 else update

    rows = [
        {"vacancy_id": "1", "state": "invitation", "viewed": True, "employer_name": "A"},
        {"vacancy_id": "2", "state": "invitation", "viewed": True, "employer_name": "B"},
        {"vacancy_id": "3", "state": "invitation", "viewed": True, "employer_name": "C"},
    ]
    with patch.object(ns.service_client, "table", side_effect=table):
        changed = ns._persist("u1", rows)

    # 1 changed; 2 unchanged; 3 has no application row (never applied by us)
    assert changed == 1
    patch_arg = update.update.call_args[0][0]
    assert patch_arg["hh_state"] == "invitation"
    assert patch_arg["hh_viewed"] is True
    assert patch_arg["employer_name"] == "A"
    assert "hh_state_at" in patch_arg


@pytest.mark.asyncio
async def test_sync_states_skips_when_not_due():
    with patch.object(ns, "_due", return_value=False), patch.object(
        ns, "load_api_client"
    ) as load:
        assert await ns.sync_states("u1") == 0
    load.assert_not_called()


@pytest.mark.asyncio
async def test_sync_states_survives_dead_creds():
    with patch.object(ns, "_due", return_value=True), patch.object(
        ns, "load_api_client", side_effect=RuntimeError("no creds")
    ):
        assert await ns.sync_states("u1") == 0


@pytest.mark.asyncio
async def test_sync_states_pages_and_marks_synced():
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "items": [
            {"state": {"id": "invitation"}, "viewed_by_opponent": True, "vacancy": {"id": 9}}
        ],
        "pages": 1,
    }
    with patch.object(ns, "_due", return_value=True), patch.object(
        ns, "load_api_client", return_value=client
    ), patch.object(ns, "_persist", return_value=1) as persist, patch.object(
        ns, "_mark_synced"
    ) as mark, patch.object(ns, "persist_if_refreshed"):
        changed = await ns.sync_states("u1")

    assert changed == 1
    assert client.get.call_count == 1
    persist.assert_called_once()
    mark.assert_called_once_with("u1")
