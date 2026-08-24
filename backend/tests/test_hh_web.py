import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

SEARCH_PAGE = (
    '<html>{&#34;vacancySearchResult&#34;:{&#34;totalResults&#34;:2,&#34;vacancies&#34;:['
    '{&#34;vacancyId&#34;:1,&#34;name&#34;:&#34;Python dev&#34;,'
    '&#34;company&#34;:{&#34;id&#34;:9,&#34;name&#34;:&#34;Acme&#34;},'
    '&#34;userTestPresent&#34;:true,&#34;@responseLetterRequired&#34;:false,'
    '&#34;closedForApplicants&#34;:false}]}}</html>'
)


def _fake_get(page_text, status=200):
    def _get(session, user_id, url, **kw):
        if status in (401, 403):
            from app.services.form_filler import WebSessionExpired

            raise WebSessionExpired("hh rejected the web session")
        return SimpleNamespace(text=page_text, status_code=status, url=url)

    return _get


@pytest.mark.asyncio
async def test_search_normalises_web_json_to_the_api_shape(monkeypatch):
    from app.hh import web

    async def _load_web_session(_user_id):
        return SimpleNamespace()

    monkeypatch.setattr(web, "_get", _fake_get(SEARCH_PAGE))
    monkeypatch.setattr(web, "load_web_session", _load_web_session)
    vacancies, total = await web.search_vacancies("u1", {"text": "python"})

    assert total == 2
    v = vacancies[0]
    assert v["id"] == "1"
    assert v["name"] == "Python dev"
    assert v["employer"] == {"id": "9", "name": "Acme"}
    assert v["has_test"] is True
    assert v["response_letter_required"] is False
    assert v["archived"] is False


@pytest.mark.asyncio
async def test_search_raises_web_session_expired_on_a_login_wall(monkeypatch):
    from app.hh import web
    from app.services.form_filler import WebSessionExpired

    async def _load_web_session(_user_id):
        return SimpleNamespace()

    monkeypatch.setattr(web, "_get", _fake_get("", status=403))
    monkeypatch.setattr(web, "load_web_session", _load_web_session)
    with pytest.raises(WebSessionExpired):
        await web.search_vacancies("u1", {"text": "python"})


def test_normalise_vacancy_handles_missing_company():
    from app.hh.web import _normalise_vacancy

    v = _normalise_vacancy({"vacancyId": 7, "name": "X", "company": {}})
    assert v["id"] == "7"
    assert v["employer"] == {}


VACANCY_PAGE = (
    '<html>{&#34;shortVacancy&#34;:{&#34;vacancyId&#34;:42,&#34;name&#34;:&#34;Dev&#34;,'
    '&#34;company&#34;:{&#34;id&#34;:7,&#34;name&#34;:&#34;Acme&#34;},'
    '&#34;@responseLetterRequired&#34;:true,&#34;userTestPresent&#34;:false,'
    '&#34;closedForApplicants&#34;:false},'
    '&#34;applicantVacancyResponseStatuses&#34;:{&#34;42&#34;:{'
    '&#34;test&#34;:{&#34;hasTests&#34;:true},'
    '&#34;negotiations&#34;:{&#34;topicList&#34;:[{&#34;id&#34;:1}]}}}}</html>'
)


@pytest.mark.asyncio
async def test_get_vacancy_normalises_and_prefers_the_authoritative_test_flag(monkeypatch):
    """shortVacancy.userTestPresent is the search-time flag; the per-applicant
    block is the live one and must win, or a test vacancy gets a blind apply."""
    from app.hh import web

    async def _load_web_session(_user_id):
        return SimpleNamespace()

    monkeypatch.setattr(web, "_get", _fake_get(VACANCY_PAGE))
    monkeypatch.setattr(web, "load_web_session", _load_web_session)
    v = await web.get_vacancy("u1", "42")

    assert v["id"] == "42"
    assert v["name"] == "Dev"
    assert v["employer"] == {"id": "7", "name": "Acme"}
    assert v["response_letter_required"] is True
    assert v["has_test"] is True          # from applicantVacancyResponseStatuses
    assert v["already_responded"] is True  # non-empty topicList
    assert v["archived"] is False


