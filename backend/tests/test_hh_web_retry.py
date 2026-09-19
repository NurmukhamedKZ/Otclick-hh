from unittest.mock import MagicMock

import pytest
import requests


def _response(status: int, *, retry_after: str | None = None) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.url = "https://hh.ru/vacancy/1"
    if retry_after is not None:
        resp.headers["Retry-After"] = retry_after
    return resp


def test_get_retries_connect_timeout_then_succeeds(monkeypatch):
    from app.hh import web

    session = MagicMock()
    session.get.side_effect = [
        requests.exceptions.ConnectTimeout("connect timeout"),
        requests.exceptions.ConnectTimeout("connect timeout"),
        _response(200),
    ]
    sleeps: list[float] = []
    monkeypatch.setattr(web.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(web.random, "uniform", lambda *_: 0.0)
    monkeypatch.setattr(web, "session_looks_dead", lambda _resp: False)
    web._last_request_at.clear()

    result = web._get(session, "u1", "https://hh.ru/vacancy/1")

    assert result.status_code == 200
    assert session.get.call_count == 3
    # Backoff is 1s then 2s; per-user throttle may add tiny extra sleeps.
    assert 1.0 in sleeps
    assert 2.0 in sleeps
    assert session.get.call_args.kwargs["timeout"] == (7, 25)


def test_get_honours_retry_after_for_429(monkeypatch):
    from app.hh import web

    session = MagicMock()
    session.get.side_effect = [_response(429, retry_after="3"), _response(200)]
    sleeps: list[float] = []
    monkeypatch.setattr(web.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(web, "session_looks_dead", lambda _resp: False)
    web._last_request_at.clear()

    result = web._get(session, "u1", "https://hh.ru/vacancy/1")

    assert result.status_code == 200
    assert session.get.call_count == 2
    assert 3.0 in sleeps


def test_get_raises_typed_transient_error_after_bounded_retries(monkeypatch):
    from app.hh import web

    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectTimeout("connect timeout")
    monkeypatch.setattr(web.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(web.random, "uniform", lambda *_: 0.0)
    web._last_request_at.clear()

    with pytest.raises(web.HHTransientError) as ex:
        web._get(session, "u1", "https://hh.ru/vacancy/1")

    assert session.get.call_count == 3
    assert "3 attempts" in str(ex.value)


def test_get_does_not_retry_vacancy_gone(monkeypatch):
    from app.hh import web

    session = MagicMock()
    session.get.return_value = _response(404)
    monkeypatch.setattr(web.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(web, "session_looks_dead", lambda _resp: False)
    web._last_request_at.clear()

    with pytest.raises(web.VacancyGone):
        web._get(session, "u1", "https://hh.ru/vacancy/1")

    assert session.get.call_count == 1
