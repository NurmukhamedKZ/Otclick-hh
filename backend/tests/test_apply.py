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



def _vacancy_from(client):
    """apply_one used to fetch the vacancy through ApiClient.get; it now goes
    through web.get_vacancy. Replay whatever the test staged on client.get."""

    async def _get_vacancy(user_id, vacancy_id):
        if client.get.side_effect is not None:
            raise client.get.side_effect
        return client.get.return_value

    return _get_vacancy



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
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    async def _submitted(user_id, resume_id, vacancy_id, letter="", answers=None):
        assert answers is None  # no-test plain response
        return "sent", None

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_submitted),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())

    assert result == "sent"
    client.post.assert_not_called()


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


async def test_apply_one_web_session_dead_maps_to_token_dead():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    async def _dead(user_id, resume_id, vacancy_id, letter="", answers=None):
        return "failed", "web_session_expired: hh rejected the web session (403)"

    mark_calls = []

    async def fake_mark(user_id, reason):
        mark_calls.append((user_id, reason))

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_dead),
        patch.object(apply_mod, "mark_invalid", side_effect=fake_mark),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())

    # Dead web session must hit the terminal path so the runner stops the loop.
    assert result == "token_dead"
    assert mark_calls and mark_calls[0][0] == "u1"


async def test_apply_one_rejection_maps_form_required():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    async def _rej(**kwargs):
        return "failed", "hh_rejected: 403 must process test first"

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_rej),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "form_required"


async def test_apply_one_rejection_maps_already_applied():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    async def _rej(**kwargs):
        return "failed", "hh_rejected: 400 already applied"

    blacklist_upserts = []

    def fake_blacklist(user_id, employer_id):
        blacklist_upserts.append((user_id, employer_id))

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_rej),
        patch.object(apply_mod, "_auto_blacklist", side_effect=fake_blacklist),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "skipped"
    assert ("u1", "42") in blacklist_upserts


async def test_apply_one_failed_on_unknown_rejection():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    async def _rej(**kwargs):
        return "failed", "hh_rejected: 502 upstream down"

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_rej),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "failed"


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
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
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
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
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

    captured = {}

    async def _submitted(user_id, resume_id, vacancy_id, letter="", answers=None):
        captured["letter"] = letter
        return "sent", None

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_submitted),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", agent)
    assert result == "sent"
    agent.write_cover_letter.assert_not_awaited()
    assert captured["letter"] == ""


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

    captured = {}

    async def _submitted(user_id, resume_id, vacancy_id, letter="", answers=None):
        captured["letter"] = letter
        return "sent", None

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_submitted),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", agent)
    assert result == "sent"
    assert captured["letter"] == "GENERATED"


async def test_apply_one_form_required_on_rejection_marker():
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

    async def _rej(**kwargs):
        return "failed", "hh_rejected: 403 must process test first"

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_rej),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "form_required"


async def test_apply_one_account_banned_on_rejection():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    async def _rej(**kwargs):
        return "failed", "hh_rejected: 403 user_blocked"

    mark_calls = []

    async def fake_mark(user_id, reason):
        mark_calls.append((user_id, reason))

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_rej),
        patch.object(apply_mod, "mark_invalid", side_effect=fake_mark),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "account_banned"
    assert mark_calls and "banned" in mark_calls[0][1].lower()


async def test_apply_one_resume_gone_disables_filters():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    async def _rej(**kwargs):
        return "failed", "hh_rejected: 400 resume_not_found"

    disable_calls = []

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_rej),
        patch.object(
            apply_mod,
            "_disable_filters_for_resume",
            side_effect=lambda uid, ruid: disable_calls.append((uid, ruid)),
        ),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "resume_missing"
    assert disable_calls == [("u1", "r-uuid")]


async def test_apply_one_failed_on_generic_rejection():
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "v1", "employer": {"id": "42"}, "has_test": False, "response_letter_required": False}

    async def _rej(**kwargs):
        return "failed", "hh_rejected: 400 nope"

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy_from(client)),
        patch.object(apply_mod.form_filler, "submit_response", new=_rej),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "failed"