@pytest.mark.asyncio
async def test_get_vacancy_raises_vacancy_gone_on_404(monkeypatch):
    from app.hh import web

    async def _load_web_session(_user_id):
        return SimpleNamespace()

    def _get(session, user_id, url, **kw):
        raise web.VacancyGone(url)

    monkeypatch.setattr(web, "_get", _get)
    monkeypatch.setattr(web, "load_web_session", _load_web_session)
    with pytest.raises(web.VacancyGone):
        await web.get_vacancy("u1", "42")


@pytest.mark.asyncio
async def test_get_vacancy_raises_antibot_block_when_state_absent(monkeypatch):
    """A 200 page without the inline state JSON is an antibot interstitial, not
    a parse error — must surface as a typed error the runner backs off from,
    not a bare ValueError that becomes 'failed'."""
    from app.hh import web
    from app.services.form_filler import AntibotBlock

    async def _load_web_session(_user_id):
        return SimpleNamespace()

    # A 200 interstitial: no shortVacancy, no xsrfToken (so session_looks_dead
    # is bypassed by stubbing _get directly and feeding raw HTML).
    monkeypatch.setattr(web, "_get", _fake_get("<html>please verify you are human</html>"))
    monkeypatch.setattr(web, "load_web_session", _load_web_session)
    monkeypatch.setattr(web, "dump_blocked_page", lambda *a: None)
    with pytest.raises(AntibotBlock):
        await web.get_vacancy("u1", "42")


RESUMES_PAGE = (
    '<html>{&#34;applicantResumes&#34;:[{'
    '&#34;title&#34;:[{&#34;string&#34;:&#34;AI-инженер&#34;}],'
    '&#34;_attributes&#34;:{&#34;hash&#34;:&#34;abc123&#34;,&#34;updated&#34;:1785961567117,'
    '&#34;publishState&#34;:&#34;published&#34;}}]}</html>'
)

NEGOTIATIONS_PAGE = (
    '<html>{&#34;topicList&#34;:['
    '{&#34;vacancyId&#34;:1,&#34;lastState&#34;:&#34;RESPONSE&#34;,&#34;viewedByOpponent&#34;:false},'
    '{&#34;vacancyId&#34;:2,&#34;lastState&#34;:&#34;INTERVIEW&#34;,&#34;viewedByOpponent&#34;:true},'
    '{&#34;vacancyId&#34;:3,&#34;lastState&#34;:&#34;DISCARD&#34;,&#34;viewedByOpponent&#34;:true},'
    '{&#34;lastState&#34;:&#34;RESPONSE&#34;}]}</html>'
)


@pytest.mark.asyncio
async def test_list_resumes_flattens_hhs_title_and_uses_the_hash_as_id(monkeypatch):
    from app.hh import web

    async def _load_web_session(_user_id):
        return SimpleNamespace()

    monkeypatch.setattr(web, "_get", _fake_get(RESUMES_PAGE))
    monkeypatch.setattr(web, "load_web_session", _load_web_session)
    items = await web.list_resumes("u1")

    assert items == [{"id": "abc123", "title": "AI-инженер", "status": "published"}]


@pytest.mark.asyncio
async def test_list_negotiations_maps_hh_states_to_the_analytics_literals(monkeypatch):
    """analytics_summary() keys the funnel off response/invitation/discard —
    the stored values must not drift to hh's web wording."""
    from app.hh import web

    async def _load_web_session(_user_id):
        return SimpleNamespace()

    monkeypatch.setattr(web, "_get", _fake_get(NEGOTIATIONS_PAGE))
    monkeypatch.setattr(web, "load_web_session", _load_web_session)
    rows = await web.list_negotiations("u1")

    # the entry with no vacancyId is dropped
    assert [r["vacancy_id"] for r in rows] == ["1", "2", "3"]
    assert [r["state"] for r in rows] == ["response", "invitation", "discard"]
    assert [r["viewed"] for r in rows] == [False, True, True]


