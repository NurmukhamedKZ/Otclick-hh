"""Load full resume content for AI form-filling agent."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from typing import Literal

import requests
from langchain_core.language_models import BaseChatModel

from app.ai.prompts import (
    build_form_choice_prompt,
    build_form_text_prompt,
    sanitize_ai_text,
)
from app.config import settings
from app.db.supabase import service_client
from app.services import qa_memory
from app.services.hh_auth import decrypt_token
from app.services.hh_credentials import load_api_client, persist_if_refreshed

logger = logging.getLogger(__name__)

# Subset of apply.ApplyStatus that fill() can produce.
# "form_sent" = a test was solved + submitted (distinct from a plain "sent").
FillStatus = Literal["form_sent", "form_required", "form_pending", "failed"]

# Desktop UA for the hh.ru web session (test pages live on the desktop site).
HH_WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _load_cookies_encrypted(user_id: str) -> str | None:
    res = (
        service_client.table("hh_credentials")
        .select("web_cookies_encrypted")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    data = res.data if res else None
    return data.get("web_cookies_encrypted") if data else None


async def load_web_session(user_id: str) -> requests.Session:
    """Build a requests.Session from the stored hh.ru web cookies.

    Cookies were captured during the OAuth login (see hh/authorize.py). No
    browser, no re-login. Raises ValueError if no session is stored (the user
    connected before cookie capture existed → needs reconnect).
    """
    loop = asyncio.get_running_loop()
    enc = await loop.run_in_executor(None, _load_cookies_encrypted, user_id)
    if not enc:
        raise ValueError(f"no stored web session for user {user_id} — reconnect required")

    cookies = json.loads(decrypt_token(enc))
    session = requests.Session()
    session.headers["User-Agent"] = HH_WEB_USER_AGENT
    for c in cookies:
        session.cookies.set(
            c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/")
        )
    return session


def extract_xsrf_token(page_html: str) -> str:
    """Pull the xsrfToken out of an hh.ru page's inline JSON state."""
    marker = ',"xsrfToken":"'
    start = page_html.find(marker)
    if start == -1:  # hh entity-encodes the inline JSON (&#34;)
        page_html = html.unescape(page_html)
        start = page_html.find(marker)
    if start == -1:
        raise ValueError("xsrfToken not found in page")
    start += len(marker)
    end = page_html.find('"', start)
    return page_html[start:end]


async def _get_hh_resume_id(user_id: str, resume_row_id: str | None) -> str:
    """Pick hh_resume_id: explicit row id, else most recent synced resume."""
    loop = asyncio.get_running_loop()

    def _q():
        q = (
            service_client.table("resumes")
            .select("hh_resume_id")
            .eq("user_id", user_id)
        )
        if resume_row_id:
            q = q.eq("id", resume_row_id)
        else:
            q = q.order("synced_at", desc=True).limit(1)
        return q.execute()

    res = await loop.run_in_executor(None, _q)
    rows = res.data or []
    if not rows:
        raise ValueError(f"no resume found for user {user_id}")
    return rows[0]["hh_resume_id"]


async def load_resume(user_id: str, resume_row_id: str | None = None) -> dict:
    """Fetch full resume from hh API. Returns raw resume payload.

    resume_row_id: optional id of row in `resumes` table.
                   If None, picks most recently synced resume.
    """
    hh_resume_id = await _get_hh_resume_id(user_id, resume_row_id)

    client = await load_api_client(user_id)
    original_access = client.access_token
    loop = asyncio.get_running_loop()
    try:
        payload = await loop.run_in_executor(
            None, client.get, f"resumes/{hh_resume_id}"
        )
    finally:
        await persist_if_refreshed(user_id, client, original_access)

    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected hh resume payload: {type(payload)}")
    return payload


# --- vacancy test solving (web endpoint) -------------------------------------

_TESTS_MARKER = ',"vacancyTests":'


def _strip_tags(s: str | None) -> str:
    # Tags in the page JSON are entity-encoded (&lt;p&gt;) — unescape first.
    text = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    return re.sub(r"\s+", " ", text).strip()


