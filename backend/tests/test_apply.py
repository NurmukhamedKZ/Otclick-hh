import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


def _fake_agent(form=("form_sent", []), letter="GENERATED"):
    """Stand-in HHAgent: form/cover-letter methods return canned values."""
    agent = MagicMock()
    agent.write_form_answers = AsyncMock(return_value=form)
    agent.write_cover_letter = AsyncMock(return_value=letter)
    return agent


def _supabase_mock(resume_row, already_applied=False):
    """Return a fluent supabase mock that drives apply.py's three queries."""

    # resolve_hh_resume_id (.select.eq.eq.maybe_single.execute)
    resume_chain = MagicMock()
    resume_chain.select.return_value = resume_chain
    resume_chain.eq.return_value = resume_chain
    resume_chain.maybe_single.return_value = resume_chain
    resume_chain.execute.return_value = SimpleNamespace(data=resume_row)

    # already_applied (.select.eq.eq.limit.execute)
    applied_chain = MagicMock()
    applied_chain.select.return_value = applied_chain
    applied_chain.eq.return_value = applied_chain
    applied_chain.limit.return_value = applied_chain
    applied_chain.execute.return_value = SimpleNamespace(
        data=[{"id": "x"}] if already_applied else []
    )

    # applications.upsert / blacklist.upsert
    upsert_chain = MagicMock()
    upsert_chain.upsert.return_value = upsert_chain
    upsert_chain.execute.return_value = SimpleNamespace(data=None)

    sb = MagicMock()

    def _route(name):
        if name == "resumes":
            return resume_chain
        if name == "applications":
            # First read (already_applied) then upsert calls.
            return applied_chain if applied_chain.execute.call_count == 0 else upsert_chain
        return upsert_chain

    sb.table.side_effect = lambda name: _route(name)
    return sb, applied_chain, upsert_chain


async def test_apply_one_sent_success():
    from app.services import apply as apply_mod

    sb, _, upsert = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.post.return_value = {}
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())

    assert result == "sent"
    client.post.assert_called_once()


async def test_apply_one_resume_missing():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock(None)
    with patch.object(apply_mod, "service_client", sb):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "resume_missing"


async def test_apply_one_skipped_already_applied_locally():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock(
        {"id": "r-uuid", "hh_resume_id": "hh-r1"}, already_applied=True
    )
    with patch.object(apply_mod, "service_client", sb):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "skipped"


async def test_apply_one_captcha():
    from unittest.mock import AsyncMock

    from app.hh import errors as hh_errors
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    resp = MagicMock(status_code=403)
    data = {"errors": [{"value": "captcha_required", "captcha_url": "https://hh.ru/cap.png"}]}
    client.post.side_effect = hh_errors.CaptchaRequired(resp, data)

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
        patch.object(apply_mod.captcha_service, "create_request", new=AsyncMock()) as create_req,
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "captcha"
    create_req.assert_awaited_once_with("u1", "https://hh.ru/cap.png")


async def test_apply_one_limit_exceeded():
    from app.hh import errors as hh_errors
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    resp = MagicMock(status_code=400)
    data = {"errors": [{"value": "limit_exceeded", "type": "bad"}]}
    client.post.side_effect = hh_errors.LimitExceeded(resp, data)

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "limit_day"


async def test_apply_one_token_dead_on_forbidden():
    from app.hh import errors as hh_errors
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    resp = MagicMock(status_code=403)
    data = {"errors": [{"value": "token_dead", "type": "auth"}]}
    client.post.side_effect = hh_errors.Forbidden(resp, data)

    mark_calls = []

    async def fake_mark(user_id, reason):
        mark_calls.append((user_id, reason))

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
        patch.object(apply_mod, "mark_invalid", side_effect=fake_mark),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "token_dead"
    assert mark_calls and mark_calls[0][0] == "u1"


async def test_apply_one_token_dead_when_creds_invalid():
    from app.services import apply as apply_mod
    from app.services.hh_credentials import HHCredentialsInvalid

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})

    async def raise_invalid(user_id):
        raise HHCredentialsInvalid(user_id, "Forbidden: x")

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", side_effect=raise_invalid),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "token_dead"


async def test_apply_one_form_required_on_has_test():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "id": "v1",
        "has_test": True,
        "response_letter_required": False,
        "employer": {"id": "42"},
    }

    agent = _fake_agent(form=("form_required", []))

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", agent)
    assert result == "form_required"
    client.post.assert_not_called()