RESUME_DETAIL_PAGE = (
    '<html>{&#34;applicantResume&#34;:{'
    '&#34;title&#34;:[{&#34;string&#34;:&#34;AI-инженер&#34;}],'
    '&#34;firstName&#34;:[{&#34;string&#34;:&#34;Иван&#34;}],'
    '&#34;lastName&#34;:[{&#34;string&#34;:&#34;Петров&#34;}],'
    '&#34;gender&#34;:[{&#34;string&#34;:&#34;male&#34;}],'
    '&#34;totalExperience&#34;:[{&#34;string&#34;:22}],'
    '&#34;area&#34;:[{&#34;string&#34;:160}],'
    '&#34;salary&#34;:[],'
    '&#34;keySkills&#34;:[{&#34;string&#34;:&#34;Python&#34;},{&#34;string&#34;:&#34;SQL&#34;}],'
    '&#34;skills&#34;:[{&#34;string&#34;:&#34;Про себя&#34;}],'
    '&#34;experience&#34;:[{&#34;position&#34;:&#34;Dev&#34;,&#34;companyName&#34;:&#34;Acme&#34;,'
    '&#34;startDate&#34;:&#34;2026-06-01&#34;,&#34;endDate&#34;:null,'
    '&#34;description&#34;:&#34;Делал штуки&#34;}],'
    '&#34;primaryEducation&#34;:[{&#34;name&#34;:&#34;КБТУ&#34;,&#34;organization&#34;:&#34;ШИТиИ&#34;,'
    '&#34;result&#34;:&#34;ИС&#34;,&#34;year&#34;:2025}],'
    '&#34;language&#34;:[{&#34;degree&#34;:&#34;c1&#34;,&#34;id&#34;:57}]}}</html>'
)


@pytest.mark.asyncio
async def test_get_resume_maps_the_web_shape_onto_what_the_summary_expects(monkeypatch):
    from app.hh import web

    async def _load_web_session(_user_id):
        return SimpleNamespace()

    monkeypatch.setattr(web, "_get", _fake_get(RESUME_DETAIL_PAGE))
    monkeypatch.setattr(web, "load_web_session", _load_web_session)
    r = await web.get_resume("u1", "abc123")

    assert r["title"] == "AI-инженер"
    assert r["first_name"] == "Иван" and r["last_name"] == "Петров"
    assert r["skill_set"] == ["Python", "SQL"]
    assert r["gender"] == "мужской"  # not the raw "male" enum
    assert r["skills"] == "Про себя"
    assert r["experience"] == [{
        "position": "Dev", "company": "Acme",
        "start": "2026-06-01", "end": None, "description": "Делал штуки",
    }]
    assert r["education"]["primary"] == [{
        "name": "КБТУ", "organization": "ШИТиИ", "result": "ИС", "year": 2025,
    }]

    # Ids we cannot resolve to names must be ABSENT, not printed raw: the
    # summary feeds an LLM, and "Город: 160" is worse than no city at all.
    assert "area" not in r
    assert "language" not in r
    assert "salary" not in r


@pytest.mark.asyncio
async def test_get_resume_renders_total_experience_readably(monkeypatch):
    from app.hh import web

    async def _load_web_session(_user_id):
        return SimpleNamespace()

    monkeypatch.setattr(web, "_get", _fake_get(RESUME_DETAIL_PAGE))
    monkeypatch.setattr(web, "load_web_session", _load_web_session)
    r = await web.get_resume("u1", "abc123")
    assert r["total_experience"] == "1 г. 10 мес."
