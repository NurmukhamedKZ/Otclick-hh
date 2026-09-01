"""Playwright OAuth flow for hh.ru.

Adapted from backend/poc_day1_playwright.py. Differs from
hh-applicant-tool/operations/authorize.py — the upstream selectors are stale
(Magritte UI changed). Our POC selectors are verified Day 1.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.async_api import async_playwright

from .client_keys import ANDROID_CLIENT_ID, REDIRECT_URI

logger = logging.getLogger(__name__)

HH_OAUTH_AUTHORIZE = "https://hh.ru/oauth/authorize"

SEL_LOGIN_INPUT = 'input[data-qa="login-input-username"], input[name="login"], input[type="email"]'
SEL_EXPAND_PASSWORD = (
    'button:has-text("Войти с паролем"), '
    'button:has-text("Войти по паролю"), '
    'a:has-text("Войти с паролем"), '
    'button[data-qa="expand-login-by-password"]'
)
SEL_PASSWORD_INPUT = (
    'input[data-qa="applicant-login-input-password"], '
    'input[data-qa="login-input-password"], '
    'input[name="password"]:not([type="hidden"]), '
    'input[type="password"]'
)
SEL_CAPTCHA_IMAGE = 'img[data-qa="account-captcha-picture"]'
SEL_CAPTCHA_INPUT = 'input[data-qa="account-captcha-input"]'

SEL_CODE_CONTAINER = 'div[data-qa="account-login-code-input"]'
SEL_PIN_CODE_INPUT = 'input[data-qa="magritte-pincode-input-field"]'


def build_authorize_url() -> str:
    qs = urlencode({
        "client_id": ANDROID_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
    })
    return f"{HH_OAUTH_AUTHORIZE}?{qs}"


def _watch_redirect(page) -> asyncio.Future[str]:
    """Resolve with the full redirect_uri URL hh sends the browser to.

    Works both for the Android custom scheme (which never loads) and for a real
    https callback of a self-registered app — we only need the URL, not its
    response, so it does not matter whether the host resolves.
    """
    fut: asyncio.Future[str] = asyncio.Future()

    def handle_request(request):
        if request.url.startswith(REDIRECT_URI) and not fut.done():
            fut.set_result(request.url)

    page.on("request", handle_request)
    return fut


def _extract_code(redirect_url: str) -> str | None:
    """Pull the OAuth code out of the redirect, or None with the reason logged.

    Deliberately does NOT raise. The login itself already succeeded by this
    point and the browser holds a working hh.ru web session — which is what the
    product actually runs on. Blowing up here used to throw those cookies away
    over an OAuth grant nothing needs any more.
    """
    parts = urlsplit(redirect_url)
    params = parse_qs(parts.query)
    params.update(parse_qs(parts.fragment))  # hh may answer in the fragment
    code = (params.get("code") or [None])[0]
    if code:
        return code
    err = (params.get("error_description") or params.get("error") or [None])[0]
    if err == "geo_forbidden":
        logger.warning(
            "hh oauth: geo_forbidden — hh refuses the OAuth grant for this "
            "region under client_id %s. Continuing on the web session alone; "
            "register your own app (dev.hh.kz/admin) to get tokens back.",
            ANDROID_CLIENT_ID[:8],
        )
    else:
        logger.warning("hh oauth: no code in redirect %s", redirect_url)
    return None


async def get_auth_code(
    username: str,
    password: str,
    on_captcha: Callable[[bytes], Awaitable[str]] | None = None,
    headless: bool = True,
) -> tuple[str | None, list[dict]]:
    """Run Playwright OAuth flow → returns (hh OAuth code or None, web cookies).

    The cookies are the logged-in hh.ru session captured from the same browser
    context. Stored alongside the tokens and reused by the form-filler to solve
    vacancy tests over the web endpoint — avoids re-login (and its captcha).

    on_captcha: async callback (screenshot_png_bytes) -> solution_string.
                If captcha appears and callback is None, raises RuntimeError.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=["--disable-dev-shm-usage"])
        try:
            device = pw.devices["Galaxy A55"]
            context = await browser.new_context(**device)
            page = await context.new_page()

            redirect_future = _watch_redirect(page)

            await page.goto(build_authorize_url(), timeout=30000, wait_until="load")

            await page.wait_for_selector(SEL_LOGIN_INPUT, timeout=10000, state="visible")
            await page.fill(SEL_LOGIN_INPUT, username)

            try:
                await page.wait_for_selector(SEL_EXPAND_PASSWORD, timeout=5000, state="visible")
                await page.click(SEL_EXPAND_PASSWORD)
            except Exception:
                pass  # password field may already be visible

            await _handle_captcha_if_present(page, on_captcha)

            try:
                await page.wait_for_selector(SEL_PASSWORD_INPUT, timeout=15000, state="visible")
            except Exception:
                try:
                    import logging
                    inputs = await page.evaluate(
                        "Array.from(document.querySelectorAll('input,button'))"
                        ".slice(0,40).map(e=>({tag:e.tagName,type:e.type,"
                        "name:e.name,qa:e.getAttribute('data-qa'),"
                        "text:(e.innerText||'').slice(0,40)}))"
                    )
                    logging.getLogger(__name__).error(
                        "hh login: password field missing. URL=%s inputs=%s",
                        page.url, inputs,
                    )
                except Exception:
                    pass
                raise
            await page.fill(SEL_PASSWORD_INPUT, password)
            await page.keyboard.press("Enter")

            await _handle_captcha_if_present(page, on_captcha)

            code = _extract_code(await asyncio.wait_for(redirect_future, timeout=120.0))
            cookies = await context.cookies()
            return code, cookies
        finally:
            await browser.close()


