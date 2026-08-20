"""hh OAuth onboarding: Playwright job manager + Fernet + Supabase writes."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from fastapi import status as status_codes

from app.config import settings
from app.db.supabase import service_client
from app.hh.authorize import get_auth_code, get_auth_code_via_email_code
from app.hh.client import ApiClient, OAuthClient
from app.hh.user_agent import generate_android_useragent

logger = logging.getLogger(__name__)

JobStatus = Literal["running", "captcha_required", "code_required", "success", "failed"]

CAPTCHA_TIMEOUT_SECONDS = 300.0
CODE_TIMEOUT_SECONDS = 300.0


# Each job launches a headless Chromium. Without a cap, one authenticated user
# can OOM the API container by spamming POST /api/hh/connect.
MAX_CONCURRENT_JOBS = 4
# Finished jobs are kept only long enough for the client to poll the result.
FINISHED_JOB_TTL_S = 600.0


@dataclass
class JobState:
    user_id: str
    status: JobStatus = "running"
    captcha_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    code_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    screenshot_url: str | None = None
    error: str | None = None
    finished_at: float | None = None
    # Strong ref to the background task: a bare asyncio.create_task() result is
    # only weakly held by the loop and can be GC'd mid-flow.
    task: asyncio.Task | None = None


_jobs: dict[str, JobState] = {}


def _live_jobs() -> list[JobState]:
    return [s for s in _jobs.values() if s.finished_at is None]


def _purge_finished(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    for job_id, state in list(_jobs.items()):
        if state.finished_at is not None and now - state.finished_at > FINISHED_JOB_TTL_S:
            _jobs.pop(job_id, None)


def _finish(state: JobState, status: JobStatus, error: str | None = None) -> None:
    state.status = status
    state.error = error
    state.finished_at = time.monotonic()


def _admit(user_id: str) -> None:
    """Raise 429 when this user (or the box) already has a job running."""
    _purge_finished()
    live = _live_jobs()
    if any(s.user_id == user_id for s in live):
        raise HTTPException(
            status_code=status_codes.HTTP_429_TOO_MANY_REQUESTS,
            detail="connect job already running for this user",
        )
    if len(live) >= MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=status_codes.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many concurrent hh connect jobs — try again shortly",
        )


def _browser_reachable(url: str) -> str:
    """Signed Storage URLs come back on SUPABASE_URL's host (in-docker `kong`).
    Swap it for the host the user's browser can actually reach."""
    base = settings.SUPABASE_URL.rstrip("/")
    public = settings.SUPABASE_PUBLIC_URL.rstrip("/")
    if public and url.startswith(base):
        return public + url[len(base):]
    return url


