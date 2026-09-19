from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_refresh_is_noop_for_cookies_only_connection():
    from app.api import auth as api

    with (
        patch.object(
            api.hh_auth,
            "get_credentials_status",
            return_value={
                "connected": True,
                "has_api_token": False,
                "expires_at": None,
                "last_refreshed_at": "2026-09-07T00:00:00+00:00",
                "hh_user_id": None,
            },
        ),
        patch.object(api.token_refresh, "refresh_user", new=AsyncMock()) as refresh_user,
    ):
        result = await api.refresh(user_id="u1")

    assert result.status == "not_applicable"
    refresh_user.assert_not_awaited()


def test_status_schema_preserves_optional_api_token_flag():
    from app.schemas.auth import HHStatusResponse

    status = HHStatusResponse(
        connected=True,
        has_api_token=False,
        expires_at=None,
        last_refreshed_at=None,
        hh_user_id=None,
    )

    assert status.connected is True
    assert status.has_api_token is False


def test_hh_service_treats_web_cookies_as_connection_without_api_token():
    from app.services import hh_auth

    class Result:
        data = {
            "expires_at": None,
            "last_refreshed_at": "2026-09-07T00:00:00+00:00",
            "hh_user_id": None,
            "invalid_at": None,
            "web_cookies_encrypted": "encrypted-cookie-json",
        }

    query = type("Query", (), {})()
    query.select = lambda *args, **kwargs: query
    query.eq = lambda *args, **kwargs: query
    query.maybe_single = lambda *args, **kwargs: query
    query.execute = lambda: Result()

    with patch.object(hh_auth.service_client, "table", return_value=query):
        result = hh_auth.get_credentials_status("u1")

    assert result["connected"] is True
    assert result["has_api_token"] is False