def _ai_answer(chat: BaseChatModel, prompt: str) -> str:
    content = chat.invoke(prompt).content
    if isinstance(content, list):  # some models return content parts
        content = " ".join(str(c) for c in content)
    return (content or "").strip()


def _resume_summary(resume: dict) -> str:
    """Full resume text to ground LLM. No truncation — user requirement."""
    parts: list[str] = []
    if resume.get("title"):
        parts.append(f"Желаемая должность: {resume['title']}")
    if resume.get("first_name") or resume.get("last_name"):
        fio = " ".join(
            str(resume.get(k) or "") for k in ("last_name", "first_name", "middle_name")
        ).strip()
        if fio:
            parts.append(f"ФИО: {fio}")
    for k, label in (
        ("age", "Возраст"),
        ("gender", "Пол"),
        ("area", "Город"),
        ("citizenship", "Гражданство"),
        ("relocation", "Релокация"),
        ("business_trip_readiness", "Командировки"),
        ("employments", "Занятость"),
        ("schedules", "График"),
        ("total_experience", "Общий опыт"),
        ("salary", "Зарплата"),
    ):
        v = resume.get(k)
        if v:
            if isinstance(v, dict):
                v = v.get("name") or v.get("title") or v
            elif isinstance(v, list):
                v = ", ".join(
                    str((x.get("name") if isinstance(x, dict) else x) or "") for x in v
                )
            parts.append(f"{label}: {v}")
    skills = resume.get("skill_set") or []
    if skills:
        parts.append("Навыки: " + ", ".join(str(s) for s in skills))
    if resume.get("skills"):
        parts.append("О себе: " + _strip_tags(resume["skills"]))
    for e in resume.get("experience") or []:
        pos = e.get("position") or ""
        comp = e.get("company") or ""
        start = e.get("start") or ""
        end = e.get("end") or "наст.вр."
        desc = _strip_tags(e.get("description"))
        parts.append(f"Опыт ({start}–{end}): {pos} @ {comp}. {desc}".strip())
    for ed in resume.get("education", {}).get("primary", []) if isinstance(resume.get("education"), dict) else []:
        parts.append(
            f"Образование: {ed.get('name','')} — {ed.get('result','')} ({ed.get('year','')})".strip()
        )
    for lang in resume.get("language") or []:
        if isinstance(lang, dict):
            parts.append(
                f"Язык: {lang.get('name','')} — {(lang.get('level') or {}).get('name','')}".strip()
            )
    for cert in resume.get("certificate") or []:
        if isinstance(cert, dict):
            parts.append(f"Сертификат: {cert.get('title','')} ({cert.get('achieved_at','')})".strip())
    return "\n".join(parts)


