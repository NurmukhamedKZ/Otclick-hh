"""Central AI interface for hh automation.

One HHAgent per worker runner (per user). Wraps a single langchain ChatOpenAI
(self.llm) shared by every AI path — form-test answers, cover letters, and the
recruiter chat agent. No per-call LLM construction.
"""

from __future__ import annotations

import json
import logging

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.ai.prompts import (
    build_chat_prompt,
    build_fill_prompt,
    build_fill_system_prompt,
    build_recruiter_prompt,
    sanitize_ai_text,
)
from app.ai.recruiter_tools import RECRUITER_TOOLS, RecruiterContext, do_ask
from app.config import settings
from app.services import qa_memory
from app.services.cover_letter import generate as _generate_cover_letter
from app.services.form_filler import FillStatus, prepare_form_answers
from app.services.relevance import Verdict, filter_relevant

logger = logging.getLogger(__name__)


class _FillField(BaseModel):
    ref: str
    value: str
    source: str = Field(default="ai")


class _FillPlan(BaseModel):
    fields: list[_FillField] = Field(default_factory=list)


def snap_to_option(value: str, options: list[str]) -> str | None:
    """Map the model's answer onto a real option. None ⇒ no confident match, so
    the caller drops the field instead of typing something the widget rejects."""
    want = (value or "").strip().lower()
    if not want:
        return None
    for opt in options:
        if str(opt).strip().lower() == want:
            return str(opt)
    for opt in options:
        text = str(opt).strip().lower()
        if want in text or text in want:
            return str(opt)
    return None


