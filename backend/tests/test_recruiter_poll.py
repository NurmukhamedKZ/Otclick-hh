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
        patch.object(rp.asyncio, "sleep", new=AsyncMock()),
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
