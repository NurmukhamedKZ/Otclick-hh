import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from app.services import plan as plan_service


def _iso(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


@pytest.fixture
def billing_on():
    """Prod shape. The default is BILLING_ENABLED=False (self-host)."""
    with patch.object(plan_service.settings, "BILLING_ENABLED", True):
        yield


# ─── is_paid / has_access ────────────────────────────────────

def test_active_within_period(billing_on):
    assert plan_service.has_access({"plan": "active", "plan_expires_at": _iso(10)}) is True


def test_active_expired(billing_on):
    assert plan_service.has_access({"plan": "active", "plan_expires_at": _iso(-1)}) is False


def test_cancelled_keeps_access_until_period_end(billing_on):
    assert plan_service.has_access({"plan": "cancelled", "plan_expires_at": _iso(5)}) is True


def test_free_is_not_paid(billing_on):
    assert plan_service.has_access({"plan": "free"}) is False


def test_legacy_trial_is_not_paid(billing_on):
    # Migration 026 converts them, but a stale row must not grant paid access.
    assert plan_service.has_access({"plan": "trial", "trial_ends": _iso(5)}) is False


def test_empty_profile_is_not_paid(billing_on):
    assert plan_service.has_access({}) is False


def test_billing_disabled_grants_everything():
    with patch.object(plan_service.settings, "BILLING_ENABLED", False):
        assert plan_service.has_access({"plan": "free"}) is True


def test_parse_ts_handles_zulu_and_datetime():
    now = datetime.now(UTC)
    assert plan_service._parse_ts(now.isoformat().replace("+00:00", "Z")) is not None
    assert plan_service._parse_ts(now) == now
    assert plan_service._parse_ts("garbage") is None


# ─── limits_for ──────────────────────────────────────────────

def test_limits_free_is_manual_with_total_cap(billing_on):
    limits = plan_service.limits_for({"plan": "free"})
    assert limits == {
        "mode": "manual",
        "daily": None,
        "total": plan_service.settings.FREE_TOTAL_APPLIES,
    }


def test_limits_paid_is_auto_with_daily_cap(billing_on):
    limits = plan_service.limits_for({"plan": "active", "plan_expires_at": _iso(3)})
    assert limits == {
        "mode": "auto",
        "daily": plan_service.settings.PAID_DAILY_APPLIES,
        "total": None,
    }


def test_limits_expired_paid_falls_back_to_free(billing_on):
    # Истёкший платный не блокируется — он становится бесплатным.
    limits = plan_service.limits_for({"plan": "active", "plan_expires_at": _iso(-1)})
    assert limits["mode"] == "manual"
    assert limits["total"] == plan_service.settings.FREE_TOTAL_APPLIES


def test_limits_selfhost_is_unlimited_and_auto():
    with patch.object(plan_service.settings, "BILLING_ENABLED", False):
        assert plan_service.limits_for({"plan": "free"}) == {
            "mode": "auto",
            "daily": None,
            "total": None,
        }


# ─── async readers ───────────────────────────────────────────

def _profile_client(data):
    chain = MagicMock()
    for m in ("select", "eq", "maybe_single"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = SimpleNamespace(data=data)
    client = MagicMock()
    client.table.return_value = chain
    return client


@pytest.mark.asyncio
async def test_check_access_reads_profile(billing_on):
    client = _profile_client({"plan": "active", "plan_expires_at": _iso(2)})
    with patch.object(plan_service, "service_client", client):
        assert await plan_service.check_access("u1") is True


@pytest.mark.asyncio
async def test_get_limits_reads_profile(billing_on):
    client = _profile_client({"plan": "free"})
    with patch.object(plan_service, "service_client", client):
        limits = await plan_service.get_limits("u1")
    assert limits["mode"] == "manual"


@pytest.mark.asyncio
async def test_get_limits_missing_profile_is_free(billing_on):
    client = _profile_client(None)
    with patch.object(plan_service, "service_client", client):
        limits = await plan_service.get_limits("ghost")
    assert limits["mode"] == "manual"


# ─── filter_paid (sync, worker_main agent gate) ──────────────

def test_filter_paid_keeps_only_paying(billing_on):
    rows = [
        {"id": "u1", "plan": "free"},
        {"id": "u2", "plan": "active", "plan_expires_at": _iso(-2)},
        {"id": "u3", "plan": "active", "plan_expires_at": _iso(9)},
    ]
    chain = MagicMock()
    for m in ("select", "in_"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = SimpleNamespace(data=rows)
    client = MagicMock()
    client.table.return_value = chain
    with patch.object(plan_service, "service_client", client):
        # u4 has no profile row → not paid
        assert plan_service.filter_paid(["u1", "u2", "u3", "u4"]) == ["u3"]


def test_filter_paid_empty(billing_on):
    assert plan_service.filter_paid([]) == []


def test_filter_paid_selfhost_keeps_everyone():
    with patch.object(plan_service.settings, "BILLING_ENABLED", False):
        assert plan_service.filter_paid(["u1", "u2"]) == ["u1", "u2"]