def encrypt_token(plain: str) -> str:
    return settings.fernet.encrypt(plain.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    return settings.fernet.decrypt(encrypted.encode()).decode()


def get_job(job_id: str) -> JobState | None:
    return _jobs.get(job_id)


async def start_connect_job(user_id: str, username: str, password: str) -> str:
    _admit(user_id)
    job_id = str(uuid.uuid4())
    state = JobState(user_id=user_id)
    _jobs[job_id] = state
    state.task = asyncio.create_task(_run_oauth(job_id, username, password))
    return job_id


async def solve_captcha(job_id: str, solution: str) -> None:
    state = _jobs.get(job_id)
    if not state:
        raise KeyError(f"job {job_id} not found")
    await state.captcha_queue.put(solution)


async def start_connect_email_code_job(user_id: str, username: str) -> str:
    _admit(user_id)
    job_id = str(uuid.uuid4())
    state = JobState(user_id=user_id)
    _jobs[job_id] = state
    state.task = asyncio.create_task(_run_oauth_email_code(job_id, username))
    return job_id


async def solve_email_code(job_id: str, code: str) -> None:
    state = _jobs.get(job_id)
    if not state:
        raise KeyError(f"job {job_id} not found")
    await state.code_queue.put(code)


async def _run_oauth(job_id: str, username: str, password: str) -> None:
    state = _jobs[job_id]
    loop = asyncio.get_running_loop()
    try:
        async def on_captcha(screenshot_png: bytes) -> str:
            state.status = "captcha_required"
            path = f"{state.user_id}/{job_id}.png"

            # Sync Supabase storage calls — run in executor to avoid blocking event loop
            await loop.run_in_executor(
                None,
                lambda: service_client.storage.from_("captcha-screenshots").upload(
                    path, screenshot_png,
                    {"content-type": "image/png", "upsert": "true"},
                ),
            )
            signed = await loop.run_in_executor(
                None,
                lambda: service_client.storage.from_("captcha-screenshots")
                    .create_signed_url(path, 600),
            )
            url = signed.get("signedURL") or signed.get("signedUrl")
            if not url:
                raise RuntimeError("Captcha screenshot URL unavailable (storage error)")
            state.screenshot_url = _browser_reachable(url)

            try:
                solution = await asyncio.wait_for(
                    state.captcha_queue.get(), timeout=CAPTCHA_TIMEOUT_SECONDS
                )
            except TimeoutError:
                raise RuntimeError(
                    f"Captcha not solved within {int(CAPTCHA_TIMEOUT_SECONDS // 60)} minutes"
                )
            state.status = "running"
            return solution

        code, cookies = await get_auth_code(
            username, password, on_captcha=on_captcha, headless=True
        )

        # Sync blocking HTTP calls (requests + time.sleep) — run in executor
        await _persist_connection(loop, state.user_id, code, cookies)
        _finish(state, "success")
    except Exception as ex:
        logger.exception("hh oauth job %s failed", job_id)
        _finish(state, "failed", str(ex))


async def _run_oauth_email_code(job_id: str, username: str) -> None:
    state = _jobs[job_id]
    loop = asyncio.get_running_loop()
    try:
        async def on_captcha(screenshot_png: bytes) -> str:
            state.status = "captcha_required"
            path = f"{state.user_id}/{job_id}.png"
            await loop.run_in_executor(
                None,
                lambda: service_client.storage.from_("captcha-screenshots").upload(
                    path, screenshot_png,
                    {"content-type": "image/png", "upsert": "true"},
                ),
            )
            signed = await loop.run_in_executor(
                None,
                lambda: service_client.storage.from_("captcha-screenshots")
                    .create_signed_url(path, 600),
            )
            url = signed.get("signedURL") or signed.get("signedUrl")
            if not url:
                raise RuntimeError("Captcha screenshot URL unavailable (storage error)")
            state.screenshot_url = _browser_reachable(url)

            try:
                solution = await asyncio.wait_for(
                    state.captcha_queue.get(), timeout=CAPTCHA_TIMEOUT_SECONDS
                )
            except TimeoutError:
                raise RuntimeError(
                    f"Captcha not solved within {int(CAPTCHA_TIMEOUT_SECONDS // 60)} minutes"
                )
            state.status = "running"
            return solution

        async def on_code_required() -> str:
            state.status = "code_required"
            try:
                code = await asyncio.wait_for(
                    state.code_queue.get(), timeout=CODE_TIMEOUT_SECONDS
                )
            except TimeoutError:
                raise RuntimeError(
                    f"Email code not provided within {int(CODE_TIMEOUT_SECONDS // 60)} minutes"
                )
            state.status = "running"
            return code

        code, cookies = await get_auth_code_via_email_code(
            username,
            on_code_required=on_code_required,
            on_captcha=on_captcha,
            headless=True,
        )

        await _persist_connection(loop, state.user_id, code, cookies)
        _finish(state, "success")
    except Exception as ex:
        logger.exception("hh oauth email-code job %s failed", job_id)
        _finish(state, "failed", str(ex))


async def _persist_connection(
    loop, user_id: str, code: str | None, cookies: list[dict]
) -> None:
    """Store whatever the login produced.

    The web session is the product's data path; the OAuth token is a bonus hh
    refuses outside the client's region (`geo_forbidden`). A connect that got
    cookies but no code is a WORKING connection, not a failure — treating it as
    one used to discard the cookies and leave the user unable to reconnect at all.
    """
    if code:
        try:
            token = await loop.run_in_executor(None, _exchange_and_fetch_user, code)
        except Exception:
            logger.exception("hh oauth: token exchange failed — keeping cookies")
        else:
            await loop.run_in_executor(
                None,
                _persist_credentials,
                user_id,
                token["access_token"],
                token["refresh_token"],
                token["access_expires_at"],
                token["hh_user_id"],
                cookies,
            )
            return
    logger.info("hh oauth: storing a cookies-only connection for %s", user_id)
    await loop.run_in_executor(None, _persist_web_session_only, user_id, cookies)


def _exchange_and_fetch_user(code: str) -> dict:
    ua = generate_android_useragent()
    oauth = OAuthClient(user_agent=ua)
    tok = oauth.authenticate(code)
    api = ApiClient(
        user_agent=ua,
        access_token=tok["access_token"],
        refresh_token=tok["refresh_token"],
        access_expires_at=tok["access_expires_at"],
    )
    me = api.get("me")
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok["refresh_token"],
        "access_expires_at": tok["access_expires_at"],
        "hh_user_id": str(me["id"]),
    }


