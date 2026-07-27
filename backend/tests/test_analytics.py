import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from app.services import analytics  # noqa: E402


@pytest.mark.asyncio
async def test_summary_passes_params_and_merges_defaults():
    rpc = MagicMock()
    rpc.execute.return_value = SimpleNamespace(
        data={"funnel": {"sent": 5, "invited": 1}, "by_filter": [{"name": "py"}]}
    )
    with patch.object(analytics.service_client, "rpc", return_value=rpc) as call:
        out = await analytics.summary("u1", 7)

    call.assert_called_once_with("analytics_summary", {"p_user_id": "u1", "p_days": 7})
    assert out["days"] == 7
    assert out["funnel"]["sent"] == 5
    # keys the rpc did not return still exist (UI never sees undefined)
    assert out["kpi"]["invite_rate"] is None
    assert out["failures"] == []
    assert out["error"] is False


@pytest.mark.asyncio
async def test_summary_returns_empty_shape_on_rpc_failure():
    with patch.object(analytics.service_client, "rpc", side_effect=RuntimeError("boom")):
        out = await analytics.summary("u1", 30)
    assert out["funnel"]["sent"] == 0
    assert out["days"] == 30
    assert out["error"] is True
