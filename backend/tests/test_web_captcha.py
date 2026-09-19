import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

import pytest


def _fake_playwright(page_url="https://hh.ru/account/captcha?state=abc", has_widget=True):
    """A mock async_playwright() context manager whose chromium.launch()
    yields a browser/context/page chain matching Playwright's real API shape
    closely enough for web_captcha to drive it."""
    page = MagicMock()
    page.url = page_url
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock(
        side_effect=None if has_widget else TimeoutError("not found")
    )
    locator = MagicMock()
    locator.screenshot = AsyncMock(return_value=b"PNGDATA")
    page.locator.return_value = locator
    page.fill = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    context = MagicMock()
    context.add_cookies = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.cookies = AsyncMock(return_value=[{"name": "a", "value": "b"}])

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    pw_instance = MagicMock()
    pw_instance.chromium.launch = AsyncMock(return_value=browser)
    pw_instance.devices = {"Galaxy A55": {}}
    pw_instance.stop = AsyncMock()

    pw_factory = MagicMock()
    pw_factory.start = AsyncMock(return_value=pw_instance)
    return pw_factory, page, context, browser


async def test_open_for_returns_captcha_with_screenshot():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        result, screenshot = await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])

    assert result == "captcha"
    assert screenshot == b"PNGDATA"
    context.add_cookies.assert_called_once_with([])
    await web_captcha.close_for("u1")


async def test_open_for_returns_cleared_when_no_widget():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=False)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        result, screenshot = await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])

    assert result == "cleared"
    assert screenshot is None
    await web_captcha.close_for("u1")


async def test_open_for_returns_token_dead_on_login_wall():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(
        page_url="https://hh.ru/account/login", has_widget=False
    )

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        result, screenshot = await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])

    assert result == "token_dead"
    assert screenshot is None
    await web_captcha.close_for("u1")


async def test_submit_for_wrong_answer_returns_new_screenshot():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])
        result, screenshot = await web_captcha.submit_for("u1", "wrong-guess")

    assert result == "captcha"
    assert screenshot == b"PNGDATA"
    page.fill.assert_called_once()
    page.keyboard.press.assert_called_once_with("Enter")
    await web_captcha.close_for("u1")


async def test_submit_for_correct_answer_returns_cleared():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])
        page.wait_for_selector = AsyncMock(side_effect=TimeoutError("gone"))
        result, screenshot = await web_captcha.submit_for("u1", "right-answer")

    assert result == "cleared"
    assert screenshot is None
    await web_captcha.close_for("u1")


async def test_cookies_for_returns_context_cookies():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])
        cookies = await web_captcha.cookies_for("u1")

    assert cookies == [{"name": "a", "value": "b"}]
    await web_captcha.close_for("u1")


async def test_close_for_releases_semaphore_and_removes_session():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])
        assert "u1" in web_captcha._sessions
        await web_captcha.close_for("u1")

    assert "u1" not in web_captcha._sessions
    browser.close.assert_called_once()


async def test_open_for_raises_at_capacity_when_semaphore_exhausted():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        for i in range(web_captcha.MAX_CONCURRENT_CAPTCHA_BROWSERS):
            await web_captcha.open_for(f"u{i}", "https://hh.ru/account/captcha", [])

        with pytest.raises(web_captcha.AtCapacity):
            await web_captcha.open_for("u-overflow", "https://hh.ru/account/captcha", [])

        for i in range(web_captcha.MAX_CONCURRENT_CAPTCHA_BROWSERS):
            await web_captcha.close_for(f"u{i}")