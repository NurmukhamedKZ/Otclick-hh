import os

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from app.services import plan as plan_service


def test_has_access_ignores_legacy_plan_state():
    for profile in (
        {},
        {"plan": "free"},
        {"plan": "trial"},
        {"plan": "active", "plan_expires_at": "2000-01-01T00:00:00Z"},
        {"plan": "cancelled"},
    ):
        assert plan_service.has_access(profile) is True


def test_limits_are_always_unlimited_auto():
    assert plan_service.limits_for({"plan": "free"}) == {
        "mode": "auto",
        "daily": None,
        "total": None,
    }
    assert plan_service.limits_for({"plan": "active"}) == {
        "mode": "auto",
        "daily": None,
        "total": None,
    }


@pytest.mark.asyncio
async def test_check_access_does_not_read_plan_state():
    assert await plan_service.check_access("u1") is True


@pytest.mark.asyncio
async def test_get_limits_is_unlimited_for_every_user():
    assert await plan_service.get_limits("u1") == {
        "mode": "auto",
        "daily": None,
        "total": None,
    }


def test_legacy_filter_paid_no_longer_filters():
    assert plan_service.filter_paid([]) == []
    assert plan_service.filter_paid(["u1", "u2"]) == ["u1", "u2"]
