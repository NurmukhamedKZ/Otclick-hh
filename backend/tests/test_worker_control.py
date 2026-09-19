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
    for m in ("select", "update", "eq", "in_", "is_", "maybe_single"):
        getattr(c, m).return_value = c
    c.execute.return_value = SimpleNamespace(data=final_data)
    return c


@pytest.mark.asyncio
async def test_set_enabled_updates_flag():
    from app.services import worker_control

    chain = _chain(None)
    with patch.object(worker_control.service_client, "table", return_value=chain):
        await worker_control.set_enabled("u1", True)
    chain.update.assert_called_once_with({"worker_enabled": True})
    chain.eq.assert_called_once_with("id", "u1")


@pytest.mark.asyncio
async def test_is_enabled_reads_flag():
    from app.services import worker_control

    chain = _chain({"worker_enabled": True})
    with patch.object(worker_control.service_client, "table", return_value=chain):
        assert await worker_control.is_enabled("u1") is True

    chain = _chain(None)
    with patch.object(worker_control.service_client, "table", return_value=chain):
        assert await worker_control.is_enabled("u1") is False


@pytest.mark.asyncio
async def test_set_agent_enabled_updates_flag():
    from app.services import worker_control

    chain = _chain(None)
    with patch.object(worker_control.service_client, "table", return_value=chain):
        await worker_control.set_agent_enabled("u1", True)
    chain.update.assert_called_once_with({"agent_enabled": True})
    chain.eq.assert_called_once_with("id", "u1")


@pytest.mark.asyncio
async def test_is_agent_enabled_reads_flag():
    from app.services import worker_control

    chain = _chain({"agent_enabled": True})
    with patch.object(worker_control.service_client, "table", return_value=chain):
        assert await worker_control.is_agent_enabled("u1") is True

    chain = _chain({"agent_enabled": False})
    with patch.object(worker_control.service_client, "table", return_value=chain):
        assert await worker_control.is_agent_enabled("u1") is False


def test_active_user_flags_maps_both_flags():
    from app.services import worker_control

    creds = _chain([{"user_id": "a"}, {"user_id": "b"}, {"user_id": "c"}])
    profiles = _chain(
        [
            {"id": "a", "worker_enabled": True, "agent_enabled": False},
            {"id": "b", "worker_enabled": False, "agent_enabled": True},
            {"id": "c", "worker_enabled": False, "agent_enabled": False},
        ]
    )

    def _table(name):
        return creds if name == "hh_credentials" else profiles

    with patch.object(worker_control.service_client, "table", side_effect=_table):
        out = worker_control.active_user_flags()
    assert out == {"a": (True, False), "b": (False, True)}


def test_active_user_flags_empty_when_no_active_creds():
    from app.services import worker_control

    creds = _chain([])
    with patch.object(worker_control.service_client, "table", return_value=creds):
        assert worker_control.active_user_flags() == {}


@pytest.mark.asyncio
async def test_reconcile_drives_discovery_and_agent_without_plan_gate():
    import worker_main

    registry = MagicMock()
    registry.active_user_ids.return_value = ["b", "c"]
    registry.reconcile = AsyncMock()

    flags = {"a": (True, False), "b": (False, True)}
    with (
        patch.object(worker_main, "active_user_flags", return_value=flags),
        patch.object(worker_main, "_run_manual_search_job", new=AsyncMock(return_value=None)),
        patch.object(worker_main, "_run_discovery_if_due", new=AsyncMock()) as discovery,
    ):
        await worker_main._reconcile(registry)

    calls = {c.args[0]: c.args[1:] for c in registry.reconcile.await_args_list}
    assert calls["a"] == (False, False)
    assert calls["b"] == (False, True)
    assert calls["c"] == (False, False)
    discovery.assert_any_await("a", True)
    discovery.assert_any_await("b", False)


@pytest.mark.asyncio
async def test_agent_flag_is_honoured_for_every_user():
    import worker_main

    registry = MagicMock()
    registry.active_user_ids.return_value = []
    registry.reconcile = AsyncMock()

    flags = {"a": (True, True)}
    with (
        patch.object(worker_main, "active_user_flags", return_value=flags),
        patch.object(worker_main, "_run_manual_search_job", new=AsyncMock(return_value=None)),
        patch.object(worker_main, "_run_discovery_if_due", new=AsyncMock()) as discovery,
    ):
        await worker_main._reconcile(registry)

    registry.reconcile.assert_awaited_once_with("a", False, True)
    discovery.assert_awaited_once_with("a", True)
