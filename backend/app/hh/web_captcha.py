"""Solves hh's own image captcha (the same widget authorize.py already
handles during OAuth login) against the worker's own stored web session —
not the user's personal browser, which holds a different cookie jar and
never actually clears the wall the worker is stuck behind.

One live headless Chromium per captcha-walled user, held in this module's
process-local registry for the duration of the pause (app/worker/runner.py
owns when to open/close it). Capped globally so N simultaneous captchas
can't spin unbounded browsers on one host.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.hh.authorize import SEL_CAPTCHA_IMAGE, SEL_CAPTCHA_INPUT

logger = logging.getLogger(__name__)

# ponytail: fixed global cap, not measured against real Chromium memory/CPU
# cost — tune (or split per-plan/tier) once real concurrent-captcha usage is
# observed.
MAX_CONCURRENT_CAPTCHA_BROWSERS = 4
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CAPTCHA_BROWSERS)


class AtCapacity(Exception):
    """No free captcha-browser slot right now — caller should back off and retry."""


@dataclass
class _Session:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page


_sessions: dict[str, _Session] = {}


async def _read_challenge(page: Page) -> tuple[str, bytes | None]:
    """hh answers one of three ways once we're on/near /account/captcha:
    still logged in but blocked (captcha widget), a login wall (dead
    session), or nothing at all (the wall already lifted)."""
    if "/account/login" in (page.url or ""):
        return "token_dead", None
    try:
        await page.wait_for_selector(SEL_CAPTCHA_IMAGE, timeout=3000, state="visible")
    except Exception:
        return "cleared", None
    screenshot = await page.locator(SEL_CAPTCHA_IMAGE).screenshot()
    return "captcha", screenshot


async def open_for(user_id: str, challenge_url: str, cookies: list[dict]) -> tuple[str, bytes | None]:
    """Launch a headless Chromium loaded with `cookies`, navigate to
    challenge_url, report what's there. Raises AtCapacity if the global
    semaphore is exhausted — caller should back off and retry later."""
    if _semaphore.locked():
        raise AtCapacity(user_id)
    await _semaphore.acquire()
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        device = pw.devices["Galaxy A55"]
        context = await browser.new_context(**device)
        await context.add_cookies(cookies)
        page = await context.new_page()
        _sessions[user_id] = _Session(playwright=pw, browser=browser, context=context, page=page)
    except Exception:
        await pw.stop()
        _semaphore.release()
        raise

    await page.goto(challenge_url, timeout=30000, wait_until="load")
    return await _read_challenge(page)


async def submit_for(user_id: str, solution: str) -> tuple[str, bytes | None]:
    """Type the answer into the open session's captcha input and re-read."""
    page = _sessions[user_id].page
    await page.fill(SEL_CAPTCHA_INPUT, solution)
    await page.keyboard.press("Enter")
    await page.wait_for_load_state("load", timeout=15000)
    return await _read_challenge(page)


async def cookies_for(user_id: str) -> list[dict]:
    """Refreshed cookies from the open session — call only after "cleared"."""
    return await _sessions[user_id].context.cookies()


async def close_for(user_id: str) -> None:
    sess = _sessions.pop(user_id, None)
    if not sess:
        return
    try:
        await sess.browser.close()
    finally:
        await sess.playwright.stop()
        _semaphore.release()