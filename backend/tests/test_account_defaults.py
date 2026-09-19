import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _table(data):
    chain = MagicMock()
    for m in ("select", "eq", "order", "maybe_single"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = SimpleNamespace(data=data)
    return chain


def test_new_account_gets_seeded_candidate_profile():
    from app.services import candidate_context_service as svc

    profile = {"version": 1, "source_name": "s", "data": {"a": 1}}
    sb = MagicMock()
    # 1st lookup: no profile → seed → 2nd lookup: profile + facts
    sb.table.side_effect = [_table(None), _table(profile), _table([])]
    with (
        patch.object(svc, "service_client", sb),
        patch.object(svc, "_seed_default_profile") as seed,
    ):
        ctx = svc._load("u1")
    seed.assert_called_once_with("u1")
    assert ctx["profile"] == {"a": 1}


def test_seed_failure_keeps_409():
    from app.services import candidate_context_service as svc

    sb = MagicMock()
    sb.table.side_effect = [_table(None)]
    with (
        patch.object(svc, "service_client", sb),
        patch.object(svc, "_seed_default_profile", side_effect=RuntimeError("boom")),
        pytest.raises(HTTPException) as ex,
    ):
        svc._load("u1")
    assert ex.value.status_code == 409


@pytest.mark.asyncio
async def test_form_approve_refused_while_real_apply_disabled():
    from app.api import forms

    with patch.object(forms.settings, "ALLOW_REAL_APPLY", False):
        with pytest.raises(HTTPException) as ex:
            await forms.approve_draft("d1", forms.ApproveRequest(), user_id="u1")
    assert ex.value.status_code == 409
    assert "real_apply_disabled" in ex.value.detail
