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


class VacancyGone(Exception):
    """hh no longer serves this vacancy page (404/410) — archived or deleted."""

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
    if resp.status_code in (404, 410):
        raise VacancyGone(f"{resp.status_code} for {url}")
    resp.raise_for_status()
    return resp


def _normalise_vacancy(v: dict) -> dict:
    company = v.get("company") or {}
    emp = {}
    if company.get("id") is not None:
        emp = {"id": str(company["id"]), "name": company.get("name") or ""}
    area = v.get("area")
    links = v.get("links") or {}
    return {
        "id": str(v["vacancyId"]),
        "name": v.get("name") or "",
        "employer": emp,
        "has_test": bool(v.get("userTestPresent")),
        "response_letter_required": bool(v.get("@responseLetterRequired")),
        "archived": bool(v.get("closedForApplicants")),
        # preview fields (kept for filters preview; ignored by the producer)
        "area": {"name": area.get("name")} if isinstance(area, dict) else None,
        "salary": v.get("compensation"),
        "url": links.get("desktop"),
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


async def get_vacancy(user_id: str, vacancy_id: str) -> dict:
    """Fetch one vacancy over the web session, shaped like the old API payload.

    Two blocks matter on the page. `shortVacancy` carries the same fields the
    search results do; `applicantVacancyResponseStatuses[<id>]` is the
    per-applicant view and is the authoritative one — `test.hasTests` reflects
    the test as it stands now (the search flag can be stale), and a non-empty
    `negotiations.topicList` means this user already responded. That last one
    replaces guessing "already applied" from hh's rejection wording.

    Raises VacancyGone (404/410) and WebSessionExpired (login wall).
    """
    loop = asyncio.get_running_loop()
    session = await load_web_session(user_id)
    url = f"{WEB_BASE}/vacancy/{vacancy_id}"
    resp = await loop.run_in_executor(None, _get, session, user_id, url)

    short = find_state(resp.text, "shortVacancy")
    vacancy = _normalise_vacancy(short)

    try:
        status = find_state(resp.text, "applicantVacancyResponseStatuses").get(
            str(vacancy_id)
        ) or {}
    except ValueError:  # block absent — fall back to the search-time flags
        status = {}
    if isinstance(status.get("test"), dict):
        vacancy["has_test"] = bool(status["test"].get("hasTests"))
    topics = (status.get("negotiations") or {}).get("topicList") or []
    vacancy["already_responded"] = bool(topics)
    return vacancy