async def test_apply_one_form_pending_when_filler_drafts_answers():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "id": "v1",
        "has_test": True,
        "response_letter_required": False,
        "employer": {"id": "42"},
    }

    agent = _fake_agent(form=("form_pending", [{"task_id": 1, "answer": "Да"}]))

    async def _ok(*a, **kw):
        return None

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
        patch.object(apply_mod.form_drafts, "insert_draft", side_effect=_ok),
        patch.object(apply_mod.notifications, "notify", side_effect=_ok),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", agent)
    assert result == "form_pending"
    # answers go to drafts table — apply must NOT submit to hh
    client.post.assert_not_called()


async def test_apply_one_skips_letter_when_not_required():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "id": "v1",
        "has_test": False,
        "response_letter_required": False,
        "employer": {"id": "42"},
    }
    client.post.return_value = {}

    agent = _fake_agent()

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", agent)
    assert result == "sent"
    agent.write_cover_letter.assert_not_awaited()
    posted_params = client.post.call_args[0][1]
    assert "message" not in posted_params


async def test_apply_one_generates_letter_when_required():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "id": "v1",
        "has_test": False,
        "response_letter_required": True,
        "employer": {"id": "42"},
        "name": "Go Dev",
    }
    client.post.return_value = {}

    agent = _fake_agent(letter="GENERATED")

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", agent)
    assert result == "sent"
    posted_params = client.post.call_args[0][1]
    assert posted_params["message"] == "GENERATED"


async def test_apply_one_vacancy_gone():
    from app.hh import errors as hh_errors
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})
    client = MagicMock()
    client.access_token = "tok"
    resp = MagicMock(status_code=404)
    client.get.side_effect = hh_errors.ResourceNotFound(resp, {"description": "gone"})

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "vacancy_gone"
    client.post.assert_not_called()


async def test_apply_one_form_required_on_hh_forbidden_marker():
    from app.hh import errors as hh_errors
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {
        "id": "v1",
        "has_test": False,
        "response_letter_required": False,
        "employer": {"id": "42"},
    }
    resp = MagicMock(status_code=403)
    client.post.side_effect = hh_errors.Forbidden(
        resp, {"errors": [{"type": "test_required", "value": "must process test first"}]}
    )

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "form_required"


async def test_apply_one_account_banned_on_negotiations_forbidden():
    from app.hh import errors as hh_errors
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    resp = MagicMock(status_code=403)
    data = {"errors": [{"type": "account", "value": "user_blocked"}]}
    client.post.side_effect = hh_errors.Forbidden(resp, data)

    mark_calls = []

    async def fake_mark(user_id, reason):
        mark_calls.append((user_id, reason))

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
        patch.object(apply_mod, "mark_invalid", side_effect=fake_mark),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "account_banned"
    assert mark_calls and "banned" in mark_calls[0][1].lower()


async def test_apply_one_account_banned_on_vacancy_fetch():
    from app.hh import errors as hh_errors
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    resp = MagicMock(status_code=403)
    client.get.side_effect = hh_errors.Forbidden(
        resp, {"errors": [{"type": "auth", "value": "account_blocked"}]}
    )

    async def fake_mark(user_id, reason):
        pass

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
        patch.object(apply_mod, "mark_invalid", side_effect=fake_mark),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "account_banned"
    client.post.assert_not_called()


async def test_apply_one_resume_gone_on_hh_disables_filters():
    from app.hh import errors as hh_errors
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    resp = MagicMock(status_code=400)
    client.post.side_effect = hh_errors.BadRequest(
        resp, {"errors": [{"type": "bad_argument", "value": "resume_not_found"}]}
    )

    disable_calls = []

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
        patch.object(
            apply_mod,
            "_disable_filters_for_resume",
            side_effect=lambda uid, ruid: disable_calls.append((uid, ruid)),
        ),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "resume_missing"
    assert disable_calls == [("u1", "r-uuid")]


async def test_apply_one_failed_on_generic_client_error():
    from app.hh import errors as hh_errors
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}
    resp = MagicMock(status_code=400)
    client.post.side_effect = hh_errors.BadRequest(resp, {"description": "nope"})

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod, "load_api_client", return_value=client),
        patch.object(apply_mod, "persist_if_refreshed"),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "failed"