def _persist_web_session_only(user_id: str, web_cookies: list[dict]) -> None:
    """Upsert just the web session, leaving any existing token columns alone.

    Clears invalid_at: a fresh login IS a valid connection even without a token.
    """
    service_client.table("hh_credentials").upsert({
        "user_id": user_id,
        "web_cookies_encrypted": encrypt_token(json.dumps(web_cookies)),
        "last_refreshed_at": datetime.now(UTC).isoformat(),
        "invalid_at": None,
        "invalid_reason": None,
    }).execute()
    _reset_caches(user_id)


def _reset_caches(user_id: str) -> None:
    from app.services import notifications
    from app.services.form_filler import drop_web_session
    from app.services.hh_credentials import drop_cached_client

    drop_web_session(user_id)
    drop_cached_client(user_id)
    notifications.clear_once(user_id, "web_session_expired")


def _persist_credentials(user_id: str, access: str, refresh: str,
                         expires_at: int, hh_user_id: str,
                         web_cookies: list[dict] | None = None) -> None:
    now = datetime.now(UTC).isoformat()
    row = {
        "user_id": user_id,
        "access_token_encrypted": encrypt_token(access),
        "refresh_token_encrypted": encrypt_token(refresh),
        "expires_at": datetime.fromtimestamp(expires_at, tz=UTC).isoformat(),
        "hh_user_id": hh_user_id,
        "last_refreshed_at": now,
        "invalid_at": None,
        "invalid_reason": None,
    }
    if web_cookies is not None:
        row["web_cookies_encrypted"] = encrypt_token(json.dumps(web_cookies))
    service_client.table("hh_credentials").upsert(row).execute()
    # Fresh credentials — drop anything cached from the previous connection and
    # re-arm the "web session expired" notification.
    _reset_caches(user_id)


def get_credentials_status(user_id: str) -> dict:
    res = service_client.table("hh_credentials").select(
        "expires_at,last_refreshed_at,hh_user_id,invalid_at,web_cookies_encrypted"
    ).eq("user_id", user_id).maybe_single().execute()
    data = res.data if res else None
    if not data or data.get("invalid_at"):
        return {"connected": False}
    # The web session is what the product runs on; an OAuth token is optional
    # (hh refuses the grant in some regions). No cookies = nothing works.
    if not data.get("web_cookies_encrypted"):
        return {"connected": False}
    return {
        "connected": True,
        "has_api_token": bool(data.get("expires_at")),
        "expires_at": data.get("expires_at"),
        "last_refreshed_at": data.get("last_refreshed_at"),
        "hh_user_id": data.get("hh_user_id"),
    }


def disconnect(user_id: str) -> None:
    from app.services.form_filler import drop_web_session
    from app.services.hh_credentials import drop_cached_client

    service_client.table("hh_credentials").delete().eq("user_id", user_id).execute()
    drop_web_session(user_id)
    drop_cached_client(user_id)
