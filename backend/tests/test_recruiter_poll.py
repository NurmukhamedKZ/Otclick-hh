import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _ref(**kw):
    base = {
        "nid": "n9", "chat_id": "c1", "applicant_id": "me", "vacancy_id": "v1",
        "last_id": "m5", "last_participant_id": "emp", "last_is_bot": False,
    }
    base.update(kw)
    return base


def _msg(mid, text, from_employer=True, is_bot=False, buttons=None):
    return {
        "id": mid, "text": text, "created_at": "2026-05-30T00:00:00+03:00",
        "from_employer": from_employer, "is_bot": is_bot, "name": "X",
        "type": "SIMPLE", "buttons": buttons or [],
    }


def _patches(rp, *, recent, messages, cursor=None):
    """Common patch set; returns the contextmanagers list for `with`."""
    return [
        patch.object(rp, "load_api_client", new=AsyncMock(return_value=MagicMock(access_token="t"))),
        patch.object(rp, "persist_if_refreshed", new=AsyncMock()),
        patch.object(rp.chatik, "recent_chats", new=AsyncMock(return_value=recent)),
        patch.object(rp.chatik, "chat_messages", new=AsyncMock(return_value=messages)),
        patch.object(rp.recruiter, "get_cursor", new=AsyncMock(return_value=cursor)),
        patch.object(rp.recruiter, "upsert_cursor", new=AsyncMock()),
        patch.object(rp.recruiter, "list_answered_questions", new=AsyncMock(return_value=[])),
        patch.object(rp.recruiter, "mark_question_completed", new=AsyncMock()),
        patch.object(rp.asyncio, "sleep", new=AsyncMock()),
        patch.object(rp, "_vacancy_meta", new=AsyncMock(return_value=("Python Dev", "Acme"))),
    ]


async def _run(rp, agent, patches):
    import contextlib
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        await rp.poll_recruiter_chats("u1", agent)


@pytest.mark.asyncio
async def test_poll_routes_real_recruiter_to_free_text():
    from app.worker import recruiter_poll as rp
    recent = [_ref(last_id="m5", last_participant_id="emp")]
    messages = [_msg("m5", "Здравствуйте, меня зовут Елена", is_bot=False)]
    agent = MagicMock()
    agent.answer_recruiter = AsyncMock()
    agent.answer_recruiter_choice = AsyncMock()
    p = _patches(rp, recent=recent, messages=messages, cursor="old")
    upsert = p[5]
    await _run(rp, agent, p)
    agent.answer_recruiter.assert_awaited_once()
    args = agent.answer_recruiter.await_args.args
    assert args[0] == "n9" and args[1] == "m5"  # nid, message_id
    kwargs = agent.answer_recruiter.await_args.kwargs
    assert kwargs["vacancy_id"] == "v1"
    assert kwargs["vacancy_title"] == "Python Dev"
    assert kwargs["employer_name"] == "Acme"
    agent.answer_recruiter_choice.assert_not_awaited()
    upsert.new.assert_awaited_once()
    assert upsert.new.await_args.args[2] == "m5"


@pytest.mark.asyncio
async def test_poll_routes_bot_buttons_to_choice():
    from app.worker import recruiter_poll as rp
    recent = [_ref(last_id="m5", last_is_bot=True)]
    messages = [_msg("m5", "Подходит 100 тыс?", is_bot=True, buttons=["Да", "Нет"])]
    agent = MagicMock()
    agent.answer_recruiter = AsyncMock()
    agent.answer_recruiter_choice = AsyncMock()
    p = _patches(rp, recent=recent, messages=messages, cursor="old")
    await _run(rp, agent, p)
    agent.answer_recruiter_choice.assert_awaited_once()
    ca = agent.answer_recruiter_choice.await_args.args
    assert ca[0] == "n9" and ca[1] == "m5" and ca[4] == "Подходит 100 тыс?" and ca[5] == ["Да", "Нет"]
    ckw = agent.answer_recruiter_choice.await_args.kwargs
    assert ckw["vacancy_id"] == "v1" and ckw["vacancy_title"] == "Python Dev"
    agent.answer_recruiter.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_handles_bot_message_without_buttons():
    """The hh bot also asks open questions without buttons — those must reach the
    agent (it decides reply/escalate/SKIP), not be dropped as a bot notice."""
    from app.worker import recruiter_poll as rp
    recent = [_ref(last_id="m5", last_is_bot=True)]
    messages = [_msg("m5", "Есть ли у вас опыт интеграции Claude API?", is_bot=True)]
    agent = MagicMock()
    agent.answer_recruiter = AsyncMock()
    agent.answer_recruiter_choice = AsyncMock()
    p = _patches(rp, recent=recent, messages=messages, cursor="old")
    upsert = p[5]
    await _run(rp, agent, p)
    agent.answer_recruiter.assert_awaited_once()
    agent.answer_recruiter_choice.assert_not_awaited()
    upsert.new.assert_awaited_once()
    assert upsert.new.await_args.args[2] == "m5"


