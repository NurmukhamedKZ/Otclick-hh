import os
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
    chain.in_.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = SimpleNamespace(data=final_data, count=count)
    return chain


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
async def test_check_is_always_allowed_without_commercial_quotas():
    from app.worker import limiter

    sb = MagicMock()
    with patch.object(limiter, "service_client", sb):
        result = await limiter.check("u1")
    assert result == "allowed"
    sb.table.assert_not_called()


def test_sent_total_counts_only_delivered_statuses():
    from app.worker import limiter

    chain = _fluent([], count=7)
    sb = MagicMock()
    sb.table.return_value = chain
    with patch.object(limiter, "service_client", sb):
        assert limiter.sent_total("u1") == 7
    assert chain.in_.call_args[0][1] == ["sent", "form_sent"]


@pytest.mark.asyncio
async def test_increment_bumps_count():
    """Daily counter remains for analytics/status even though it is not a quota."""
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
    assert sb.table.call_count == 1
