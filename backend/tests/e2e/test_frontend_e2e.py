"""Browser end-to-end tests: real Chromium → Next.js frontend → Kong/GoTrue → FastAPI.

Needs the full stack up (`docker compose up -d`) and host Chromium
(`playwright install chromium`). Auto-skips when either is missing.

Written in Python/Playwright rather than @playwright/test so the whole suite stays
one `pytest` run with no extra toolchain — the frontend has no JS test setup.

Chief target: the cloud→local regression where the frontend was built with
NEXT_PUBLIC_API_URL pointing at Kong (54321) instead of the backend (8000), so every
/api/* call 404'd and hh features died. Only a browser sees that — the baked-in URL
lives in the JS bundle, not in any server-side config a unit test can read.
"""

import uuid
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_URL = "http://localhost:3000"
API_URL = "http://localhost:8000"
KONG_URL = "http://localhost:54321"
NAV_TIMEOUT = 30_000


def _load_root_env() -> dict[str, str]:
    path = REPO_ROOT / ".env"
    if not path.exists():
        return {}
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


ENV = _load_root_env()
SERVICE_ROLE_KEY = ENV.get("SERVICE_ROLE_KEY", "")


def _reachable(url: str) -> bool:
    try:
        requests.get(url, timeout=3)
        return True
    except requests.RequestException:
        return False


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not SERVICE_ROLE_KEY
    or not _reachable(FRONTEND_URL)
    or not _reachable(f"{API_URL}/health")
    or not _chromium_available(),
    reason="needs the local stack up (docker compose up -d) + playwright install chromium",
)


def _delete_user_by_email(email: str) -> None:
    headers = {"apikey": SERVICE_ROLE_KEY, "Authorization": f"Bearer {SERVICE_ROLE_KEY}"}
    res = requests.get(
        f"{KONG_URL}/auth/v1/admin/users", headers=headers, params={"per_page": 200}, timeout=10
    )
    if res.status_code != 200:
        return
    for user in res.json().get("users", []):
        if user.get("email") == email:
            requests.delete(
                f"{KONG_URL}/auth/v1/admin/users/{user['id']}", headers=headers, timeout=10
            )


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


class Traffic:
    """Records every request/response the page made, so tests can assert on wiring."""

    def __init__(self):
        self.requests: list[str] = []
        self.failures: list[tuple[str, int]] = []
        self.console_errors: list[str] = []

    def attach(self, page) -> None:
        page.on("request", lambda r: self.requests.append(r.url))
        page.on(
            "response",
            lambda r: self.failures.append((r.url, r.status)) if r.status >= 400 else None,
        )
        page.on(
            "console",
            lambda m: self.console_errors.append(m.text) if m.type == "error" else None,
        )

    def to(self, prefix: str) -> list[str]:
        return [u for u in self.requests if u.startswith(prefix)]


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
    _delete_user_by_email(email)


def _sign_up(page, creds: dict) -> None:
    page.goto(f"{FRONTEND_URL}/auth", wait_until="domcontentloaded")
    page.get_by_role("button", name="регистрация").click()
    page.locator('input[type="email"]').fill(creds["email"])
    page.locator('input[type="password"]').fill(creds["password"])
    page.get_by_role("button", name="зарегистрироваться").click()
    page.wait_for_url(f"{FRONTEND_URL}/dashboard", timeout=NAV_TIMEOUT)


@pytest.fixture
def signed_in_page(page, credentials):
    _sign_up(page, credentials)
    # HHBanner fires /api/hh/status on mount — wait for the app to settle.
    page.wait_for_load_state("networkidle")
    return page


# --- public pages ------------------------------------------------------------------


def test_landing_page_renders(page):
    page.goto(FRONTEND_URL, wait_until="domcontentloaded")

    assert page.locator("body").inner_text().strip()
    assert not [f for f in page.traffic.failures if f[1] >= 500]


def test_auth_page_has_login_and_signup_modes(page):
    page.goto(f"{FRONTEND_URL}/auth", wait_until="domcontentloaded")

    assert page.get_by_role("button", name="войти").first.is_visible()
    assert page.get_by_role("button", name="регистрация").is_visible()
    assert page.locator('input[type="email"]').is_visible()
    assert page.locator('input[type="password"]').is_visible()


def test_dashboard_redirects_anonymous_to_auth(page):
    page.goto(f"{FRONTEND_URL}/dashboard", wait_until="domcontentloaded")

    page.wait_for_url(f"{FRONTEND_URL}/auth")


# --- auth against the local GoTrue -------------------------------------------------


def test_signup_through_ui_lands_on_dashboard(page, credentials):
    _sign_up(page, credentials)

    assert page.url == f"{FRONTEND_URL}/dashboard"


def test_login_through_ui_with_existing_user(browser, page, credentials):
    _sign_up(page, credentials)

    fresh_context = browser.new_context()
    fresh = fresh_context.new_page()
    try:
        fresh.goto(f"{FRONTEND_URL}/auth", wait_until="domcontentloaded")
        fresh.locator('input[type="email"]').fill(credentials["email"])
        fresh.locator('input[type="password"]').fill(credentials["password"])
        fresh.get_by_role("button", name="войти").last.click()
        fresh.wait_for_url(f"{FRONTEND_URL}/dashboard", timeout=NAV_TIMEOUT)
    finally:
        fresh_context.close()


def test_wrong_password_shows_error_and_stays_on_auth(page, credentials):
    _sign_up(page, credentials)

    page.context.clear_cookies()
    page.goto(f"{FRONTEND_URL}/auth", wait_until="domcontentloaded")
    page.locator('input[type="email"]').fill(credentials["email"])
    page.locator('input[type="password"]').fill("definitely-not-the-password")
    page.get_by_role("button", name="войти").last.click()

    page.wait_for_timeout(2000)
    assert page.url.startswith(f"{FRONTEND_URL}/auth")


def test_auth_requests_go_to_local_kong(page, credentials):
    _sign_up(page, credentials)

    gotrue_calls = [u for u in page.traffic.to(KONG_URL) if "/auth/v1/" in u]
    assert gotrue_calls, "frontend never talked to the local GoTrue through Kong"


# --- the regression: backend base URL baked into the bundle ------------------------


def test_dashboard_calls_backend_on_port_8000(signed_in_page):
    api_calls = [u for u in signed_in_page.traffic.to(API_URL) if "/api/" in u]

    assert api_calls, "dashboard made no backend calls — NEXT_PUBLIC_API_URL is likely wrong"
    assert any("/api/hh/status" in u for u in api_calls)


def test_no_api_calls_leak_to_the_supabase_gateway(signed_in_page):
    """/api/* on 54321 is Kong, which 404s — the exact cloud→local breakage."""
    leaked = [u for u in signed_in_page.traffic.to(KONG_URL) if "/api/" in u]

    assert not leaked, f"backend calls sent to the Supabase gateway: {leaked}"


def test_hh_banner_renders_status_instead_of_api_error(signed_in_page):
    body = signed_in_page.locator("body").inner_text()

    assert "hh status:" not in body, f"HHBanner surfaced an API error: {body[:400]}"
    assert "нет связи с hh" in body, "expected the not-connected banner for a fresh user"


def test_dashboard_has_no_failing_backend_responses(signed_in_page):
    bad = [
        (url, status)
        for url, status in signed_in_page.traffic.failures
        if url.startswith(API_URL)
    ]

    assert not bad, f"backend responses failed on dashboard load: {bad}"
