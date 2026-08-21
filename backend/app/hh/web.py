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


class CaptchaRequired(Exception):
    """hh redirected the web session to a captcha wall (/account/captcha)."""

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
    if "/account/captcha" in (resp.url or ""):
        raise CaptchaRequired("hh redirected the web session to a captcha wall")
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


def _hh_string(value) -> str:
    """hh wraps resume text fields as [{"string": "..."}]. Flatten to a string."""
    if isinstance(value, list):
        return " ".join(
            str(v.get("string") or "") if isinstance(v, dict) else str(v) for v in value
        ).strip()
    return str(value or "")


async def list_resumes(user_id: str) -> list[dict]:
    """The user's resumes, shaped like the old /resumes/mine items.

    `_attributes.hash` is the id every other hh surface uses (it is what
    `resume_hash` in the apply POST expects), NOT `_attributes.id`.
    """
    loop = asyncio.get_running_loop()
    session = await load_web_session(user_id)
    resp = await loop.run_in_executor(
        None, _get, session, user_id, f"{WEB_BASE}/applicant/resumes"
    )
    out: list[dict] = []
    for r in find_state(resp.text, "applicantResumes") or []:
        attrs = r.get("_attributes") or {}
        if not attrs.get("hash"):
            continue
        out.append({
            "id": str(attrs["hash"]),
            "title": _hh_string(r.get("title")),
            "status": attrs.get("publishState"),
        })
    return out


# hh's web wording → the literals analytics_summary() and the UI expect.
# Anything unmapped falls through lowercased rather than being dropped, so a
# new hh state shows up in the data instead of silently reading as "no reply".
_STATE_MAP = {
    "RESPONSE": "response",
    "INVITATION": "invitation",
    "INTERVIEW": "invitation",
    "DISCARD": "discard",
}


async def list_negotiations(user_id: str, page: int = 0) -> list[dict]:
    """Negotiation states, shaped like negotiation_sync._rows_from_items output.

    employer_name is not on this page (only employerId), so it stays None —
    apply_one already fills it on new rows.
    """
    loop = asyncio.get_running_loop()
    session = await load_web_session(user_id)
    url = f"{WEB_BASE}/applicant/negotiations?{urlencode({'page': page})}"
    resp = await loop.run_in_executor(None, _get, session, user_id, url)

    out: list[dict] = []
    for t in find_state(resp.text, "topicList") or []:
        vid = t.get("vacancyId")
        if not vid:
            continue
        raw = str(t.get("lastState") or "")
        out.append({
            "vacancy_id": str(vid),
            "state": _STATE_MAP.get(raw, raw.lower() or None),
            "viewed": bool(t.get("viewedByOpponent")),
            "employer_name": None,
        })
    return out


# The API served these as {"name": "Мужской"}; the web page has only the enum.
# The summary is LLM grounding, so "Пол: male" is a small but real quality loss.
_ENUM_RU = {
    "male": "мужской",
    "female": "женский",
    "relocation_possible": "возможна",
    "relocation_impossible": "невозможна",
    "relocation_no": "невозможна",
    "ready": "готов",
    "never": "не готов",
    "sometimes": "иногда",
}


def _months_human(months) -> str | None:
    """22 → "1 г. 10 мес.". The API gave a {"months": n} dict; the summary
    prints whatever it gets, so render it here rather than leak a raw number."""
    try:
        m = int(months)
    except (TypeError, ValueError):
        return None
    years, rest = divmod(m, 12)
    parts = ([f"{years} г."] if years else []) + ([f"{rest} мес."] if rest else [])
    return " ".join(parts) or None


async def get_resume(user_id: str, hh_resume_id: str) -> dict:
    """One full resume, mapped onto the API shape form_filler._resume_summary reads.

    hh wraps scalars as [{"string": value}] and keeps the rich blocks as lists
    of objects. Fields that survive only as numeric ids on this page (area,
    language) are DROPPED rather than mapped: the summary grounds an LLM, and
    "Город: 160" is worse for the answer than no city at all.
    """
    loop = asyncio.get_running_loop()
    session = await load_web_session(user_id)
    resp = await loop.run_in_executor(
        None, _get, session, user_id, f"{WEB_BASE}/resume/{hh_resume_id}"
    )
    r = find_state(resp.text, "applicantResume")

    out: dict = {}
    for src, dst in (
        ("title", "title"),
        ("firstName", "first_name"),
        ("lastName", "last_name"),
        ("middleName", "middle_name"),
        ("gender", "gender"),
        ("skills", "skills"),
        ("relocation", "relocation"),
        ("businessTripReadiness", "business_trip_readiness"),
    ):
        if value := _hh_string(r.get(src)):
            out[dst] = _ENUM_RU.get(value, value)

    if total := _months_human(_hh_string(r.get("totalExperience"))):
        out["total_experience"] = total

    if skills := [s.get("string") for s in (r.get("keySkills") or []) if isinstance(s, dict)]:
        out["skill_set"] = [s for s in skills if s]

    experience = [
        {
            "position": e.get("position"),
            "company": e.get("companyName"),
            "start": e.get("startDate"),
            "end": e.get("endDate"),
            "description": e.get("description"),
        }
        for e in (r.get("experience") or [])
        if isinstance(e, dict)
    ]
    if experience:
        out["experience"] = experience

    education = [
        {
            "name": e.get("name"),
            "organization": e.get("organization"),
            "result": e.get("result"),
            "year": e.get("year"),
        }
        for e in (r.get("primaryEducation") or [])
        if isinstance(e, dict)
    ]
    if education:
        out["education"] = {"primary": education}

    return out
