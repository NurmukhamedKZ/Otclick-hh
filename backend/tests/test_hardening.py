"""Regression tests for the production-readiness fixes (see AUDIT.md)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- /health must fail loudly on a dead DB (blocker 3) -----------------------

def test_health_raises_503_when_db_unreachable():
    from fastapi import HTTPException

    from app.main import health

    with patch("app.main.service_client") as sc:
        sc.table.side_effect = RuntimeError("db down")
        with pytest.raises(HTTPException) as ex:
            health()
    assert ex.value.status_code == 503


def test_health_ok_when_db_reachable():
    from app.main import health

    with patch("app.main.service_client"):
        assert health() == {"status": "ok", "db": True}


# --- hh connect jobs are capped and reaped (blocker 4) -----------------------

@pytest.mark.asyncio
async def test_second_connect_job_for_same_user_is_rejected():
    from fastapi import HTTPException

    from app.services import hh_auth

    hh_auth._jobs.clear()
    with patch.object(hh_auth, "_run_oauth", new=AsyncMock()):
        await hh_auth.start_connect_job("u1", "a@b.c", "pw")
        with pytest.raises(HTTPException) as ex:
            await hh_auth.start_connect_job("u1", "a@b.c", "pw")
    assert ex.value.status_code == 429
    hh_auth._jobs.clear()


@pytest.mark.asyncio
async def test_global_concurrent_job_cap():
    from fastapi import HTTPException

    from app.services import hh_auth

    hh_auth._jobs.clear()
    with patch.object(hh_auth, "_run_oauth", new=AsyncMock()):
        for i in range(hh_auth.MAX_CONCURRENT_JOBS):
            await hh_auth.start_connect_job(f"u{i}", "a@b.c", "pw")
        with pytest.raises(HTTPException) as ex:
            await hh_auth.start_connect_job("other", "a@b.c", "pw")
    assert ex.value.status_code == 429
    hh_auth._jobs.clear()


@pytest.mark.asyncio
async def test_finished_job_is_purged_after_ttl_and_frees_the_slot():
    from app.services import hh_auth

    hh_auth._jobs.clear()
    with patch.object(hh_auth, "_run_oauth", new=AsyncMock()):
        job_id = await hh_auth.start_connect_job("u1", "a@b.c", "pw")
    state = hh_auth.get_job(job_id)
    hh_auth._finish(state, "failed", "boom")
    assert state.status == "failed" and state.finished_at is not None

    # slot is free again immediately...
    with patch.object(hh_auth, "_run_oauth", new=AsyncMock()):
        await hh_auth.start_connect_job("u1", "a@b.c", "pw")
    # ...and the finished row disappears once the TTL passes
    hh_auth._purge_finished(now=state.finished_at + hh_auth.FINISHED_JOB_TTL_S + 1)
    assert hh_auth.get_job(job_id) is None
    hh_auth._jobs.clear()


# --- idle producer backs off instead of hammering hh (high 6) ---------------

def test_idle_backoff_doubles_and_is_capped():
    from app.worker.runner import IDLE_REFILL_MAX_SLEEP_S, IDLE_REFILL_SLEEP_S

    sleep = IDLE_REFILL_SLEEP_S
    seen = [sleep]
    for _ in range(20):
        sleep = min(sleep * 2, IDLE_REFILL_MAX_SLEEP_S)
        seen.append(sleep)
    assert seen[1] == IDLE_REFILL_SLEEP_S * 2
    assert seen[-1] == IDLE_REFILL_MAX_SLEEP_S
    assert max(seen) <= IDLE_REFILL_MAX_SLEEP_S


# --- recruiter agent keeps no cross-poll state (high 7) ---------------------

def test_recruiter_agent_is_built_without_a_checkpointer():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    with patch("app.ai.agent.create_agent") as create:
        agent._build_recruiter_agent("sys")
    _, kwargs = create.call_args
    assert "checkpointer" not in kwargs


# --- dead web session is detected and reported once (high 8) ----------------

@pytest.mark.parametrize(
    "status_code,url,expected",
    [
        (200, "https://hh.ru/applicant/vacancy_response?vacancyId=1", False),
        (403, "https://hh.ru/applicant/vacancy_response?vacancyId=1", True),
        (401, "https://hh.ru/x", True),
        (200, "https://hh.ru/account/login?backurl=%2F", True),
    ],
)
def test_session_looks_dead(status_code, url, expected):
    from app.services.form_filler import session_looks_dead

    resp = MagicMock(status_code=status_code, url=url)
    assert session_looks_dead(resp) is expected


@pytest.mark.asyncio
async def test_report_dead_session_drops_cache_and_notifies_once():
    from app.services import form_filler, notifications

    form_filler._sessions["u1"] = (0.0, MagicMock())
    with patch.object(notifications, "notify", new=AsyncMock()) as notify:
        await form_filler.report_dead_session("u1", RuntimeError("403"))
        await form_filler.report_dead_session("u1", RuntimeError("403"))

    assert "u1" not in form_filler._sessions
    assert notify.await_count == 1
    assert notify.await_args[0][1] == "web_session_expired"

    # a reconnect re-arms the notification
    notifications.clear_once("u1", "web_session_expired")
    with patch.object(notifications, "notify", new=AsyncMock()) as notify:
        await form_filler.report_dead_session("u1", RuntimeError("403"))
    assert notify.await_count == 1


# --- caches actually avoid the repeated work (high 9 / 10) ------------------

@pytest.mark.asyncio
async def test_web_session_is_built_once_per_user():
    import json

    from app.services import form_filler

    cookies = json.dumps([{"name": "c", "value": "v", "domain": ".hh.ru", "path": "/"}])
    with patch.object(form_filler, "_load_cookies_encrypted", return_value="enc") as load, \
         patch.object(form_filler, "decrypt_token", return_value=cookies):
        a = await form_filler.load_web_session("u1")
        b = await form_filler.load_web_session("u1")
    assert a is b
    assert load.call_count == 1


@pytest.mark.asyncio
async def test_api_client_cached_and_dropped_on_invalidation():
    from app.services import hh_credentials

    row = {"access_token_encrypted": "a", "refresh_token_encrypted": "r", "expires_at": None}
    with patch.object(hh_credentials, "_load_row", return_value=row) as load, \
         patch.object(hh_credentials, "decrypt_token", side_effect=lambda x: "USERtok"):
        a = await hh_credentials.load_api_client("u1")
        b = await hh_credentials.load_api_client("u1")
        assert a is b and load.call_count == 1

        hh_credentials.drop_cached_client("u1")
        c = await hh_credentials.load_api_client("u1")
    assert c is not a and load.call_count == 2


@pytest.mark.asyncio
async def test_negotiation_states_are_cached_between_polls():
    from app.worker import recruiter_poll

    client = MagicMock()
    client.get.return_value = {"items": [{"id": 1, "state": {"id": "discard"}}], "pages": 1}
    first = await recruiter_poll._negotiation_states(client, "u1")
    second = await recruiter_poll._negotiation_states(client, "u1")
    assert first == second == {"1": "discard"}
    assert client.get.call_count == 1  # second poll served from cache


# --- hh client raises real errors instead of asserts (high 11) --------------

def test_unknown_http_method_raises_value_error():
    from app.hh.client import ApiClient

    client = ApiClient()
    with pytest.raises(ValueError):
        client.request("PATCH", "me")


def test_unexpected_token_prefix_does_not_crash():
    from app.hh.client import ApiClient

    client = ApiClient(access_token="WEIRD-token")
    headers = client._default_headers()
    assert headers["authorization"] == "Bearer WEIRD-token"


# --- verified JWTs are cached but not forever (high 12) ---------------------

@pytest.mark.asyncio
async def test_get_current_user_caches_verification():
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api import deps

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok-123")
    res = MagicMock(user=MagicMock(id="user-9"))
    with patch.object(deps.anon_client.auth, "get_user", return_value=res) as get_user:
        assert await deps.get_current_user(creds) == "user-9"
        assert await deps.get_current_user(creds) == "user-9"
    assert get_user.call_count == 1
    # the raw token is never a cache key
    assert all("tok-123" not in k for k in deps._token_cache)


@pytest.mark.asyncio
async def test_get_current_user_hides_upstream_error_detail():
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api import deps

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad")
    with patch.object(deps.anon_client.auth, "get_user", side_effect=RuntimeError("secret internals")):
        with pytest.raises(HTTPException) as ex:
            await deps.get_current_user(creds)
    assert ex.value.status_code == 401
    assert "secret internals" not in str(ex.value.detail)