@pytest.mark.asyncio
async def test_poll_skips_rejected_negotiation_state():
    # Negotiation in a discard ("отказ") state → agent never runs (no tokens),
    # no chatik message fetch, cursor untouched.
    from app.worker import recruiter_poll as rp
    recent = [_ref(last_id="m5", last_participant_id="emp")]
    fetch = AsyncMock()
    agent = MagicMock()
    agent.answer_recruiter = AsyncMock()
    agent.answer_recruiter_choice = AsyncMock()
    p = _patches(rp, recent=recent, messages=[], cursor="old")
    p[3] = patch.object(rp.chatik, "chat_messages", new=fetch)  # spy
    upsert = p[5]
    with patch.object(rp, "_negotiation_states",
                      new=AsyncMock(return_value={"n9": "discard_after_interview"})):
        await _run(rp, agent, p)
    fetch.assert_not_awaited()
    agent.answer_recruiter.assert_not_awaited()
    agent.answer_recruiter_choice.assert_not_awaited()
    upsert.new.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_skips_when_last_message_is_mine():
    from app.worker import recruiter_poll as rp
    recent = [_ref(last_participant_id="me")]  # == applicant_id
    fetch = AsyncMock()
    agent = MagicMock()
    agent.answer_recruiter = AsyncMock()
    p = _patches(rp, recent=recent, messages=[])
    p[3] = patch.object(rp.chatik, "chat_messages", new=fetch)  # spy
    await _run(rp, agent, p)
    fetch.assert_not_awaited()  # no message fetch when we sent the last message
    agent.answer_recruiter.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_skips_already_handled():
    from app.worker import recruiter_poll as rp
    recent = [_ref(last_id="m5")]
    fetch = AsyncMock()
    agent = MagicMock()
    agent.answer_recruiter = AsyncMock()
    p = _patches(rp, recent=recent, messages=[], cursor="m5")  # cursor == last
    p[3] = patch.object(rp.chatik, "chat_messages", new=fetch)
    await _run(rp, agent, p)
    fetch.assert_not_awaited()
    agent.answer_recruiter.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_no_web_session_returns_early():
    from app.worker import recruiter_poll as rp
    load = AsyncMock()
    agent = MagicMock()
    with patch.object(rp.chatik, "recent_chats", new=AsyncMock(return_value=None)), \
         patch.object(rp, "load_api_client", new=load):
        await rp.poll_recruiter_chats("u1", agent)
    load.assert_not_awaited()  # no creds load when there is no web session


@pytest.mark.asyncio
async def test_poll_swallows_error_keeps_cursor():
    from app.worker import recruiter_poll as rp
    recent = [_ref(last_id="m5")]
    agent = MagicMock()
    agent.answer_recruiter = AsyncMock(side_effect=RuntimeError("boom"))
    messages = [_msg("m5", "Здравствуйте", is_bot=False)]
    p = _patches(rp, recent=recent, messages=messages, cursor="old")
    upsert = p[5]
    await _run(rp, agent, p)  # must not raise
    upsert.new.assert_not_awaited()  # error → cursor NOT advanced


