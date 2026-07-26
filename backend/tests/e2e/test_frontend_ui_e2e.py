"""Browser end-to-end tests for app UI behaviour.

Regression cover for defects found reviewing the UI/UX overhaul. Every case here
failed against the code as first written, and none of them is observable without a
real browser — they are about URL/history state, keyboard layout, and focus.

Needs the full stack up (`docker compose up -d`) and host Chromium; auto-skips
otherwise. Fixtures live in conftest.py, shared helpers in _harness.py.
"""

import re

import pytest

from ._harness import API_URL, FRONTEND_URL, requires_stack

pytestmark = requires_stack


@pytest.fixture(autouse=True)
def reset_ui(app_page):
    """The signed-in page is shared across this module, so leave no dialog open."""
    yield
    app_page.keyboard.press("Escape")

SEARCH = 'input[placeholder="vacancy_id, employer_id…"]'
PALETTE = '[role="dialog"][aria-label="Командная палитра"]'
DEBOUNCE_SETTLE_MS = 900  # the search debounce is 300ms; outlive it comfortably


def open_app(page, route: str):
    """Navigate and wait until the app shell is up.

    Deliberately not `networkidle`: the worker bar polls /api/worker/status every
    5s and the realtime socket retries on a loop, so that state can never settle
    reliably. Waiting for the sidebar is both sufficient and stable.
    """
    page.goto(f"{FRONTEND_URL}{route}", wait_until="load")
    page.get_by_role("navigation", name="Основная навигация").wait_for(state="visible")
    return page


def retry_until(action, check, attempts: int = 20, message: str = "condition never held"):
    """Repeat `action` until `check` passes.

    Interactions that depend on a React event handler are silently dropped when
    they land before hydration, and there is no event to wait on for that.
    """
    for _ in range(attempts):
        action()
        try:
            check(1000)
            return
        except Exception:
            continue
    raise AssertionError(message)


def open_palette(page, press=None):
    press = press or (lambda: page.keyboard.press("Control+k"))
    retry_until(
        press,
        lambda ms: page.locator(PALETTE).wait_for(state="visible", timeout=ms),
        message="the command palette never opened",
    )


# --- /applications URL state -------------------------------------------------------


def test_typing_reflects_into_the_url(app_page):
    open_app(app_page, "/applications")
    app_page.wait_for_selector(SEARCH)

    retry_until(
        lambda: app_page.locator(SEARCH).fill("zzznomatch"),
        lambda ms: app_page.wait_for_url("**/applications?q=zzznomatch", timeout=ms),
        message="typing never reached the URL",
    )


def test_reset_clears_the_query_and_it_stays_cleared(app_page):
    """The debounce used to push the stale input back 300ms after the reset."""
    open_app(app_page, "/applications?status=failed&q=zzznomatch")
    app_page.wait_for_selector(SEARCH)

    retry_until(
        lambda: app_page.get_by_role("button", name=re.compile("Сбросить")).click(),
        lambda ms: app_page.wait_for_url("**/applications", timeout=ms),
        message="reset never cleared the URL",
    )
    app_page.wait_for_timeout(DEBOUNCE_SETTLE_MS)

    assert "q=" not in app_page.url, f"reset was undone: {app_page.url}"
    assert "status=" not in app_page.url, f"reset was undone: {app_page.url}"
    assert app_page.locator(SEARCH).input_value() == ""


def test_back_button_steps_through_filter_tabs(app_page):
    """Tab choices push history; only the debounced query replaces it."""
    open_app(app_page, "/applications")
    app_page.wait_for_selector(SEARCH)

    retry_until(
        lambda: app_page.locator('[role="tab"]', has_text="ошибки").first.click(),
        lambda ms: app_page.wait_for_url("**/applications?status=failed", timeout=ms),
        message="the status tab never changed the URL",
    )
    app_page.locator('[role="tab"]', has_text="капча").first.click()
    app_page.wait_for_url("**/applications?status=captcha", timeout=10_000)

    app_page.go_back()
    app_page.wait_for_timeout(DEBOUNCE_SETTLE_MS)

    assert app_page.url.endswith("/applications?status=failed")


def test_a_shared_filter_link_restores_that_exact_view(app_page):
    open_app(app_page, "/applications?status=captcha&q=abc&p=2")
    app_page.wait_for_selector(SEARCH)
    app_page.wait_for_timeout(DEBOUNCE_SETTLE_MS)

    assert app_page.locator(SEARCH).input_value() == "abc"
    selected = app_page.locator('[role="tab"][aria-selected="true"]')
    assert "капча" in selected.inner_text()
    # the view survived the debounce instead of being rewritten by it
    assert "status=captcha" in app_page.url and "q=abc" in app_page.url


# --- command palette ---------------------------------------------------------------


def _press_ctrl_k_as_cyrillic_layout(page) -> None:
    """Dispatch what a Russian layout actually sends: key "л", code "KeyK".

    page.keyboard.press("Control+k") always reports code KeyK *and* key "k", so it
    cannot catch a handler that matches on e.key — this can.
    """
    cdp = page.context.new_cdp_session(page)
    for event in ("keyDown", "keyUp"):
        cdp.send(
            "Input.dispatchKeyEvent",
            {
                "type": event,
                "key": "л",
                "code": "KeyK",
                "windowsVirtualKeyCode": 75,
                "nativeVirtualKeyCode": 75,
                "modifiers": 2,  # Ctrl
            },
        )


def test_palette_opens_under_a_cyrillic_keyboard_layout(app_page):
    # retrying only covers hydration timing: a handler matching on e.key would
    # never see "л" no matter how many times the event is dispatched
    open_palette(app_page, press=lambda: _press_ctrl_k_as_cyrillic_layout(app_page))


