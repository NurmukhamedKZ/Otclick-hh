import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.recruiter import new_employer_message, to_lc_messages


def _msgs():
    return [
        {"id": "1", "author": {"participant_type": "applicant"}, "text": "cover letter"},
        {"id": "2", "author": {"participant_type": "employer"}, "text": "Какая зарплата?"},
        {"id": "3", "author": {"participant_type": "applicant"}, "text": "300к"},
        {"id": "4", "author": {"participant_type": "employer"}, "text": "Готовы к офферу?"},
    ]


def _fluent(final_data=None):
    chain = MagicMock()
    for m in ("select", "insert", "update", "delete", "eq", "order", "maybe_single", "limit", "upsert"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = SimpleNamespace(data=final_data)
    return chain


def _async_return(value):
    async def _f(*a, **k):
        return value
    return _f


def _async_noop():
    async def _f(*a, **k):
        return None
    return _f


# --- message selection -------------------------------------------------------

def test_new_employer_message_after_cursor():
    msg = new_employer_message(_msgs(), last_handled_id="2")
    assert msg["id"] == "4"


def test_new_employer_message_none_when_last_is_applicant():
    msgs = _msgs()[:3]  # last is applicant
    assert new_employer_message(msgs, last_handled_id="2") is None


def test_new_employer_message_no_cursor_takes_latest_employer():
    assert new_employer_message(_msgs(), last_handled_id=None)["id"] == "4"


def test_new_employer_message_skips_empty_text():
    msgs = [{"id": "5", "author": {"participant_type": "employer"}, "text": ""}]
    assert new_employer_message(msgs, last_handled_id=None) is None


def test_to_lc_messages_maps_roles():
    out = to_lc_messages(_msgs())
    assert out == [
        ("assistant", "cover letter"),
        ("user", "Какая зарплата?"),
        ("assistant", "300к"),
        ("user", "Готовы к офферу?"),
    ]


# --- persistence -------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cursor_returns_last_handled():
    from app.services import recruiter
    chain = _fluent({"last_handled_message_id": "42"})
    with patch.object(recruiter.service_client, "table", return_value=chain):
        assert await recruiter.get_cursor("u1", "n1") == "42"


@pytest.mark.asyncio
async def test_get_cursor_none_when_no_row():
    from app.services import recruiter
    chain = _fluent(None)
    with patch.object(recruiter.service_client, "table", return_value=chain):
        assert await recruiter.get_cursor("u1", "n1") is None


@pytest.mark.asyncio
async def test_insert_draft_writes_row():
    from app.services import recruiter
    chain = _fluent([{"id": "d1"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        await recruiter.insert_draft("u1", "n1", "m1", "draft text", "ambiguous")
    args = chain.insert.call_args[0][0]
    assert args["user_id"] == "u1"
    assert args["negotiation_id"] == "n1"
    assert args["message_id"] == "m1"
    assert args["draft_text"] == "draft text"
    assert args["reason"] == "ambiguous"
    assert args["status"] == "pending"


@pytest.mark.asyncio
async def test_insert_todo_writes_row():
    from app.services import recruiter
    chain = _fluent([{"id": "t1"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        await recruiter.insert_todo("u1", "n1", "m1", "Заполнить форму", "ссылка ниже", "https://forms.gle/x")
    args = chain.insert.call_args[0][0]
    assert args["title"] == "Заполнить форму"
    assert args["link"] == "https://forms.gle/x"
    assert args["status"] == "open"


@pytest.mark.asyncio
async def test_upsert_cursor_upserts():
    from app.services import recruiter
    chain = _fluent([{"id": "c1"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        await recruiter.upsert_cursor("u1", "n1", "m9", vacancy_id="v1", employer_name="Acme")
    assert chain.upsert.called
    row = chain.upsert.call_args[0][0]
    assert row["last_handled_message_id"] == "m9"
    assert row["negotiation_id"] == "n1"


# --- query + send ------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pending_drafts():
    from app.services import recruiter
    chain = _fluent([{"id": "d1", "draft_text": "hi", "status": "pending"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        rows = await recruiter.list_drafts("u1")
    assert rows[0]["id"] == "d1"
    chain.eq.assert_any_call("status", "pending")


@pytest.mark.asyncio
async def test_discard_draft_sets_status():
    from app.services import recruiter
    chain = _fluent([{"id": "d1"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        await recruiter.discard_draft("u1", "d1")
    update = chain.update.call_args[0][0]
    assert update["status"] == "discarded"
    assert "resolved_at" in update


@pytest.mark.asyncio
async def test_mark_todo_done():
    from app.services import recruiter
    chain = _fluent([{"id": "t1"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        await recruiter.mark_todo("u1", "t1", "done")
    update = chain.update.call_args[0][0]
    assert update["status"] == "done"
    assert "done_at" in update


@pytest.mark.asyncio
async def test_send_draft_posts_to_hh_and_marks_sent():
    from app.services import recruiter
    draft_chain = _fluent([{"id": "d1", "negotiation_id": "n9", "draft_text": "orig", "status": "pending"}])
    draft_chain.maybe_single.return_value = draft_chain
    draft_chain.execute.return_value = SimpleNamespace(
        data={"id": "d1", "negotiation_id": "n9", "draft_text": "orig", "status": "pending"}
    )
    fake_client = MagicMock()
    fake_client.access_token = "tok"
    with patch.object(recruiter.service_client, "table", return_value=draft_chain), \
         patch.object(recruiter, "load_api_client", new=_async_return(fake_client)), \
         patch.object(recruiter, "persist_if_refreshed", new=_async_noop()):
        await recruiter.send_draft("u1", "d1", message="edited reply")
    fake_client.post.assert_called_once()
    endpoint, body = fake_client.post.call_args[0][0], fake_client.post.call_args[0][1]
    assert endpoint == "negotiations/n9/messages"
    assert body == {"message": "edited reply"}
    update = draft_chain.update.call_args[0][0]
    assert update["status"] == "sent"


@pytest.mark.asyncio
async def test_send_draft_saves_qa_memory_only_when_edited():
    from app.services import recruiter

    row = {
        "id": "d1", "negotiation_id": "n9", "draft_text": "orig",
        "question_text": "Готовы к переезду?", "status": "pending",
    }
    draft_chain = _fluent([row])
    draft_chain.maybe_single.return_value = draft_chain
    draft_chain.execute.return_value = SimpleNamespace(data=row)
    fake_client = MagicMock()
    fake_client.access_token = "tok"
    with patch.object(recruiter.service_client, "table", return_value=draft_chain), \
         patch.object(recruiter, "load_api_client", new=_async_return(fake_client)), \
         patch.object(recruiter, "persist_if_refreshed", new=_async_noop()), \
         patch.object(recruiter.qa_memory, "upsert", new=AsyncMock()) as up:
        await recruiter.send_draft("u1", "d1", message="edited reply")
    up.assert_awaited_once_with(
        "u1", "Готовы к переезду?", "edited reply", source="recruiter", vacancy_id="n9"
    )


@pytest.mark.asyncio
async def test_send_draft_skips_qa_memory_when_unchanged():
    from app.services import recruiter

    row = {
        "id": "d1", "negotiation_id": "n9", "draft_text": "orig",
        "question_text": "Готовы к переезду?", "status": "pending",
    }
    draft_chain = _fluent([row])
    draft_chain.maybe_single.return_value = draft_chain
    draft_chain.execute.return_value = SimpleNamespace(data=row)
    fake_client = MagicMock()
    fake_client.access_token = "tok"
    with patch.object(recruiter.service_client, "table", return_value=draft_chain), \
         patch.object(recruiter, "load_api_client", new=_async_return(fake_client)), \
         patch.object(recruiter, "persist_if_refreshed", new=_async_noop()), \
         patch.object(recruiter.qa_memory, "upsert", new=AsyncMock()) as up:
        await recruiter.send_draft("u1", "d1", message="orig")
    up.assert_not_awaited()
