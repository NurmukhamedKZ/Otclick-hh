"""Fixtures shared by the browser end-to-end modules."""

from __future__ import annotations

import uuid

import pytest

from ._harness import Traffic, delete_user_by_email, mark_onboarded, sign_up

NAV_TIMEOUT = 30_000


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    p = context.new_page()
    p.set_default_timeout(NAV_TIMEOUT)
    traffic = Traffic()
    traffic.attach(p)
    p.traffic = traffic  # type: ignore[attr-defined]
    yield p
    context.close()


@pytest.fixture
def credentials():
    email = f"e2e-{uuid.uuid4().hex[:12]}@example.com"
    yield {"email": email, "password": f"Pw-{uuid.uuid4().hex[:16]}"}
    delete_user_by_email(email)


@pytest.fixture
def signed_in_page(page, credentials):
    sign_up(page, credentials)
    # HHBanner fires /api/hh/status on mount — wait for the app to settle.
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture(scope="module")
def module_credentials():
    email = f"e2e-ui-{uuid.uuid4().hex[:12]}@example.com"
    yield {"email": email, "password": f"Pw-{uuid.uuid4().hex[:16]}"}
    delete_user_by_email(email)


@pytest.fixture(scope="module")
def app_page(browser, module_credentials):
    """Signed in once per module, with the onboarding overlay dismissed.

    Module-scoped on purpose: a signup per test trips GoTrue's rate limit once a
    module has more than a handful of cases, which shows up as unrelated auth
    tests failing. The UI tests only read and navigate, so sharing is safe —
    anything that opens a dialog must close it (see the reset_ui autouse fixture).
    """
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    p = context.new_page()
    p.set_default_timeout(NAV_TIMEOUT)
    traffic = Traffic()
    traffic.attach(p)
    p.traffic = traffic  # type: ignore[attr-defined]

    sign_up(p, module_credentials)
    assert mark_onboarded(module_credentials["email"]), "could not clear profiles.onboarded"
    p.reload(wait_until="load")

    yield p
    context.close()