class HHAgent:
    """Single entry point for all LLM work. Construct once per runner/user."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        # ChatOpenAI raises without an api key; empty key → fallback paths use None.
        self.llm = (
            ChatOpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                model=settings.OPENAI_MODEL,
                # gpt-5-family models default to a non-"none" reasoning effort
                # server-side, which OpenAI's chat/completions endpoint refuses
                # to combine with function tools ("Function tools with
                # reasoning_effort are not supported ... set reasoning_effort
                # to 'none'"). The recruiter agent (create_agent + tools) hit
                # this on every single call — force it off.
                reasoning_effort="none",
                rate_limiter=InMemoryRateLimiter(
                    requests_per_second=settings.OPENAI_RATE_LIMIT / 60.0
                ),
            )
            if settings.OPENAI_API_KEY
            else None
        )
        self._recruiter_agent = None
        self._resume_summary: str | None = None
        self._full_resumes: dict[str, dict] = {}
        self._relevance_summaries: dict[str, str] = {}

    async def write_form_answers(
        self, user_id: str, resume_id: str, vacancy: dict
    ) -> tuple[FillStatus, list[dict]]:
        """Generate vacancy-test answers — caller persists for user approval."""
        return await prepare_form_answers(self.llm, user_id, resume_id, vacancy)

    async def write_cover_letter(
        self, user_id: str, vacancy: dict, resume: dict, resume_uuid: str
    ) -> str:
        """Cover letter text. PG cache → self.llm → fallback template.

        `resume` arg is the sparse DB row (title only). Pull the full hh resume
        payload so the prompt is grounded in the candidate's real experience —
        fall back to the sparse row if the fetch fails."""
        full = await self._load_full_resume(resume_uuid)
        return await _generate_cover_letter(
            self.llm,
            user_id=user_id,
            vacancy=vacancy,
            resume=full or resume,
            resume_uuid=resume_uuid,
        )

    async def filter_relevant_vacancies(
        self, resume_id: str, items: list[dict]
    ) -> dict[str, Verdict]:
        """Per-vacancy relevance verdicts grounded in the filter's resume.

        items: {id, name, snippet_requirement, snippet_responsibility}.
        Fail-open: no llm → all relevant (handled inside filter_relevant)."""
        summary = await self._summary_for(resume_id)
        return filter_relevant(self.llm, summary, items)

    # --- browser extension ---------------------------------------------------

    async def fill_form_fields(
        self,
        context: str,
        page_text: str,
        snapshot: list[dict],
        known: set[str] | None = None,
    ) -> list[dict]:
        """Decide one value per snapshot field for the browser extension.

        Empty list when there is no LLM, the call fails, or nothing could be
        answered confidently — the extension then leaves those fields to the
        user. Never invents a value for a field the context doesn't cover."""
        if not self.llm or not snapshot:
            return []
        try:
            plan = await self.llm.with_structured_output(_FillPlan).ainvoke(
                [
                    ("system", build_fill_system_prompt()),
                    ("human", build_fill_prompt(context, page_text, snapshot)),
                ]
            )
        except Exception:
            logger.warning("extension fill: llm call failed", exc_info=True)
            return []
        plan = _FillPlan.model_validate(plan) if isinstance(plan, dict) else plan
        by_ref = {str(el.get("ref")): el for el in snapshot}
        out: list[dict] = []
        for f in plan.fields:
            el = by_ref.get(f.ref)
            if el is None:
                continue
            value = sanitize_ai_text(f.value).strip()
            if not value:
                continue
            options = [str(o) for o in (el.get("options") or [])]
            if options:
                snapped = snap_to_option(value, options)
                if snapped is None:
                    continue
                value = snapped
            source = f.source if f.source in ("profile", "ai") else "ai"
            if source == "profile" and known is not None and value.lower() not in known:
                source = "ai"  # not a verbatim fact — don't label it as one
            out.append(
                {
                    "ref": f.ref,
                    "selector": el.get("selector") or "",
                    "field_type": el.get("field_type") or "text",
                    "value": value,
                    "source": source,
                    "required": bool(el.get("required")),
                }
            )
        return out

    MAX_CHAT_TURNS = 20

    async def chat(
        self, context: str, messages: list[dict], page_text: str | None = None
    ) -> str:
        """Free-form chat grounded in the candidate's resume + Q&A memory.

        History comes from the extension (nothing is stored server-side), so
        only the last MAX_CHAT_TURNS messages are forwarded."""
        if not self.llm:
            return "ИИ недоступен: не настроен OPENAI_API_KEY."
        msgs: list[tuple[str, str]] = [("system", build_chat_prompt(context, page_text))]
        for m in messages[-self.MAX_CHAT_TURNS :]:
            role = "ai" if m.get("role") == "assistant" else "human"
            content = str(m.get("content") or "").strip()
            if content:
                msgs.append((role, content))
        try:
            resp = await self.llm.ainvoke(msgs)
        except Exception:
            logger.warning("extension chat: llm call failed", exc_info=True)
            return "Не удалось получить ответ. Попробуйте ещё раз."
        content = resp.content
        if isinstance(content, list):  # some models return content parts
            content = " ".join(str(c) for c in content)
        return sanitize_ai_text(content)

    async def _summary_for(self, resume_id: str) -> str:
        """Resume summary for a specific resume_id, cached. '' on failure."""
        if resume_id in self._relevance_summaries:
            return self._relevance_summaries[resume_id]
        from app.services.form_filler import _resume_summary, load_resume
        try:
            resume = await load_resume(self.user_id, resume_id)
            summary = _resume_summary(resume)
        except Exception:
            logger.warning(
                "relevance: resume load failed for %s/%s — ungrounded",
                self.user_id, resume_id, exc_info=True,
            )
            summary = ""
        self._relevance_summaries[resume_id] = summary
        return summary

    async def _load_full_resume(self, resume_uuid: str) -> dict | None:
        """Full hh resume payload, cached per resume_uuid (same as the
        recruiter path's _resume_summary). None on failure → caller falls back."""
        if resume_uuid in self._full_resumes:
            return self._full_resumes[resume_uuid]
        from app.services.form_filler import load_resume
        try:
            resume = await load_resume(self.user_id, resume_uuid)
            self._full_resumes[resume_uuid] = resume
            return resume
        except Exception:
            logger.warning(
                "cover_letter: full resume load failed for %s — using sparse row",
                self.user_id, exc_info=True,
            )
            return None

    async def _load_resume_summary(self) -> str:
        if self._resume_summary is not None:
            return self._resume_summary
        from app.services.form_filler import _resume_summary, load_resume
        try:
            resume = await load_resume(self.user_id)
            self._resume_summary = _resume_summary(resume)
        except Exception:
            logger.warning(
                "recruiter: resume load failed for %s — ungrounded", self.user_id, exc_info=True
            )
            self._resume_summary = ""
        return self._resume_summary

    def _build_recruiter_agent(self, system_prompt: str):
        # No checkpointer on purpose: the caller passes the FULL chat history on
        # every poll, so a persisted per-thread state would be appended to that
        # history each cycle — the context (and the token bill) doubled every
        # 2 minutes, and InMemorySaver never released a single chat for the
        # whole lifetime of the worker process. History in, nothing retained.
        return create_agent(
            self.llm,
            tools=RECRUITER_TOOLS,
            system_prompt=system_prompt,
            context_schema=RecruiterContext,
        )

    async def answer_recruiter(
        self, negotiation_id: str, message_id: str,
        history: list[tuple[str, str]], client,
        question_text: str | None = None,
        chat_id: str | None = None, applicant_id: str | None = None,
        vacancy_id: str | None = None, vacancy_title: str | None = None,
        employer_name: str | None = None,
    ) -> None:
        """Decide + act on the latest recruiter message via tools (send/escalate/
        todo) or no-op. Conversation memory keyed by negotiation_id. The
        `question_text` is the verbatim recruiter message and is persisted
        with any draft so the user can review it on the Todo screen."""
        if not settings.OPENAI_API_KEY:
            logger.info("recruiter: no OPENAI_API_KEY — skipping chat %s", negotiation_id)
            return
        if self._recruiter_agent is None:
            summary = await self._load_resume_summary()
            qa = await qa_memory.prompt_block(self.user_id)
            # ponytail: prompt frozen for the agent's lifetime — Q&A edits land
            # on the next runner restart; rebuild per message if that's too slow.
            self._recruiter_agent = self._build_recruiter_agent(
                build_recruiter_prompt(summary, qa)
            )
        ctx = RecruiterContext(
            self.user_id, negotiation_id, message_id, client,
            question_text=question_text,
            chat_id=chat_id, applicant_id=applicant_id,
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
        await self._run_recruiter(history, ctx)

    async def answer_recruiter_choice(
        self, negotiation_id: str, message_id: str,
        history: list[tuple[str, str]], client, question: str, labels: list[str],
        chat_id: str | None = None, applicant_id: str | None = None,
        vacancy_id: str | None = None, vacancy_title: str | None = None,
        employer_name: str | None = None,
    ) -> None:
        """Answer a robot-recruiter quick-reply question via the langchain agent.

        Same agent/tools/memory as answer_recruiter — but the chatik buttons are
        injected into the context (`quick_reply_labels`) plus a directive turn,
        so the agent picks `answer_recruiter_question` with an exact label (no
        loop), or `escalate_to_human` when no option fits. hh's bot accepts only
        a verbatim label, so free-text replies must never be used here."""
        if not settings.OPENAI_API_KEY:
            logger.info("recruiter: no OPENAI_API_KEY — skipping bot chat %s", negotiation_id)
            return
        if self._recruiter_agent is None:
            summary = await self._load_resume_summary()
            qa = await qa_memory.prompt_block(self.user_id)
            # ponytail: prompt frozen for the agent's lifetime — Q&A edits land
            # on the next runner restart; rebuild per message if that's too slow.
            self._recruiter_agent = self._build_recruiter_agent(
                build_recruiter_prompt(summary, qa)
            )
        ctx = RecruiterContext(
            self.user_id, negotiation_id, message_id, client,
            question_text=question, quick_reply_labels=labels,
            chat_id=chat_id, applicant_id=applicant_id,
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
        directive = (
            "Последнее сообщение - вопрос робота-рекрутёра с кнопками-вариантами. "
            f"Варианты ответа: {labels}. Выбери ОДИН правдивый по резюме и вызови "
            "answer_recruiter_question с его ТОЧНЫМ текстом. Если ни один не "
            "подходит или неоднозначно - escalate_to_human, где reason = причина "
            '(почему не выбрал) И перечисление этих вариантов через " / ".'
        )
        await self._run_recruiter(history + [("user", directive)], ctx)

    async def resume_recruiter_with_answers(
        self, negotiation_id: str, message_id: str,
        history: list[tuple[str, str]], client, *,
        questions: list[str], answers: list[str], reason: str,
        question_text: str | None = None,
        chat_id: str | None = None, applicant_id: str | None = None,
        vacancy_id=None, vacancy_title=None, employer_name=None,
    ) -> None:
        """Re-invoke the recruiter agent after the candidate answered a pending
        question set. Feeds the answers back as a literal LangChain ToolMessage
        (the model "sees" its own escalate_to_human call answered), plus a
        directive turn, so it produces the real reply via answer_recruiter_question
        (or asks again / makes a todo). No checkpointer — the plain message list
        is extended, same as answer_recruiter/answer_recruiter_choice."""
        if not settings.OPENAI_API_KEY:
            logger.info("recruiter: no OPENAI_API_KEY — skipping resume %s", negotiation_id)
            return
        if self._recruiter_agent is None:
            summary = await self._load_resume_summary()
            qa = await qa_memory.prompt_block(self.user_id)
            self._recruiter_agent = self._build_recruiter_agent(
                build_recruiter_prompt(summary, qa)
            )
        ctx = RecruiterContext(
            self.user_id, negotiation_id, message_id, client,
            question_text=question_text,
            chat_id=chat_id, applicant_id=applicant_id,
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
        call_id = f"call_{message_id}"
        qa_pairs = json.dumps(dict(zip(questions, answers)), ensure_ascii=False)
        synthetic = [
            AIMessage(content="", tool_calls=[{
                "name": "escalate_to_human",
                "args": {"questions": questions, "reason": reason},
                "id": call_id,
            }]),
            ToolMessage(content=qa_pairs, tool_call_id=call_id),
            ("user", "Кандидат ответил на твои вопросы (см. tool response выше). "
                     "Сформулируй финальный ответ рекрутёру через "
                     "answer_recruiter_question. Если нужно уточнить что-то ещё "
                     "— снова escalate_to_human."),
        ]
        await self._run_recruiter(history + synthetic, ctx)

    async def _run_recruiter(self, messages: list[tuple[str, str]], ctx) -> None:
        """Invoke the recruiter agent and guarantee an outcome.

        The model may reply with plain text and call nothing — that used to
        silently drop the recruiter's message. Only an explicit "SKIP" (rejection
        / "we'll get back to you", per the prompt) is allowed to end without a
        side effect; anything else is escalated to the user as a draft."""
        nid = ctx.negotiation_id
        result = await self._recruiter_agent.ainvoke(
            {"messages": messages},
            config={
                "configurable": {"thread_id": nid},
                "metadata": {"thread_id": nid, "session_id": nid},
            },
            context=ctx,
        )
        if ctx.acted:
            return
        final = result["messages"][-1].content if result.get("messages") else ""
        text = (final if isinstance(final, str) else str(final)).strip()
        if text.upper().strip(".!") == "SKIP":
            logger.info("recruiter: chat %s skipped (отказ / в обработке)", nid)
            return
        logger.warning("recruiter: chat %s — no tool call, escalating", nid)
        await do_ask(ctx, [text], "агент не выбрал действие, проверьте вручную")