def _find_balanced_object(text: str, obj_start: int) -> str:
    """Return the JSON object substring starting at text[obj_start] == '{'."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(obj_start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[obj_start:i + 1]
    raise ValueError("unbalanced vacancyTests object in page")


def _decode_page(page_html: str) -> str:
    """hh serves the inline JSON HTML-entity-encoded (&#34; instead of ") — decode.

    Only when the plain marker is absent, so already-plain pages keep their
    literal &amp; sequences intact.
    """
    return page_html if _TESTS_MARKER in page_html else html.unescape(page_html)


def _parse_tests(page_html: str, vacancy_id: str) -> dict:
    """Pull the test definition for vacancy_id out of the page's inline JSON."""
    page_html = _decode_page(page_html)
    marker_pos = page_html.find(_TESTS_MARKER)
    if marker_pos == -1:
        raise ValueError("vacancyTests block not found in page")
    obj_start = marker_pos + len(_TESTS_MARKER)
    blob = _find_balanced_object(page_html, obj_start)
    tests_data = json.loads(blob, strict=False)
    try:
        return tests_data[str(vacancy_id)]
    except KeyError as ex:
        raise ValueError(f"no test data for vacancy {vacancy_id}") from ex


def _choose_solution(
    chat: BaseChatModel | None, question: str, solutions: list, resume_ctx: str = ""
) -> str:
    """Pick a candidate solution id for a multiple-choice task, grounded in resume."""
    if chat is not None:
        options = "\n".join(
            f"{s['id']}: {_strip_tags(s.get('text'))}" for s in solutions
        )
        prompt = build_form_choice_prompt(question, options, resume_ctx)
        try:
            match = re.search(r"\d+", _ai_answer(chat, prompt))
            if match and any(str(s["id"]) == match.group(0) for s in solutions):
                return match.group(0)
        except Exception:
            logger.warning("fill: AI choose failed — using fallback", exc_info=True)
    # Fallback: prefer "да", else the middle option (statistically common).
    yes = next(
        (s for s in solutions if str(s.get("text", "")).strip().lower() == "да"),
        None,
    )
    return str(yes["id"]) if yes else str(solutions[len(solutions) // 2]["id"])


def _free_text(chat: BaseChatModel | None, question: str, resume_ctx: str = "") -> str:
    """Answer a free-text task, grounded in the candidate's resume."""
    if chat is not None:
        try:
            prompt = build_form_text_prompt(question, resume_ctx)
            # Never let an empty LLM reply become an empty submitted field.
            if answer := sanitize_ai_text(_ai_answer(chat, prompt)):
                return answer
            logger.warning("fill: empty AI free-text — using fallback")
        except Exception:
            logger.warning("fill: AI free-text failed — using fallback", exc_info=True)
    return "Да"


def _response_url(vacancy_id: str) -> str:
    return (
        f"https://hh.ru/applicant/vacancy_response?vacancyId={vacancy_id}"
        "&startedWithQuestion=false&hhtmFrom=vacancy"
    )


def _build_answers(
    test_data: dict, chat: BaseChatModel | None, resume_ctx: str
) -> list[dict]:
    answers: list[dict] = []
    for task in test_data["tasks"]:
        solutions = task.get("candidateSolutions") or []
        question = _strip_tags(task.get("description"))
        if solutions:
            sel_id = _choose_solution(chat, question, solutions, resume_ctx)
            sel_text = next(
                (_strip_tags(s.get("text")) for s in solutions if str(s["id"]) == sel_id),
                "",
            )
            answers.append({
                "task_id": task["id"],
                "question": question,
                "type": "choice",
                "options": [
                    {"id": str(s["id"]), "text": _strip_tags(s.get("text"))}
                    for s in solutions
                ],
                "answer_id": sel_id,
                "answer": sel_text,
            })
        else:
            ans = _free_text(chat, question, resume_ctx)
            answers.append({
                "task_id": task["id"],
                "question": question,
                "type": "text",
                "answer": ans,
            })
    return answers


def _solve(
    session: requests.Session,
    vacancy_id: str,
    chat: BaseChatModel | None,
    resume_ctx: str,
) -> list[dict]:
    """Fetch the test page and produce AI answers WITHOUT submitting."""
    r = session.get(_response_url(vacancy_id), timeout=15)
    r.raise_for_status()
    test_data = _parse_tests(r.text, vacancy_id)
    return _build_answers(test_data, chat, resume_ctx)


def _submit(
    session: requests.Session,
    vacancy_id: str,
    hh_resume_id: str,
    answers: list[dict],
    letter: str,
) -> requests.Response:
    """Re-fetch xsrf+test meta, build payload from approved answers, POST."""
    response_url = _response_url(vacancy_id)
    r = session.get(response_url, timeout=15)
    r.raise_for_status()
    page = r.text
    test_data = _parse_tests(page, vacancy_id)
    xsrf = extract_xsrf_token(page)

    payload: dict = {
        "_xsrf": xsrf,
        "uidPk": test_data["uidPk"],
        "guid": test_data["guid"],
        "startTime": test_data["startTime"],
        "testRequired": test_data["required"],
        "vacancy_id": vacancy_id,
        "resume_hash": hh_resume_id,
        "ignore_postponed": "true",
        "incomplete": "false",
        "mark_applicant_visible_in_vacancy_country": "false",
        "country_ids": "[]",
        "lux": "true",
        "withoutTest": "no",
        "letter": letter,
    }
    for a in answers:
        field = f"task_{a['task_id']}"
        if a.get("type") == "choice":
            payload[field] = str(a["answer_id"])
        else:
            payload[f"{field}_text"] = a.get("answer", "")

    return session.post(
        "https://hh.ru/applicant/vacancy_response/popup",
        data=payload,
        headers={
            "Referer": response_url,
            "X-Hhtmfrom": "vacancy",
            "X-Hhtmsource": "vacancy_response",
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrftoken": xsrf,
        },
        timeout=20,
    )


def _is_success(resp: requests.Response) -> bool:
    if resp.status_code != 200:
        return False
    try:
        data = resp.json()
    except ValueError:
        return False
    if isinstance(data, dict) and (data.get("error") or data.get("errors")):
        return False
    return True


async def prepare_form_answers(
    llm: BaseChatModel, user_id: str, resume_id: str, vacancy: dict
) -> tuple[FillStatus, list[dict]]:
    """Generate AI answers for a vacancy test — DO NOT submit.

    Returns ("form_pending", answers) on success so caller can persist as a
    user-approval draft. Returns ("form_required", []) on no web session, no
    resume, or fetch/parse failure (caller records as manual fallback).
    """
    vacancy_id = str(vacancy.get("id") or "")
    loop = asyncio.get_running_loop()

    try:
        session = await load_web_session(user_id)
    except ValueError as ex:
        logger.warning("fill: no web session for user %s: %s", user_id, ex)
        return "form_required", []

    try:
        await _get_hh_resume_id(user_id, resume_id)
    except ValueError as ex:
        logger.warning("fill: %s", ex)
        return "form_required", []

    chat = llm if settings.OPENAI_API_KEY else None
    resume_ctx = ""
    if chat is not None:
        try:
            resume = await load_resume(user_id, resume_id)
            resume_ctx = _resume_summary(resume)
        except Exception:
            logger.warning(
                "fill: resume load failed — answers ungrounded", exc_info=True
            )
        # User-confirmed Q&A outranks the resume for repeat questions.
        if qa := await qa_memory.prompt_block(user_id):
            resume_ctx = f"{resume_ctx}\n\n{qa}" if resume_ctx else qa

    try:
        answers = await loop.run_in_executor(
            None, _solve, session, vacancy_id, chat, resume_ctx
        )
    except Exception:
        logger.warning(
            "fill: solve failed for vacancy=%s, retrying once", vacancy_id, exc_info=True
        )
        try:
            answers = await loop.run_in_executor(
                None, _solve, session, vacancy_id, chat, resume_ctx
            )
        except Exception:
            logger.exception("fill: solve failed for vacancy=%s (retry)", vacancy_id)
            return "form_required", []

    logger.info(
        "fill: answers prepared (awaiting approval) vacancy=%s n=%d",
        vacancy_id, len(answers),
    )
    return "form_pending", answers


async def submit_prepared_form(
    user_id: str, resume_id: str, vacancy_id: str,
    answers: list[dict], letter: str = "",
) -> tuple[FillStatus, str | None]:
    """Submit previously-approved answers to hh. Re-fetches fresh xsrf each call.

    Returns (status, error). "form_sent" on accepted submit, "failed" + reason
    otherwise (network/parse error, or hh rejected).
    """
    loop = asyncio.get_running_loop()
    try:
        session = await load_web_session(user_id)
    except ValueError as ex:
        return "failed", f"no_web_session: {ex}"

    try:
        hh_resume_id = await _get_hh_resume_id(user_id, resume_id)
    except ValueError as ex:
        return "failed", f"resume_missing: {ex}"

    try:
        resp = await loop.run_in_executor(
            None, _submit, session, vacancy_id, hh_resume_id, answers, letter
        )
    except Exception as ex:
        logger.exception("fill: submit failed vacancy=%s", vacancy_id)
        return "failed", f"submit_error: {ex}"

    if _is_success(resp):
        logger.info("fill: approved answers submitted vacancy=%s", vacancy_id)
        return "form_sent", None
    body = (resp.text or "")[:300]
    logger.warning(
        "fill: submit rejected vacancy=%s status=%s body=%.300s",
        vacancy_id, resp.status_code, body,
    )
    return "failed", f"hh_rejected: {resp.status_code} {body}"