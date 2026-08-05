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
    assert vacancies[0] == {
        "id": "1",
        "name": "Python dev",
        "employer": {"id": "9", "name": "Acme"},
        "has_test": True,
        "response_letter_required": False,
        "archived": False,
    }


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
