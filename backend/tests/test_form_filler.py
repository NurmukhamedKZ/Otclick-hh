import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Set required env BEFORE importing app modules
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault(
    "FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc="
)


def _fluent(return_data):
    """Fluent MagicMock for chained Supabase calls ending in .execute()."""
    m = MagicMock()
    m.table.return_value = m
    m.select.return_value = m
    m.eq.return_value = m
    m.maybe_single.return_value = m
    m.execute.return_value = MagicMock(data=return_data)
    return m


def test_strip_tags_unescapes_entities():
    from app.services.form_filler import _strip_tags

    assert _strip_tags("&lt;p&gt;Есть ли опыт?&lt;/p&gt;") == "Есть ли опыт?"
    assert _strip_tags("<b>raw</b>  tags") == "raw tags"
    assert _strip_tags(None) == ""


def test_resume_summary():
    from app.services.form_filler import _resume_summary

    resume = {
        "title": "Python разработчик",
        "skill_set": ["Python", "FastAPI", "PostgreSQL"],
        "skills": "<p>Бэкенд 5 лет</p>",
        "experience": [
            {"position": "Backend dev", "company": "Acme",
             "description": "<p>Сервисы на FastAPI</p>"},
        ],
    }
    out = _resume_summary(resume)
    assert "Python разработчик" in out
    assert "FastAPI" in out
    assert "Бэкенд 5 лет" in out  # tags stripped
    assert "Backend dev @ Acme" in out
    assert "<p>" not in out


def test_extract_xsrf_token():
    from app.services.form_filler import extract_xsrf_token

    html = 'foo,"xsrfToken":"abc123def","counters":{}'
    assert extract_xsrf_token(html) == "abc123def"


def test_extract_xsrf_token_missing():
    from app.services.form_filler import extract_xsrf_token

    with pytest.raises(ValueError):
        extract_xsrf_token("<html>no token here</html>")


@pytest.mark.asyncio
async def test_load_web_session_builds_cookies():
    from app.services import form_filler
    from app.services.hh_auth import encrypt_token

    cookies = [
        {"name": "_xsrf", "value": "tok", "domain": ".hh.ru", "path": "/"},
        {"name": "hhuid", "value": "uid123", "domain": ".hh.ru", "path": "/"},
    ]
    enc = encrypt_token(json.dumps(cookies))
    fake = _fluent({"web_cookies_encrypted": enc})

    with patch.object(form_filler, "service_client", fake):
        session = await form_filler.load_web_session("user-1")

    assert session.cookies.get("_xsrf") == "tok"
    assert session.cookies.get("hhuid") == "uid123"


@pytest.mark.asyncio
async def test_load_web_session_no_cookies_raises():
    from app.services import form_filler

    fake = _fluent({"web_cookies_encrypted": None})
    with patch.object(form_filler, "service_client", fake), pytest.raises(ValueError):
        await form_filler.load_web_session("user-1")


def test_parse_tests_extracts_vacancy_block():
    from app.services.form_filler import _parse_tests

    page = (
        'window.state={"foo":1,"vacancyTests":'
        '{"999":{"uidPk":"u","guid":"g",'
        '"startTime":123,"required":true,"tasks":[]}}'
        ',"otherField":{"y":2},"counters":{"x":1}};'
    )
    td = _parse_tests(page, "999")
    assert td["uidPk"] == "u"
    assert td["required"] is True


def test_parse_tests_entity_encoded_page():
    """hh serves the inline JSON with &#34; instead of " — must still parse."""
    from app.services.form_filler import _parse_tests, extract_xsrf_token

    page = (
        'window.state={&#34;foo&#34;:1,&#34;xsrfToken&#34;:&#34;XT&#34;,&#34;vacancyTests&#34;:'
        '{&#34;999&#34;:{&#34;uidPk&#34;:&#34;u&#34;,&#34;guid&#34;:&#34;g&#34;,'
        '&#34;startTime&#34;:123,&#34;required&#34;:true,&#34;tasks&#34;:[]}}};'
    )
    assert _parse_tests(page, "999")["uidPk"] == "u"
    assert extract_xsrf_token(page) == "XT"


def test_parse_tests_missing_raises():
    from app.services.form_filler import _parse_tests

    with pytest.raises(ValueError):
        _parse_tests("<html>nothing</html>", "1")