def test_palette_traps_focus(app_page):
    """aria-modal only tells assistive tech the rest is unavailable; Tab still walks."""
    open_palette(app_page)

    for i in range(8):
        app_page.keyboard.press("Tab")
        inside = app_page.evaluate(
            """(sel) => {
                const d = document.querySelector(sel);
                return !!d && d.contains(document.activeElement);
            }""",
            PALETTE,
        )
        assert inside, f"focus escaped the dialog after {i + 1} Tab(s)"


def test_palette_closes_on_escape_and_restores_focus(app_page):
    trigger = app_page.get_by_role("button", name=re.compile("поиск"))
    open_palette(app_page, press=lambda: trigger.first.click())

    app_page.keyboard.press("Escape")

    app_page.locator(PALETTE).wait_for(state="hidden", timeout=10_000)
    assert app_page.evaluate(
        "() => document.activeElement && document.activeElement.textContent.includes('поиск')"
    ), "focus was not returned to the trigger"


def test_palette_navigates_to_the_chosen_route(app_page):
    open_app(app_page, "/dashboard")
    open_palette(app_page)

    app_page.locator('[role="option"]', has_text="Уведомления").first.click()

    app_page.wait_for_url(f"{FRONTEND_URL}/notifications", timeout=10_000)


# --- navigation shell --------------------------------------------------------------


def test_sidebar_items_are_labelled_and_mark_the_current_route(app_page):
    open_app(app_page, "/applications")

    nav = app_page.get_by_role("navigation", name="Основная навигация")
    for label in ("Главная", "Отклики", "Чаты", "Todo", "Уведомления", "Аккаунт"):
        assert nav.get_by_role("link", name=label).count() >= 1, f"missing nav item: {label}"

    current = nav.locator('[aria-current="page"]')
    assert current.count() == 1
    assert "Отклики" in current.inner_text()


def test_every_app_page_has_one_heading_and_a_way_back(app_page):
    for route, title in (
        ("/dashboard", "Главная"),
        ("/applications", "Отклики"),
        ("/chats", "Чаты"),
        ("/todo", "Todo"),
        ("/notifications", "Уведомления"),
        ("/account", "Аккаунт"),
        ("/billing", "Подписка"),
    ):
        open_app(app_page, route)
        heading = app_page.get_by_role("heading", level=1)
        assert heading.count() == 1, f"{route} has {heading.count()} h1 elements"
        assert title in heading.inner_text(), f"{route} heading is {heading.inner_text()!r}"
        crumbs = app_page.get_by_role("navigation", name="Хлебные крошки")
        assert crumbs.count() == 1, f"{route} has no breadcrumbs"
        if route != "/dashboard":
            assert crumbs.get_by_role("link", name="Главная").count() == 1


def test_badge_sources_are_not_refetched_on_client_side_navigation(app_page):
    """The badge hooks share react-query entries; remounting must not refetch them.

    Counted over the whole session rather than from an arbitrary point: the initial
    client-side fetch fires after hydration, which is not an event we can wait on,
    so the invariant is "fetched once in total", not "zero after some marker".
    """
    seen: list[str] = []
    app_page.on("request", lambda r: seen.append(r.url))
    open_app(app_page, "/dashboard")

    nav = app_page.get_by_role("navigation", name="Основная навигация")
    for label, route in (
        ("Отклики", "/applications"),
        ("Todo", "/todo"),
        ("Уведомления", "/notifications"),
        ("Аккаунт", "/account"),
        ("Главная", "/dashboard"),
    ):
        retry_until(
            lambda label=label: nav.get_by_role("link", name=label).first.click(),
            lambda ms, route=route: app_page.wait_for_url(f"**{route}", timeout=ms),
            message=f"nav to {route} never happened",
        )
        app_page.wait_for_timeout(600)

    for endpoint in ("/api/forms/drafts", "/api/recruiter/drafts", "/api/recruiter/todos"):
        hits = [u for u in seen if endpoint in u]
        assert len(hits) <= 1, (
            f"{endpoint} fetched {len(hits)}x across 6 page views — the shared "
            f"react-query entry is not being reused"
        )


def test_unconnected_account_does_not_call_the_chats_endpoint(app_page):
    """/api/chats 409s without an hh web session — the badge must not ask for it.

    Recorded per navigation rather than off the shared page-level Traffic, because
    the /chats page itself legitimately fetches chats and other tests visit it.
    """
    seen: list[str] = []
    app_page.on("request", lambda r: seen.append(r.url))
    open_app(app_page, "/dashboard")
    app_page.wait_for_timeout(1500)

    chat_calls = [u for u in seen if u.startswith(API_URL) and "/api/chats" in u]

    assert not chat_calls, f"called chats without an hh connection: {chat_calls}"


# --- todo section links ------------------------------------------------------------


def test_todo_section_links_are_links_not_fake_tabs(app_page):
    """All three sections stay on screen, so tab/tabpanel semantics would lie."""
    open_app(app_page, "/todo")

    nav = app_page.get_by_role("navigation", name="Разделы Todo")
    assert nav.get_by_role("tab").count() == 0
    for label in ("Анкеты", "Черновики", "Задачи"):
        assert nav.get_by_role("link", name=re.compile(label)).count() == 1


def test_todo_hash_link_marks_the_matching_section(app_page):
    open_app(app_page, "/todo#drafts")
    app_page.wait_for_timeout(500)

    nav = app_page.get_by_role("navigation", name="Разделы Todo")
    current = nav.locator("[aria-current]")
    assert current.count() == 1
    assert "Черновики" in current.inner_text()
    assert app_page.locator("#drafts").count() == 1
