import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import requests

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


def _fake_client():
    client = MagicMock()
    client.access_token = "USERold"
    client.refresh_access_token = MagicMock()
    return client


async def test_refresh_user_success_persists():
    from app.services import token_refresh as tr

    client = _fake_client()
    with (
        patch.object(tr, "load_api_client", AsyncMock(return_value=client)),
        patch.object(tr, "persist_if_refreshed", AsyncMock()) as persist,
        patch.object(tr, "mark_invalid", AsyncMock()) as mark,
    ):
        result = await tr.refresh_user("u1")

    client.refresh_access_token.assert_called_once()
    persist.assert_awaited_once()
    mark.assert_not_awaited()
    assert result == {"user_id": "u1", "status": "refreshed"}


async def test_refresh_user_hh_rejection_marks_invalid():
    from app.hh import errors
    from app.services import token_refresh as tr

    client = _fake_client()
    client.refresh_access_token.side_effect = errors.BadResponse("token revoked")
    with (
        patch.object(tr, "load_api_client", AsyncMock(return_value=client)),
        patch.object(tr, "persist_if_refreshed", AsyncMock()) as persist,
        patch.object(tr, "mark_invalid", AsyncMock()) as mark,
    ):
        result = await tr.refresh_user("u1")

    mark.assert_awaited_once()
    assert mark.await_args.args[0] == "u1"
    persist.assert_not_awaited()
    assert result["status"] == "invalid"


async def test_refresh_user_transient_does_not_mark_invalid():
    from app.services import token_refresh as tr

    client = _fake_client()
    client.refresh_access_token.side_effect = requests.ConnectionError("boom")
    with (
        patch.object(tr, "load_api_client", AsyncMock(return_value=client)),
        patch.object(tr, "persist_if_refreshed", AsyncMock()) as persist,
        patch.object(tr, "mark_invalid", AsyncMock()) as mark,
    ):
        result = await tr.refresh_user("u1")

    mark.assert_not_awaited()
    persist.assert_not_awaited()
    assert result["status"] == "error"


async def test_refresh_due_selects_near_expiry_and_aggregates():
    from app.services import token_refresh as tr

    chain = MagicMock()
    chain.select.return_value = chain
    chain.is_.return_value = chain
    chain.not_.is_.return_value = chain
    chain.lte.return_value = chain
    chain.execute.return_value = SimpleNamespace(
        data=[{"user_id": "u1"}, {"user_id": "u2"}, {"user_id": "u3"}]
    )
    sb = MagicMock()
    sb.table.return_value = chain

    async def fake_refresh(uid):
        return {
            "u1": {"user_id": "u1", "status": "refreshed"},
            "u2": {"user_id": "u2", "status": "invalid", "error": "x"},
            "u3": {"user_id": "u3", "status": "error", "error": "net"},
        }[uid]

    with (
        patch.object(tr, "service_client", sb),
        patch.object(tr, "refresh_user", side_effect=fake_refresh),
    ):
        summary = await tr.refresh_due(threshold_days=2)

    # near-expiry filters applied
    chain.is_.assert_called_once_with("invalid_at", None)
    assert chain.lte.call_args.args[0] == "expires_at"
    # cookies-only rows have no refresh token; "refreshing" them would fail and
    # mark a working web session invalid
    chain.not_.is_.assert_called_once_with("refresh_token_encrypted", None)
    assert summary == {"due": 3, "refreshed": 1, "invalid": 1, "errors": 1}


async def test_refresh_due_one_bad_user_does_not_abort_batch():
    from app.services import token_refresh as tr
    from app.services.hh_credentials import HHCredentialsInvalid

    chain = MagicMock()
    chain.select.return_value = chain
    chain.is_.return_value = chain
    chain.not_.is_.return_value = chain
    chain.lte.return_value = chain
    chain.execute.return_value = SimpleNamespace(
        data=[{"user_id": "u1"}, {"user_id": "u2"}]
    )
    sb = MagicMock()
    sb.table.return_value = chain

    async def fake_refresh(uid):
        if uid == "u1":
            raise HHCredentialsInvalid("u1", "already dead")
        return {"user_id": "u2", "status": "refreshed"}

    with (
        patch.object(tr, "service_client", sb),
        patch.object(tr, "refresh_user", side_effect=fake_refresh),
    ):
        summary = await tr.refresh_due()

    assert summary == {"due": 2, "refreshed": 1, "invalid": 1, "errors": 0}
