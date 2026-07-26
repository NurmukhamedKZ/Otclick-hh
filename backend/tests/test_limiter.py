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
    chain.gte.return_value = chain
    chain.maybe_single.return_value = chain
    chain.upsert.return_value = chain
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
async def test_check_allowed_below_caps():
    from app.worker import limiter

    sb = MagicMock()
    # Sequence: tz lookup → day count read.
    sb.table.side_effect = [
        _fluent({"timezone": "Asia/Almaty"}),
        _fluent({"count": 10}),
    ]
    with patch.object(limiter, "service_client", sb):
        result = await limiter.check("u1")
    assert result == "allowed"


@pytest.mark.asyncio
async def test_check_limit_day_at_cap():
    from app.worker import limiter

    sb = MagicMock()
    sb.table.side_effect = [
        _fluent({"timezone": "Asia/Almaty"}),
        _fluent({"count": limiter.DAILY_LIMIT}),
    ]
    with patch.object(limiter, "service_client", sb):
        result = await limiter.check("u1")
    assert result == "limit_day"


@pytest.mark.asyncio
async def test_increment_bumps_count():
    from app.worker import limiter

    sb = MagicMock()
    sb.table.side_effect = [
        _fluent({"timezone": "Asia/Almaty"}),
        _fluent({"count": 7}),
        _fluent(None),  # upsert
    ]
    with patch.object(limiter, "service_client", sb):
        new_count = await limiter.increment("u1")
    assert new_count == 8
