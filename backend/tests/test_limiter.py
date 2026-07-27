import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


def _fluent(final_data, count=None):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.in_.return_value = chain
    chain.maybe_single.return_value = chain
    chain.upsert.return_value = chain
    chain.execute.return_value = SimpleNamespace(data=final_data, count=count)
    return chain


@contextmanager
def _limits(mode, daily=None, total=None):
    """Pin what plan.limits_for says — the limiter must never decide caps itself."""
    from app.services import plan as plan_service

    with (
        patch.object(plan_service, "_fetch_profile", return_value={}),
        patch.object(
            plan_service,
            "limits_for",
            return_value={"mode": mode, "daily": daily, "total": total},
        ),
    ):
        yield


def test_tz_for_user_default_when_missing():
    from app.worker import limiter

    sb = MagicMock()
    sb.table.return_value = _fluent(None)
    with patch.object(limiter, "service_client", sb):
        tz = limiter._tz_for_user("u1")
    assert tz.key == limiter.DEFAULT_TZ


def test_tz_for_user_falls_back_on_unknown():
    from app.worker import limiter

    sb = MagicMock()
    sb.table.return_value = _fluent({"timezone": "Mars/Olympus"})
    with patch.object(limiter, "service_client", sb):
        tz = limiter._tz_for_user("u1")
    assert tz.key == limiter.DEFAULT_TZ


@pytest.mark.asyncio
async def test_check_allowed_below_caps():
    from app.worker import limiter

    sb = MagicMock()
    # Sequence: tz lookup → day count read.
    sb.table.side_effect = [
        _fluent({"timezone": "Asia/Almaty"}),
        _fluent({"count": 10}),
    ]
    with _limits("auto", daily=100), patch.object(limiter, "service_client", sb):
        result = await limiter.check("u1")
    assert result == "allowed"


@pytest.mark.asyncio
async def test_check_limit_day_at_cap():
    from app.worker import limiter

    sb = MagicMock()
    sb.table.side_effect = [
        _fluent({"timezone": "Asia/Almaty"}),
        _fluent({"count": 100}),
    ]
    with _limits("auto", daily=100), patch.object(limiter, "service_client", sb):
        result = await limiter.check("u1")
    assert result == "limit_day"


# ─── free tier: lifetime total instead of a daily cap ────────

@pytest.mark.asyncio
async def test_free_at_total_cap_returns_limit_total():
    from app.worker import limiter

    sb = MagicMock()
    sb.table.side_effect = [_fluent([], count=30)]
    with _limits("manual", total=30), patch.object(limiter, "service_client", sb):
        result = await limiter.check("u1")
    assert result == "limit_total"


@pytest.mark.asyncio
async def test_free_below_total_cap_allowed():
    from app.worker import limiter

    sb = MagicMock()
    sb.table.side_effect = [_fluent([], count=29)]
    with _limits("manual", total=30), patch.object(limiter, "service_client", sb):
        result = await limiter.check("u1")
    # свободных нет дневного лимита — второй запрос не нужен
    assert result == "allowed"
    assert sb.table.call_count == 1


@pytest.mark.asyncio
async def test_paid_ignores_total_cap():
    """Платный с 30+ отправленными не упирается в бесплатный лимит."""
    from app.worker import limiter

    sb = MagicMock()
    sb.table.side_effect = [
        _fluent({"timezone": "Asia/Almaty"}),
        _fluent({"count": 5}),
    ]
    with _limits("auto", daily=100), patch.object(limiter, "service_client", sb):
        result = await limiter.check("u1")
    assert result == "allowed"


@pytest.mark.asyncio
async def test_selfhost_no_caps_at_all():
    from app.worker import limiter

    sb = MagicMock()
    sb.table.side_effect = []  # ни одного запроса: считать нечего
    with _limits("auto"), patch.object(limiter, "service_client", sb):
        result = await limiter.check("u1")
    assert result == "allowed"


def test_sent_total_counts_only_delivered_statuses():
    from app.worker import limiter

    chain = _fluent([], count=7)
    sb = MagicMock()
    sb.table.return_value = chain
    with patch.object(limiter, "service_client", sb):
        assert limiter.sent_total("u1") == 7
    # form_required / failed / captcha до hh не дошли и лимит не жгут
    assert chain.in_.call_args[0][1] == ["sent", "form_sent"]


@pytest.mark.asyncio
async def test_increment_bumps_count():
    """One atomic RPC (migration 025) — no read-modify-write to lose races on."""
    from app.worker import limiter

    sb = MagicMock()
    sb.table.side_effect = [_fluent({"timezone": "Asia/Almaty"})]
    sb.rpc.return_value.execute.return_value = MagicMock(data=8)
    with patch.object(limiter, "service_client", sb):
        new_count = await limiter.increment("u1")
    assert new_count == 8
    fn, args = sb.rpc.call_args[0]
    assert fn == "increment_apply_counter"
    assert args["p_user_id"] == "u1" and args["p_date"]
    # the counter row is never read before writing
    assert sb.table.call_count == 1