@pytest.mark.asyncio
async def test_poll_runs_agent_without_api_client():
    """Cookies-only connection (no OAuth token): the poll must still answer
    chats — the client is only the negotiation-state skip list. Regression for
    the agent going silent with AttributeError every 2 minutes."""
    from app.worker import recruiter_poll as rp
    recent = [_ref(last_id="m5", last_participant_id="emp")]
    messages = [_msg("m5", "Здравствуйте", is_bot=False)]
    agent = MagicMock()
    agent.answer_recruiter = AsyncMock()
    agent.answer_recruiter_choice = AsyncMock()
    p = _patches(rp, recent=recent, messages=messages, cursor="old")
    load, persist = p[0], p[1]
    load.new.side_effect = RuntimeError("cookies-only connection")
    upsert = p[5]
    await _run(rp, agent, p)
    agent.answer_recruiter.assert_awaited_once()
    upsert.new.assert_awaited_once()
    persist.new.assert_not_awaited()  # nothing to persist without a client


def _qrow(**kw):
    base = {
        "id": "q1", "negotiation_id": "n9", "message_id": "m5",
        "chat_id": "c1", "applicant_id": "me",
        "questions": ["Когда вам удобно?"], "answers": ["В среду в 15:00"],
        "reason": "scheduling", "question_text": "Когда?",
        "vacancy_id": "v1", "vacancy_title": "Python Dev", "employer_name": "Acme",
    }
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_poll_resumes_answered_question():
    from app.worker import recruiter_poll as rp
    agent = MagicMock()
    agent.resume_recruiter_with_answers = AsyncMock()
    msgs = [_msg("m5", "Когда удобно?", is_bot=False)]
    with patch.object(rp.recruiter, "list_answered_questions",
                      new=AsyncMock(return_value=[_qrow()])), \
         patch.object(rp.chatik, "chat_messages", new=AsyncMock(return_value=msgs)), \
         patch.object(rp.recruiter, "mark_question_completed", new=AsyncMock()) as done:
        await rp.poll_answered_questions("u1", agent, MagicMock(access_token="t"), {})
    agent.resume_recruiter_with_answers.assert_awaited_once()
    kw = agent.resume_recruiter_with_answers.await_args.kwargs
    assert kw["questions"] == ["Когда вам удобно?"] and kw["answers"] == ["В среду в 15:00"]
    assert kw["chat_id"] == "c1" and kw["applicant_id"] == "me"
    assert kw["vacancy_id"] == "v1"
    done.assert_awaited_once_with("u1", "q1")


@pytest.mark.asyncio
async def test_poll_marks_completed_without_resume_when_rejected():
    """Answer to a question from a chat that got rejected meanwhile -> marked
    completed without invoking the agent (no pointless draft)."""
    from app.worker import recruiter_poll as rp
    agent = MagicMock()
    agent.resume_recruiter_with_answers = AsyncMock()
    with patch.object(rp.recruiter, "list_answered_questions",
                      new=AsyncMock(return_value=[_qrow()])), \
         patch.object(rp.recruiter, "mark_question_completed", new=AsyncMock()) as done:
        await rp.poll_answered_questions(
            "u1", agent, MagicMock(access_token="t"),
            {"n9": "discard_after_interview"},
        )
    agent.resume_recruiter_with_answers.assert_not_awaited()
    done.assert_awaited_once_with("u1", "q1")


@pytest.mark.asyncio
async def test_poll_keeps_row_answered_on_resume_error():
    """Agent crash on resume -> status stays 'answered' (not advanced/completed)
    so the next poll retries it."""
    from app.worker import recruiter_poll as rp
    agent = MagicMock()
    agent.resume_recruiter_with_answers = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(rp.recruiter, "list_answered_questions",
                      new=AsyncMock(return_value=[_qrow()])), \
         patch.object(rp.chatik, "chat_messages", new=AsyncMock(return_value=[_msg("m5", "hi")])), \
         patch.object(rp.recruiter, "mark_question_completed", new=AsyncMock()) as done:
        await rp.poll_answered_questions("u1", agent, MagicMock(access_token="t"), {})  # must not raise
    assert agent.resume_recruiter_with_answers.await_count == 1
    done.assert_not_awaited()