async def test_apply_one_vacancy_gone_when_hh_drops_the_page():
    from app.hh import web as web_mod
    from app.services import apply as apply_mod

    sb, _, upsert = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})

    async def _gone(user_id, vacancy_id):
        raise web_mod.VacancyGone("404 for /vacancy/v1")

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_gone),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "vacancy_gone"


async def test_apply_one_token_dead_when_the_web_session_died_mid_fetch():
    """A login wall on the vacancy page must hit the terminal path, not "failed":
    worker_main respawns the runner every 15 s otherwise."""
    from app.services import apply as apply_mod
    from app.services.form_filler import WebSessionExpired

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    mark_calls = []

    async def fake_mark(user_id, reason):
        mark_calls.append((user_id, reason))

    async def _dead(user_id, vacancy_id):
        raise WebSessionExpired("hh rejected the web session (403)")

    async def _noop_report(user_id, ex):
        pass

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_dead),
        patch.object(apply_mod.form_filler, "report_dead_session", new=_noop_report),
        patch.object(apply_mod, "mark_invalid", side_effect=fake_mark),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "token_dead"
    assert mark_calls and mark_calls[0][0] == "u1"


async def test_apply_one_skips_when_hh_says_a_negotiation_already_exists():
    """hh's own per-applicant block is authoritative — no guessing from the
    rejection wording after we already posted."""
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})

    async def _already(user_id, vacancy_id):
        return {
            "id": "v1",
            "employer": {"id": "42", "name": "Acme"},
            "has_test": False,
            "response_letter_required": False,
            "already_responded": True,
        }

    posted = []

    async def _submitted(user_id, resume_id, vacancy_id, letter="", answers=None):
        posted.append(vacancy_id)
        return "sent", None

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_already),
        patch.object(apply_mod.form_filler, "submit_response", new=_submitted),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "skipped"
    assert posted == []  # must not reach hh at all


async def test_apply_one_captcha_does_not_fall_through_to_failed():
    """A captcha wall classified as "failed" leaves the runner hammering hh
    while the UI reports healthy — the fastest route to a flagged account."""
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})

    async def _vacancy(user_id, vacancy_id):
        return {
            "id": "v1",
            "employer": {"id": "42", "name": "Acme"},
            "has_test": False,
            "response_letter_required": False,
        }

    async def _submitted(user_id, resume_id, vacancy_id, letter="", answers=None):
        return "failed", "hh_rejected: 200 {\"error\":\"captcha required\"}"

    created = []

    async def _create(user_id, captcha_url):
        created.append(user_id)
        return {}

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy),
        patch.object(apply_mod.form_filler, "submit_response", new=_submitted),
        patch.object(apply_mod.captcha_service, "create_request", new=_create),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "captcha"
    assert created == ["u1"]


async def test_apply_one_writes_a_letter_when_hh_demands_one_despite_the_page_flag():
    """@responseLetterRequired is what the vacancy page advertises;
    "letter-required" is hh refusing for real. Believing the flag burned the
    vacancy as "failed" over a missing field."""
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})

    async def _vacancy(user_id, vacancy_id):
        return {
            "id": "v1",
            "employer": {"id": "42", "name": "Acme"},
            "has_test": False,
            "response_letter_required": False,   # page says no letter needed
        }

    calls = []

    async def _submitted(user_id, resume_id, vacancy_id, letter="", answers=None):
        calls.append(letter)
        if not letter:
            return "failed", 'hh_rejected: 400 {"error": "letter-required"}'
        return "sent", None

    agent = _fake_agent(letter="ПИСЬМО")

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy),
        patch.object(apply_mod.form_filler, "submit_response", new=_submitted),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", agent)

    assert result == "sent"
    assert calls == ["", "ПИСЬМО"]  # retried once, with a letter
