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


@pytest.mark.asyncio
async def test_web_login_entrypoint_waits_for_domcontentloaded_and_form():
    from app.hh.authorize import HH_WEB_LOGIN, SEL_LOGIN_INPUT, _open_web_login

    class Response:
        status = 200

    class Page:
        url = HH_WEB_LOGIN

        def __init__(self):
            self.goto_args = None
            self.selector_args = None

        async def goto(self, url, **kwargs):
            self.goto_args = (url, kwargs)
            return Response()

        async def wait_for_selector(self, selector, **kwargs):
            self.selector_args = (selector, kwargs)

        def locator(self, _selector):
            class Locator:
                async def count(self):
                    return 0

            return Locator()

    page = Page()
    await _open_web_login(page)

    assert page.goto_args == (
        HH_WEB_LOGIN,
        {"timeout": 30000, "wait_until": "domcontentloaded"},
    )
    assert page.selector_args == (
        SEL_LOGIN_INPUT,
        {"timeout": 15000, "state": "visible"},
    )


@pytest.mark.asyncio
async def test_web_login_entrypoint_rejects_http_error_page():
    from app.hh.authorize import _open_web_login

    class Response:
        status = 400

    class Page:
        url = "https://hh.ru/account/login"

        async def goto(self, _url, **_kwargs):
            return Response()

        async def wait_for_selector(self, *_args, **_kwargs):
            raise AssertionError("form readiness must not be checked after HTTP 400")

    with pytest.raises(RuntimeError, match="HH login page returned HTTP 400"):
        await _open_web_login(Page())


@pytest.mark.asyncio
async def test_web_login_entrypoint_explains_antibot_block():
    from app.hh.authorize import _open_web_login

    class Response:
        status = 451

    class Page:
        url = "https://tambov.hh.ru/account/login"

        async def goto(self, _url, **_kwargs):
            return Response()

        async def wait_for_selector(self, *_args, **_kwargs):
            raise AssertionError("form readiness must not be checked after HTTP 451")

    with pytest.raises(RuntimeError, match="anti-bot protection.*HTTP 451"):
        await _open_web_login(Page())


def test_login_selector_covers_current_username_field():
    from app.hh.authorize import SEL_LOGIN_INPUT

    assert 'input[name="username"]' in SEL_LOGIN_INPUT
    assert 'input[type="text"]' in SEL_LOGIN_INPUT


def test_email_code_selector_covers_current_magritte_form():
    """Captured current HH page: the OTP wrapper was renamed in Magritte."""
    from app.hh.authorize import SEL_CODE_CONTAINER, SEL_PIN_CODE_INPUT

    assert 'applicant-login-input-otp' in SEL_CODE_CONTAINER
    assert 'magritte-pincode-input-field' in SEL_PIN_CODE_INPUT


@pytest.mark.asyncio
async def test_verified_web_cookies_probe_authenticated_page():
    from app.hh.authorize import HH_SESSION_CHECK, _verified_web_cookies

    class Response:
        status = 200

    class MainPage:
        async def wait_for_url(self, _predicate, **kwargs):
            assert kwargs["wait_until"] == "domcontentloaded"

    class Probe:
        url = HH_SESSION_CHECK

        async def goto(self, url, **kwargs):
            assert url == HH_SESSION_CHECK
            assert kwargs["wait_until"] == "domcontentloaded"
            return Response()

        async def close(self):
            pass

    class Context:
        async def new_page(self):
            return Probe()

        async def cookies(self):
            return [{"name": "hhtoken", "value": "redacted"}]

    assert await _verified_web_cookies(MainPage(), Context()) == [
        {"name": "hhtoken", "value": "redacted"}
    ]


@pytest.mark.asyncio
async def test_verified_web_cookies_reject_login_wall():
    from app.hh.authorize import _verified_web_cookies

    class Response:
        status = 200

    class MainPage:
        async def wait_for_url(self, _predicate, **_kwargs):
            return None

    class Probe:
        url = "https://hh.ru/account/login?backurl=%2Fapplicant%2Fresumes"

        async def goto(self, _url, **_kwargs):
            return Response()

        async def close(self):
            pass

    class Context:
        async def new_page(self):
            return Probe()

        async def cookies(self):
            raise AssertionError("cookies must not be accepted after login redirect")

    with pytest.raises(RuntimeError, match="did not create an authenticated web session"):
        await _verified_web_cookies(MainPage(), Context())


def test_token_exchange_sends_the_same_redirect_uri():
    from unittest.mock import patch

    from app.hh.client import OAuthClient
    from app.hh.client_keys import REDIRECT_URI

    client = OAuthClient()
    with patch.object(
        OAuthClient,
        "post",
        return_value={
            "access_token": "USERa",
            "refresh_token": "r",
            "expires_in": 60,
        },
    ) as post:
        client.authenticate("CODE")
    assert post.call_args.args[1]["redirect_uri"] == REDIRECT_URI


async def test_connect_stores_a_cookies_only_connection_when_hh_refuses_the_code():
    import asyncio
    from unittest.mock import patch

    from app.services import hh_auth

    loop = asyncio.get_running_loop()
    stored = {}

    def _persist_web_only(user_id, cookies):
        stored["user_id"] = user_id
        stored["cookies"] = cookies

    with (
        patch.object(
            hh_auth,
            "_persist_web_session_only",
            side_effect=_persist_web_only,
        ),
        patch.object(hh_auth, "_exchange_and_fetch_user") as exchange,
    ):
        await hh_auth._persist_connection(
            loop,
            "u1",
            None,
            [{"name": "hhtoken"}],
        )

    assert stored["user_id"] == "u1"
    assert stored["cookies"] == [{"name": "hhtoken"}]
    exchange.assert_not_called()


async def test_connect_keeps_the_cookies_when_the_token_exchange_itself_fails():
    import asyncio
    from unittest.mock import patch

    from app.services import hh_auth

    loop = asyncio.get_running_loop()
    stored = {}

    with (
        patch.object(
            hh_auth,
            "_persist_web_session_only",
            side_effect=lambda u, c: stored.update(user_id=u, cookies=c),
        ),
        patch.object(
            hh_auth,
            "_exchange_and_fetch_user",
            side_effect=RuntimeError("hh 400"),
        ),
    ):
        await hh_auth._persist_connection(
            loop,
            "u1",
            "CODE",
            [{"name": "hhtoken"}],
        )

    assert stored["user_id"] == "u1"


def test_status_reports_connected_without_an_api_token_but_not_without_cookies():
    from unittest.mock import MagicMock, patch

    from app.services import hh_auth

    def _status(row):
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value
        chain.maybe_single.return_value.execute.return_value = MagicMock(data=row)
        with patch.object(hh_auth, "service_client", sb):
            return hh_auth.get_credentials_status("u1")

    cookies_only = _status({"web_cookies_encrypted": "enc", "expires_at": None})
    assert cookies_only["connected"] is True
    assert cookies_only["has_api_token"] is False

    # A token row whose web session was never captured cannot serve any feature.
    assert _status({"web_cookies_encrypted": None, "expires_at": "2030-01-01"}) == {
        "connected": False
    }
