"""Playwright web-login flow for hh.ru.

The product uses the authenticated hh.ru web session as its primary data path.
OAuth tokens are optional, so connection must not depend on a borrowed mobile
OAuth client id. The legacy public function names are kept for compatibility
with the service layer; they now return ``(None, cookies)`` after a successful
normal hh.ru web login.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

HH_WEB_LOGIN = "https://hh.ru/account/login"
HH_SESSION_CHECK = "https://hh.ru/applicant/resumes"

# HH changes the first step of the form independently for desktop/mobile and
# for A/B experiments.  `username` is the current Magritte field name; the
# other variants are kept for older rollouts and regional mirrors.
SEL_LOGIN_INPUT = (
    'input[data-qa="login-input-username"], '
    'input[data-qa="applicant-login-input-email"], '
    'input[name="username"], '
    'input[name="login"], '
    'input[autocomplete="username"], '
    'input[type="email"], '
    'input[type="tel"], '
    # Some current regional login pages omit both name and data-qa.  Scope the
    # generic fallback to the login form so it cannot select unrelated fields.
    'form[data-qa="account-login-form"] input[type="text"]:not([autocomplete="one-time-code"]), '
    'form[data-qa="account-login-form"] input:not([type]):not([autocomplete="one-time-code"])'
)
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

SEL_CODE_CONTAINER = (
    'div[data-qa="account-login-code-input"], '
    'div[data-qa="applicant-login-input-otp"]'
)
SEL_PIN_CODE_INPUT = 'input[data-qa="magritte-pincode-input-field"]'

SEL_APPLICANT_ACCOUNT_TYPE = 'input[data-qa*="account-type-card-APPLICANT"]'
SEL_ACCOUNT_TYPE_SUBMIT = 'button[data-qa="submit-button"]'
SEL_EMAIL_CREDENTIAL_TYPE = 'input[data-qa*="credential-type-email"]'


def _is_auth_wall(url: str) -> bool:
    return "/account/login" in url or "/account/captcha" in url


async def _login_page_diagnostics(page) -> str:
    """Return a small, non-sensitive description when HH did not render login.

    DDoS-Guard commonly returns an HTTP 200 challenge page, so the HTTP status
    alone cannot distinguish it from a usable login form.  Do not include the
    full HTML: it can contain anti-bot tokens and is not useful to the user.
    """
    try:
        title = (await page.title()).strip()
        body = " ".join((await page.locator("body").inner_text()).split())[:500]
    except Exception:
        return "page content could not be read"

    marker = f"{title} {body}".lower()
    if any(value in marker for value in ("ddos-guard", "access denied", "доступ ограничен")):
        return "anti-bot protection page"
    inputs = await page.locator("input:visible").evaluate_all(
        """elements => elements.map(element => ({
            type: element.type,
            name: element.name,
            autocomplete: element.autocomplete,
            inputmode: element.inputMode,
            qa: element.getAttribute("data-qa"),
            placeholder: element.placeholder,
        }))"""
    )
    return f"title={title!r}, visible inputs={inputs!r}"


async def _open_web_login(page) -> None:
    """Open the normal HH login page and wait for the actual form.

    Deliberately wait only for DOMContentLoaded. HH pages include third-party
    analytics that can keep the browser ``load`` event pending indefinitely;
    form readiness, not unrelated resources, is the condition we care about.
    """
    response = await page.goto(
        HH_WEB_LOGIN,
        timeout=30000,
        wait_until="domcontentloaded",
    )
    status = getattr(response, "status", None)
    if status is not None and status >= 400:
        if status in {403, 429, 451}:
            raise RuntimeError(
                "HH login is blocked by the site's anti-bot protection "
                f"(HTTP {status}); this is not an account-password error"
            )
        raise RuntimeError(f"HH login page returned HTTP {status}")
    # HH can first ask whether the visitor is an applicant or an employer.
    # The applicant radio is selected by default, but its explicit "Войти"
    # button must still be pressed before the credential form is rendered.
    applicant_type = page.locator(SEL_APPLICANT_ACCOUNT_TYPE)
    if await applicant_type.count():
        await applicant_type.check()
        await page.locator(SEL_ACCOUNT_TYPE_SUBMIT).click()

    # The next HH screen defaults to phone sign-in. This product receives an
    # email address, so switch explicitly before locating the username field.
    email_credential_type = page.locator(SEL_EMAIL_CREDENTIAL_TYPE)
    if await email_credential_type.count():
        await email_credential_type.check(force=True)

    try:
        await page.wait_for_selector(SEL_LOGIN_INPUT, timeout=15000, state="visible")
    except Exception as ex:
        diagnostics = await _login_page_diagnostics(page)
        raise RuntimeError(
            "HH login form did not become ready "
            f"(url={page.url}; {diagnostics})"
        ) from ex


async def _verified_web_cookies(page, context) -> list[dict]:
    """Return cookies only after HH itself proves the session is authenticated.

    A mere ``hhtoken`` cookie is insufficient because HH also issues it to
    anonymous visitors. Prefer the post-login navigation signal, then verify
    the same browser context against the applicant resumes page. A redirect
    back to /account/login means authentication did not succeed.
    """
    try:
        await page.wait_for_url(
            lambda url: not _is_auth_wall(str(url)),
            timeout=30000,
            wait_until="domcontentloaded",
        )
    except PlaywrightTimeoutError:
        # Some HH login variants may update session state before navigating.
        # The authenticated-page probe below is authoritative.
        pass

    probe = await context.new_page()
    try:
        response = await probe.goto(
            HH_SESSION_CHECK,
            timeout=30000,
            wait_until="domcontentloaded",
        )
        status = getattr(response, "status", None)
        if status in {401, 403}:
            raise RuntimeError("HH rejected the login: invalid email or password")
        if status is not None and status >= 400:
            raise RuntimeError(f"HH session validation returned HTTP {status}")
        if _is_auth_wall(probe.url):
            raise RuntimeError("HH login did not create an authenticated web session")
    finally:
        await probe.close()

    cookies = await context.cookies()
    if not cookies:
        raise RuntimeError("HH login succeeded but browser session has no cookies")
    return cookies


async def get_auth_code(
    username: str,
    password: str,
    on_captcha: Callable[[bytes], Awaitable[str]] | None = None,
    headless: bool = True,
) -> tuple[str | None, list[dict]]:
    """Log in through the normal HH web page and return ``(None, cookies)``.

    The function keeps its historical name so callers do not need a migration.
    No OAuth authorize endpoint, mobile client id, redirect URI or code exchange
    is required for the product's cookies-only data path.

    ``on_captcha`` is an async callback receiving a screenshot and returning the
    human-entered solution. If captcha appears and no callback exists, the flow
    raises RuntimeError.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            device = pw.devices["Galaxy A55"]
            context = await browser.new_context(**device)
            page = await context.new_page()

            await _open_web_login(page)
            await page.fill(SEL_LOGIN_INPUT, username)

            try:
                await page.wait_for_selector(
                    SEL_EXPAND_PASSWORD, timeout=5000, state="visible"
                )
                await page.click(SEL_EXPAND_PASSWORD)
            except Exception:
                pass  # password field may already be visible

            await _handle_captcha_if_present(page, on_captcha)

            try:
                await page.wait_for_selector(
                    SEL_PASSWORD_INPUT, timeout=15000, state="visible"
                )
            except Exception:
                try:
                    inputs = await page.evaluate(
                        "Array.from(document.querySelectorAll('input,button'))"
                        ".slice(0,40).map(e=>({tag:e.tagName,type:e.type,"
                        "name:e.name,qa:e.getAttribute('data-qa'),"
                        "text:(e.innerText||'').slice(0,40)}))"
                    )
                    logger.error(
                        "hh login: password field missing. URL=%s inputs=%s",
                        page.url,
                        inputs,
                    )
                except Exception:
                    pass
                raise

            await page.fill(SEL_PASSWORD_INPUT, password)
            await page.keyboard.press("Enter")
            await _handle_captcha_if_present(page, on_captcha)

            cookies = await _verified_web_cookies(page, context)
            return None, cookies
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
    """Log in to the normal HH web page using an email one-time code.

    Returns ``(None, cookies)``. OAuth is intentionally not part of this flow.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            device = pw.devices["Galaxy A55"]
            context = await browser.new_context(**device)
            page = await context.new_page()

            await _open_web_login(page)
            await page.fill(SEL_LOGIN_INPUT, email)
            await page.keyboard.press("Enter")

            await _handle_captcha_if_present(page, on_captcha)
            await page.wait_for_selector(
                SEL_CODE_CONTAINER, timeout=30000, state="visible"
            )

            if on_code_required is None:
                raise RuntimeError("Email code required but no handler provided")
            code = await on_code_required()

            await page.fill(SEL_PIN_CODE_INPUT, code)
            await page.keyboard.press("Enter")
            await _handle_captcha_if_present(page, on_captcha)

            cookies = await _verified_web_cookies(page, context)
            return None, cookies
        finally:
            await browser.close()