def test_choose_solution_fallback_prefers_da():
    from app.services.form_filler import _choose_solution

    solutions = [{"id": 10, "text": "Нет"}, {"id": 20, "text": "Да"}]
    assert _choose_solution(None, "q?", solutions) == "20"


def test_choose_solution_fallback_middle_when_no_da():
    from app.services.form_filler import _choose_solution

    solutions = [{"id": 1, "text": "a"}, {"id": 2, "text": "b"}, {"id": 3, "text": "c"}]
    assert _choose_solution(None, "q?", solutions) == "2"


def test_free_text_empty_ai_answer_raises():
    from app.services.form_filler import _free_text

    chat = MagicMock()
    chat.invoke.return_value = MagicMock(content="   ")
    # Раньше отдавался "Да" — на «желаемый доход» это мусор в черновике.
    with pytest.raises(ValueError):
        _free_text(chat, "q?")


def test_choose_solution_ai_picks_valid_id():
    from app.services.form_filler import _choose_solution

    chat = MagicMock()
    chat.invoke.return_value = MagicMock(content="Ответ: 20")
    solutions = [{"id": 10, "text": "Нет"}, {"id": 20, "text": "Да"}]
    assert _choose_solution(chat, "q?", solutions) == "20"


def test_choose_solution_ai_invalid_id_falls_back():
    from app.services.form_filler import _choose_solution

    chat = MagicMock()
    chat.invoke.return_value = MagicMock(content="999")  # not an option
    solutions = [{"id": 10, "text": "Нет"}, {"id": 20, "text": "Да"}]
    assert _choose_solution(chat, "q?", solutions) == "20"  # fallback → "да"


def test_is_success():
    from app.services.form_filler import _is_success

    ok = MagicMock(status_code=200)
    ok.json.return_value = {"negotiation": {"id": 1}}
    assert _is_success(ok) is True

    err = MagicMock(status_code=200)
    err.json.return_value = {"error": "bad"}
    assert _is_success(err) is False

    bad = MagicMock(status_code=403)
    assert _is_success(bad) is False


@pytest.mark.asyncio
async def test_prepare_no_session_returns_form_required():
    from app.services import form_filler

    fake = _fluent({"web_cookies_encrypted": None})
    with patch.object(form_filler, "service_client", fake):
        status, answers = await form_filler.prepare_form_answers(
            MagicMock(), "user-1", "r-uuid", {"id": "777"}
        )
    assert status == "form_required"
    assert answers == []


def test_solve_collects_answers_without_submitting():
    from app.services.form_filler import _solve

    td = {
        "777": {
            "uidPk": "u", "guid": "g", "startTime": 1, "required": True,
            "tasks": [
                {"id": 11, "description": "Готовы переехать?",
                 "candidateSolutions": [{"id": 1, "text": "Да"}, {"id": 2, "text": "Нет"}]},
                {"id": 12, "description": "Расскажите о себе", "candidateSolutions": []},
            ],
        }
    }
    page = (
        'pre,"xsrfToken":"XT","vacancyTests":'
        + json.dumps(td) + ',"counters":{}'
    )

    get_resp = MagicMock(status_code=200, text=page)
    session = MagicMock()
    session.get.return_value = get_resp

    chat = MagicMock()
    chat.invoke.return_value = MagicMock(content="Опыт 5 лет в бэкенде.")
    answers = _solve(session, "777", chat=chat, resume_ctx="")

    session.post.assert_not_called()
    assert len(answers) == 2

    choice = answers[0]
    assert choice["type"] == "choice"
    assert choice["question"] == "Готовы переехать?"
    assert choice["answer"] in ("Да", "Нет")
    assert {"id": "2", "text": "Нет"} in choice["options"]

    text = answers[1]
    assert text["type"] == "text"
    assert text["answer"] == "Опыт 5 лет в бэкенде."


def test_solve_raises_without_llm_on_free_text():
    """Без LLM свободный вопрос не заполняется мусором — весь тест уходит в form_required."""
    from app.services.form_filler import _solve

    td = {
        "777": {
            "uidPk": "u", "guid": "g", "startTime": 1, "required": True,
            "tasks": [{"id": 12, "description": "Желаемый доход", "candidateSolutions": []}],
        }
    }
    page = 'pre,"xsrfToken":"XT","vacancyTests":' + json.dumps(td) + ',"counters":{}'
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200, text=page)

    with pytest.raises(ValueError):
        _solve(session, "777", chat=None, resume_ctx="")


