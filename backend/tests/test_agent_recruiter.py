import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _reply(text):
    """Agent result shaped like langchain's: last message carries the model text."""
    return {"messages": [MagicMock(content=text)]}


def test_build_recruiter_prompt_embeds_resume_and_rules():
    from backend.app.ai.prompts import build_recruiter_prompt
    p = build_recruiter_prompt("Python dev, 3 года опыта")
    assert "Python dev, 3 года опыта" in p
    assert "answer_recruiter_question" in p
    assert "escalate_to_human" in p
    assert "make_todo" in p
    assert "Отказ" in p or "отказ" in p


@pytest.mark.asyncio
async def test_answer_recruiter_skips_when_no_api_key():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    with patch("app.ai.agent.settings") as s:
        s.OPENAI_API_KEY = ""
        agent._build_recruiter_agent = MagicMock(side_effect=AssertionError("must not build"))
        await agent.answer_recruiter("n1", "m1", [("user", "hi")], client=MagicMock())


@pytest.mark.asyncio
async def test_answer_recruiter_invokes_agent_with_context():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value=_reply("SKIP"))
    agent._recruiter_agent = fake_agent
    agent._resume_summary = "ready"  # skip resume load
    with patch("app.ai.agent.settings") as s:
        s.OPENAI_API_KEY = "sk-test"
        await agent.answer_recruiter("n9", "m5", [("user", "Какая зарплата?")], client=MagicMock(access_token="t"))
    _, kwargs = fake_agent.ainvoke.call_args
    assert kwargs["config"]["configurable"]["thread_id"] == "n9"
    ctx = kwargs["context"]
    assert ctx.negotiation_id == "n9" and ctx.message_id == "m5" and ctx.user_id == "u1"


@pytest.mark.asyncio
async def test_answer_recruiter_choice_invokes_agent_with_labels():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value=_reply("SKIP"))
    agent._recruiter_agent = fake_agent
    agent._resume_summary = "ready"
    labels = ["Да", "Рассматриваю зарплату выше"]
    with patch("app.ai.agent.settings") as s:
        s.OPENAI_API_KEY = "sk-test"
        await agent.answer_recruiter_choice(
            "n9", "m5", [("user", "Подходит 100 тыс?")],
            client=MagicMock(access_token="t"), question="Подходит 100 тыс?", labels=labels,
        )
    args, kwargs = fake_agent.ainvoke.call_args
    # buttons injected into the agent context...
    ctx = kwargs["context"]
    assert ctx.quick_reply_labels == labels and ctx.negotiation_id == "n9"
    # ...and a directive turn appended so the agent picks answer_recruiter_question
    msgs = args[0]["messages"]
    assert any("answer_recruiter_question" in m[1] for m in msgs if isinstance(m, tuple))
    assert kwargs["config"]["configurable"]["thread_id"] == "n9"


@pytest.mark.asyncio
async def test_answer_recruiter_choice_skips_when_no_api_key():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    with patch("app.ai.agent.settings") as s:
        s.OPENAI_API_KEY = ""
        agent._build_recruiter_agent = MagicMock(side_effect=AssertionError("must not build"))
        await agent.answer_recruiter_choice(
            "n9", "m5", [], client=MagicMock(), question="q", labels=["Да", "Нет"]
        )


@pytest.mark.asyncio
async def test_no_tool_call_escalates_instead_of_dropping():
    """Model answered with plain text and called nothing -> user gets a draft."""
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value=_reply("Да, опыт с Claude API есть."))
    agent._recruiter_agent = fake_agent
    agent._resume_summary = "ready"
    with patch("app.ai.agent.settings") as s, \
         patch("app.ai.agent.do_escalate", new=AsyncMock()) as esc:
        s.OPENAI_API_KEY = "sk-test"
        await agent.answer_recruiter("n1", "m1", [("user", "Есть опыт с Claude API?")],
                                     client=MagicMock(access_token="t"))
    assert esc.await_count == 1
    assert esc.await_args[0][1] == "Да, опыт с Claude API есть."


@pytest.mark.asyncio
async def test_skip_reply_does_not_escalate():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value=_reply("SKIP"))
    agent._recruiter_agent = fake_agent
    agent._resume_summary = "ready"
    with patch("app.ai.agent.settings") as s, \
         patch("app.ai.agent.do_escalate", new=AsyncMock()) as esc:
        s.OPENAI_API_KEY = "sk-test"
        await agent.answer_recruiter("n1", "m1", [("user", "Мы не готовы пригласить вас.")],
                                     client=MagicMock(access_token="t"))
    assert esc.await_count == 0


@pytest.mark.asyncio
async def test_tool_call_suppresses_fallback():
    from app.ai.agent import HHAgent
    from app.ai.recruiter_tools import RecruiterContext
    agent = HHAgent("u1")

    async def _invoke(payload, config=None, context=None):
        context.acted = True          # a tool ran
        return _reply("escalated")

    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(side_effect=_invoke)
    agent._recruiter_agent = fake_agent
    agent._resume_summary = "ready"
    with patch("app.ai.agent.settings") as s, \
         patch("app.ai.agent.do_escalate", new=AsyncMock()) as esc:
        s.OPENAI_API_KEY = "sk-test"
        await agent.answer_recruiter("n1", "m1", [("user", "q")], client=MagicMock(access_token="t"))
    assert esc.await_count == 0
    assert isinstance(fake_agent.ainvoke.await_args.kwargs["context"], RecruiterContext)