async def _handle_captcha_if_present(page, on_captcha):
    try:
        await page.wait_for_selector(SEL_CAPTCHA_IMAGE, timeout=2500, state="visible")
    except Exception:
        return  # no captcha

    if on_captcha is None:
        raise RuntimeError("Captcha required but no handler provided")

    locator = page.locator(SEL_CAPTCHA_IMAGE)
    await locator.evaluate(
        "img => img.complete && img.naturalWidth > 0 "
        "? Promise.resolve() "
        ": new Promise((res, rej) => { "
        "img.addEventListener('load', res, {once: true}); "
        "img.addEventListener('error', rej, {once: true}); "
        "})"
    )
    await page.wait_for_function(
        "sel => { const i = document.querySelector(sel);"
        " return i && i.complete && i.naturalWidth > 0 && i.getBoundingClientRect().height > 20; }",
        arg=SEL_CAPTCHA_IMAGE,
        timeout=10000,
    )
    screenshot = await locator.screenshot()
    solution = await on_captcha(screenshot)
    await page.fill(SEL_CAPTCHA_INPUT, solution)
    await page.keyboard.press("Enter")


async def get_auth_code_via_email_code(
    email: str,
    on_code_required: Callable[[], Awaitable[str]] | None = None,
    on_captcha: Callable[[bytes], Awaitable[str]] | None = None,
    headless: bool = True,
) -> tuple[str | None, list[dict]]:
    """Run Playwright OAuth flow using email-code (passwordless) → returns (code or None, web cookies).

    Flow:
    1. Fill email → press Enter → captcha? → code page
    2. on_code_required callback: code page is visible → ask user for code from email
    3. Fill pincode input → press Enter → captcha? → intercept redirect

    on_code_required: async callback () → code_string. Called when hh.ru shows the code input page.
    on_captcha: async callback (screenshot_png_bytes) → solution_string.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=["--disable-dev-shm-usage"])
        try:
            device = pw.devices["Galaxy A55"]
            context = await browser.new_context(**device)
            page = await context.new_page()

            redirect_future = _watch_redirect(page)

            await page.goto(build_authorize_url(), timeout=30000, wait_until="load")

            await page.wait_for_selector(SEL_LOGIN_INPUT, timeout=10000, state="visible")
            await page.fill(SEL_LOGIN_INPUT, email)
            await page.keyboard.press("Enter")

            await _handle_captcha_if_present(page, on_captcha)

            await page.wait_for_selector(SEL_CODE_CONTAINER, timeout=30000, state="visible")

            if on_code_required is None:
                raise RuntimeError("Email code required but no handler provided")
            code = await on_code_required()

            await page.fill(SEL_PIN_CODE_INPUT, code)
            await page.keyboard.press("Enter")

            await _handle_captcha_if_present(page, on_captcha)

            oauth_code = _extract_code(await asyncio.wait_for(redirect_future, timeout=120.0))
            cookies = await context.cookies()
            return oauth_code, cookies
        finally:
            await browser.close()
