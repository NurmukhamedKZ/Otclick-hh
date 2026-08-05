"""hh web-session data path: everything the product needs over the logged-in
web session instead of the OAuth API.

Every page hh serves carries its state as entity-encoded inline JSON (see
page_json.find_state). This module implements the handful of operations the app
actually needs as "GET the page → decode the inline state → pull the block we
need". Call sites keep their old service-function signatures.

All requests go through `_get` — the single choke point that enforces the
inter-request delay, checks `session_looks_dead` and raises `WebSessionExpired`.
Web traffic is more fingerprintable than API traffic, so the per-user delay is
at least as large as client.DEFAULT_DELAY.
"""
from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlencode

import requests

from app.hh.page_json import find_state
from app.services.form_filler import (
    WebSessionExpired,
    load_web_session,
    session_looks_dead,
)

logger = logging.getLogger(__name__)

WEB_BASE = "https://hh.ru"
SEARCH_URL = f"{WEB_BASE}/search/vacancy"

# client.DEFAULT_DELAY is the API's inter-request minimum; web traffic is not
# less fingerprintable, so we keep at least the same cadence, per user.
_MIN_DELAY_S = 0.345
_last_request_at: dict[str, float] = {}


def _get(session: requests.Session, user_id: str, url: str, **kw) -> requests.Response:
    """Single choke point: delay → request → dead-session guard.

    Raises WebSessionExpired on a login wall (401/403 or /account/login
    redirect) so a logged-out session surfaces as the existing
    `web_session_expired` notification, never as a silent empty result.
    """
    now = time.monotonic()
    wait = _last_request_at.get(user_id, 0.0) + _MIN_DELAY_S - now
    if wait > 0:
        time.sleep(wait)
    resp = session.get(url, timeout=20, **kw)
    _last_request_at[user_id] = time.monotonic()
    if session_looks_dead(resp):
        raise WebSessionExpired(f"hh rejected the web session ({resp.status_code})")
    resp.raise_for_status()
    return resp


def _normalise_vacancy(v: dict) -> dict:
    company = v.get("company") or {}
    emp = {}
    if company.get("id") is not None:
        emp = {"id": str(company["id"]), "name": company.get("name") or ""}
    return {
        "id": str(v["vacancyId"]),
        "name": v.get("name") or "",
        "employer": emp,
        "has_test": bool(v.get("userTestPresent")),
        "response_letter_required": bool(v.get("@responseLetterRequired")),
        "archived": bool(v.get("closedForApplicants")),
    }


async def search_vacancies(
    user_id: str, params: dict, page: int = 0
) -> tuple[list[dict], int]:
    """Search hh via the logged-in web session.

    Returns (vacancies, total). Each vacancy is normalised to the hh API shape
    the rest of the code already expects (id/name/employer/has_test/
    response_letter_required/archived). The same search backend backs both, so
    the query-string names are identical to the API's.
    """
    loop = asyncio.get_running_loop()
    session = await load_web_session(user_id)
    qs = {**params, "page": page}
    qs.pop("per_page", None)  # web caps items per page; nothing to set here
    url = f"{SEARCH_URL}?{urlencode(qs)}"
    resp = await loop.run_in_executor(None, _get, session, user_id, url)
    data = find_state(resp.text, "vacancySearchResult")
    items = data.get("vacancies") or []
    return [v for v in (_normalise_vacancy(i) for i in items) if v.get("id")], data.get(
        "totalResults", 0
    )