def test_submit_posts_approved_answers():
    from app.services.form_filler import _submit

    td = {
        "777": {
            "uidPk": "u", "guid": "g", "startTime": 1, "required": True,
            "tasks": [],
        }
    }
    page = (
        'pre,"xsrfToken":"XT","vacancyTests":'
        + json.dumps(td) + ',"counters":{}'
    )
    get_resp = MagicMock(status_code=200, text=page)
    post_resp = MagicMock(status_code=200)
    session = MagicMock()
    session.get.return_value = get_resp
    session.post.return_value = post_resp

    answers = [
        {"task_id": 11, "type": "choice", "answer_id": "1", "answer": "Да"},
        {"task_id": 12, "type": "text", "answer": "Привет"},
    ]
    resp = _submit(session, "777", "hh-r", answers, letter="L")
    assert resp is post_resp
    posted = session.post.call_args.kwargs["data"]
    assert posted["task_11"] == "1"
    assert posted["task_12_text"] == "Привет"
    assert posted["resume_hash"] == "hh-r"
    assert posted["letter"] == "L"


def test_plain_response_payload_omits_test_only_fields():
    from app.services.form_filler import _response_payload

    payload = _response_payload(
        vacancy_id="42", hh_resume_id="hr", xsrf="XT",
        letter="hi", test_data=None, answers=None,
    )
    assert payload["vacancy_id"] == "42"
    assert payload["letter"] == "hi"
    assert payload["letterRequired"] == "true"
    for key in ("_xsrf", "uidPk", "guid", "startTime", "testRequired"):
        assert key not in payload
    # field set matches the captured real no-test POST exactly.
    assert set(payload) == {
        "resume_hash", "vacancy_id", "letterRequired", "lux",
        "ignore_postponed", "mark_applicant_visible_in_vacancy_country",
        "country_ids", "letter",
    }


def test_answer_payload_adds_test_meta_and_tasks():
    from app.services.form_filler import _response_payload

    test_data = {"uidPk": "u", "guid": "g", "startTime": 1, "required": True}
    answers = [
        {"task_id": 11, "type": "choice", "answer_id": "1", "answer": "Да"},
        {"task_id": 12, "type": "text", "answer": "Привет"},
    ]
    payload = _response_payload(
        "42", "hr", "XT", letter="", test_data=test_data, answers=answers
    )
    assert payload["uidPk"] == "u"
    assert payload["testRequired"] is True
    assert payload["task_11"] == "1"
    assert payload["task_12_text"] == "Привет"
    # no letter → not sent, matching the real captured payload
    assert "letter" not in payload
    assert payload["letterRequired"] == "false"


@pytest.mark.asyncio
async def test_submit_response_plain_posts_without_test_fields(monkeypatch):
    """The Task 5 regression: an answers=None apply must not send the test-only
    keys (uidPk/guid/startTime/testRequired) — those only exist for tests."""
    from app.services import form_filler

    captured = {}

    def _fake_post(session, response_url, xsrf, payload):
        captured["payload"] = payload
        captured["xsrf_header"] = xsrf
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {"negotiation": {"id": 1}}
        ok.text = ""
        return ok

    async def _fake_session(user_id):
        return MagicMock()

    async def _fake_hh_resume(user_id, resume_row_id):
        return "hr"

    monkeypatch.setattr(form_filler, "_post_response", _fake_post)
    monkeypatch.setattr(form_filler, "load_web_session", _fake_session)
    monkeypatch.setattr(form_filler, "_get_hh_resume_id", _fake_hh_resume)

    status, error = await form_filler.submit_response("u1", "r1", "42", letter="hi", answers=None)

    assert status == "sent"
    assert error is None
    body = captured["payload"]
    assert body["vacancy_id"] == "42" and body["letter"] == "hi"
    for test_only in ("uidPk", "guid", "startTime", "testRequired"):
        assert test_only not in body
    assert captured["xsrf_header"] is not None
