import asyncio
import os

import pytest

# Set required env BEFORE importing app modules
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault(
    "FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc="
)


def test_encrypt_decrypt_roundtrip():
    from app.services.hh_auth import decrypt_token, encrypt_token

    plain = "USER_TOKEN_abc123"
    enc = encrypt_token(plain)
    assert enc != plain
    assert decrypt_token(enc) == plain


def test_job_state_lifecycle():
    from app.services.hh_auth import JobState, _jobs

    _jobs.clear()
    job_id = "test-job-id"
    state = JobState(user_id="user-1", status="running")
    _jobs[job_id] = state

    assert _jobs[job_id].status == "running"
    _jobs[job_id].status = "success"
    assert _jobs[job_id].status == "success"
    _jobs.clear()


@pytest.mark.asyncio
async def test_solve_captcha_unblocks_queue():
    from app.services.hh_auth import JobState, _jobs, solve_captcha

    _jobs.clear()
    job_id = "captcha-job"
    state = JobState(user_id="user-1", status="captcha_required")
    _jobs[job_id] = state

    solved = asyncio.create_task(state.captcha_queue.get())
    await solve_captcha(job_id, "abc123")
    result = await asyncio.wait_for(solved, timeout=1.0)
    assert result == "abc123"
    _jobs.clear()


def test_authorize_url_carries_the_configured_redirect_uri():
    from urllib.parse import parse_qs, urlsplit

    from app.hh.authorize import build_authorize_url
    from app.hh.client_keys import ANDROID_CLIENT_ID, REDIRECT_URI

    q = parse_qs(urlsplit(build_authorize_url()).query)
    assert q["client_id"] == [ANDROID_CLIENT_ID]
    assert q["response_type"] == ["code"]
    # Must be present and match the token exchange, or hh rejects the code.
    assert q["redirect_uri"] == [REDIRECT_URI]


def test_token_exchange_sends_the_same_redirect_uri():
    from unittest.mock import patch

    from app.hh.client import OAuthClient
    from app.hh.client_keys import REDIRECT_URI

    client = OAuthClient()
    with patch.object(OAuthClient, "post", return_value={
        "access_token": "USERa", "refresh_token": "r", "expires_in": 60,
    }) as post:
        client.authenticate("CODE")
    assert post.call_args.args[1]["redirect_uri"] == REDIRECT_URI


def test_extract_code_reads_query_and_fragment():
    from app.hh.authorize import _extract_code

    assert _extract_code("hhandroid://oauthresponse?code=Q") == "Q"
    assert _extract_code("https://x.test/cb#code=F") == "F"


def test_extract_code_surfaces_geo_forbidden_not_a_blank_failure():
    from app.hh.authorize import _extract_code

    with pytest.raises(RuntimeError, match="geo_forbidden"):
        _extract_code("hhandroid://oauthresponse?error=geo_forbidden")
    with pytest.raises(RuntimeError, match="invalid_client"):
        _extract_code("hhandroid://oauthresponse?error=invalid_client")
