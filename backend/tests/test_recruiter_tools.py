import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import MagicMock, patch

import pytest


class _Spy:
    def __init__(self):
        self.calls = []
    async def __call__(self, *args, **kwargs):
        self.calls.append(args)


def _ctx(client=None, labels=None):
    from app.ai.recruiter_tools import RecruiterContext
    return RecruiterContext(user_id="u1", negotiation_id="n9", message_id="m5",
                            client=client or MagicMock(access_token="tok"),
                            quick_reply_labels=labels)


@pytest.mark.asyncio
async def test_do_answer_drafts_instead_of_posting():
    # answering never auto-posts to hh — it queues a draft (empty reason) for
    # the user to approve on the Todo screen, and never touches the hh client.
    from app.ai import recruiter_tools as rt
    ins, notif = _Spy(), _Spy()
    ctx = _ctx()
    with patch.object(rt.recruiter, "insert_draft", new=ins), patch.object(rt, "notify", new=notif):
        out = await rt.do_answer(ctx, "Зарплата от 300к")
    ctx.client.post.assert_not_called()
    assert ins.calls[0] == ("u1", "n9", "m5", "Зарплата от 300к", "")
    assert notif.calls[0][1] == "recruiter_draft"
    assert out == "escalated"


@pytest.mark.asyncio
async def test_do_escalate_inserts_draft_and_notifies():
    from app.ai import recruiter_tools as rt
    ins, notif = _Spy(), _Spy()
    with patch.object(rt.recruiter, "insert_draft", new=ins), patch.object(rt, "notify", new=notif):
        out = await rt.do_escalate(_ctx(), "Давайте во вторник", "scheduling")
    assert ins.calls[0] == ("u1", "n9", "m5", "Давайте во вторник", "scheduling")
    assert notif.calls[0][1] == "recruiter_draft"
    assert out == "escalated"


@pytest.mark.asyncio
async def test_do_todo_inserts_and_notifies():
    from app.ai import recruiter_tools as rt
    ins, notif = _Spy(), _Spy()
    with patch.object(rt.recruiter, "insert_todo", new=ins), patch.object(rt, "notify", new=notif):
        out = await rt.do_todo(_ctx(), "Заполнить форму", "до пятницы", "https://forms.gle/x")
    assert ins.calls[0] == ("u1", "n9", "m5", "Заполнить форму", "до пятницы", "https://forms.gle/x")
    assert notif.calls[0][1] == "recruiter_todo"
    assert out == "todo_created"


@pytest.mark.asyncio
async def test_do_answer_drafts_exact_label_when_buttons_present():
    from app.ai import recruiter_tools as rt
    # model echoed the label inside a sentence — must resolve to the verbatim
    # label ('Нет ' with its trailing space) and queue it as a draft as-is (no
    # sanitize), never posting, so the bot still matches when the user sends it.
    ins, notif = _Spy(), _Spy()
    ctx = _ctx(labels=["Да, есть", "Нет "])
    with patch.object(rt.recruiter, "insert_draft", new=ins), patch.object(rt, "notify", new=notif):
        out = await rt.do_answer(ctx, "Думаю, Нет")
    ctx.client.post.assert_not_called()
    assert ins.calls[0] == ("u1", "n9", "m5", "Нет ", "")
    assert notif.calls[0][1] == "recruiter_draft"
    assert out == "escalated"


@pytest.mark.asyncio
async def test_do_answer_rejects_unmatched_label():
    from app.ai import recruiter_tools as rt
    ctx = _ctx(labels=["Да", "Нет"])
    out = await rt.do_answer(ctx, "Перезвоните завтра")
    ctx.client.post.assert_not_called()  # never send free text disguised as a label
    assert out.startswith("error:")


def test_match_label_prefers_exact_over_substring():
    from app.ai.recruiter_tools import match_label
    assert match_label(["Да", "Да, есть"], "Да") == "Да"
    assert match_label(["Yes", "No"], "yes") == "Yes"
    assert match_label(["Да", "Нет"], "ничего") is None


def test_recruiter_tools_list_has_all_tools():
    from app.ai.recruiter_tools import RECRUITER_TOOLS
    names = {t.name for t in RECRUITER_TOOLS}
    assert names == {
        "answer_recruiter_question", "escalate_to_human", "make_todo",
    }
