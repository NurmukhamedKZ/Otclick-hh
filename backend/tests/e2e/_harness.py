"""Shared plumbing for the browser end-to-end tests.

Kept out of conftest.py so test modules can import the constants and helpers
directly; conftest.py holds only the fixtures.
"""

from __future__ import annotations

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


#: Every e2e module sets `pytestmark = requires_stack` — a mark defined in a
#: conftest does not propagate to test modules, so it is shared as a value.
requires_stack = pytest.mark.skipif(
    not SERVICE_ROLE_KEY
    or not _reachable(FRONTEND_URL)
    or not _reachable(f"{API_URL}/health")
    or not _chromium_available(),
    reason="needs the local stack up (docker compose up -d) + playwright install chromium",
)


def _admin_headers() -> dict[str, str]:
    return {
        "apikey": SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def user_id_by_email(email: str) -> str | None:
    res = requests.get(
        f"{KONG_URL}/auth/v1/admin/users",
        headers=_admin_headers(),
        params={"per_page": 200},
        timeout=10,
    )
    if res.status_code != 200:
        return None
    return next((u["id"] for u in res.json().get("users", []) if u.get("email") == email), None)


def delete_user_by_email(email: str) -> None:
    uid = user_id_by_email(email)
    if uid:
        requests.delete(
            f"{KONG_URL}/auth/v1/admin/users/{uid}", headers=_admin_headers(), timeout=10
        )


def mark_onboarded(email: str) -> bool:
    """Flip profiles.onboarded so the onboarding overlay stops covering the page.

    A fresh account renders that overlay over everything, which makes any click on
    the page below time out — every UI test needs it out of the way first.
    """
    uid = user_id_by_email(email)
    if not uid:
        return False
    res = requests.patch(
        f"{KONG_URL}/rest/v1/profiles",
        headers={**_admin_headers(), "Prefer": "return=representation"},
        params={"id": f"eq.{uid}"},
        json={"onboarded": True},
        timeout=10,
    )
    return res.status_code < 300


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


def sign_up(page, creds: dict) -> None:
    page.goto(f"{FRONTEND_URL}/auth", wait_until="domcontentloaded")
    page.get_by_role("button", name="регистрация").click()
    page.locator('input[type="email"]').fill(creds["email"])
    page.locator('input[type="password"]').fill(creds["password"])
    page.get_by_role("button", name="зарегистрироваться").click()
    page.wait_for_url(f"{FRONTEND_URL}/dashboard", timeout=NAV_TIMEOUT)
