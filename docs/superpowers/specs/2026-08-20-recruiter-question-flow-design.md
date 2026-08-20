# Recruiter Question Flow — Design

**Date:** 2026-08-20
**Status:** Approved for planning

## Goal

Today, when the recruiter agent (`ai/agent.py::HHAgent`, tools in
`ai/recruiter_tools.py`) can't confidently answer a recruiter message on its
own, `escalate_to_human` writes a **draft reply** the user has to read, judge,
and edit/send from the Todo page. That's a bad interface for the actual gap:
the agent doesn't need a copywriter, it needs one fact only the candidate has
(preferred interview time, a detail not in the resume, a judgment call).

Replace that draft-writing escalation with a **question-asking** escalation:
the agent asks the candidate one or more short, direct questions on the Todo
page; once answered, the agent is re-invoked with those answers fed back in as
a tool response and produces the actual reply via `answer_recruiter_question`
— which still lands as an editable/sendable draft, same as today. Nothing new
is auto-sent to hh.

## Scope

- Change the `escalate_to_human` tool's shape: `(draft, reason)` →
  `(questions: list[str], reason)`. Every existing escalation case (interview
  scheduling, info not in the resume, an unmatched quick-reply button)
  becomes one or more direct questions instead of a guessed draft.
- New `recruiter_questions` table + Todo page tab where the user answers.
- A resume mechanism that feeds the user's answers back into the agent as a
  LangChain tool response (no draft-writing side channel), driving it to call
  `answer_recruiter_question` (or `make_todo`, or ask again) for the real
  reply.
- Reuse the existing per-user poll loop (`worker/recruiter_poll.py`) to pick
  up answered question sets — no new process, no new IPC between the API and
  worker processes (they don't share memory; the API cannot reach into a
  running `HHAgent`).

Out of scope (explicitly, confirmed with the user during brainstorming):
- Dedup when the recruiter sends a new message before a pending question set
  is answered (a second, possibly overlapping question set can appear — rare,
  acceptable).
- Partial answers — the frontend requires every question in a set answered
  before submit.
- Instant (non-polling) resume — the reply is produced on the worker's next
  `RECRUITER_POLL_INTERVAL_S` (120s) cycle, matching how new employer messages
  are already picked up.

## Architecture

### Data flow

```
recruiter message arrives (existing poll_recruiter_chats)
  └─ agent decides it needs a fact from the candidate
       └─ escalate_to_human(questions=[...], reason=...)   [tool]
            └─ do_ask(ctx, questions, reason)
                 └─ recruiter.insert_question(...)   status='pending'
                 └─ notify(user_id, "recruiter_question", ...)

user opens Todo → "Вопросы" tab → answers all questions → submits
  └─ POST /api/recruiter/questions/{id}/answer  {answers: [...]}
       └─ recruiter.submit_answers(...)   status='pending' → 'answered'

next poll_recruiter_chats cycle for that user (existing loop, ≤120s later)
  └─ NEW: poll_answered_questions(user_id, agent)
       for each row where status='answered':
         ├─ refetch chat history (chatik.chat_messages, same as _process_chat)
         └─ agent.resume_recruiter_with_answers(
                negotiation_id, message_id, history, client,
                questions=row.questions, answers=row.answers, reason=row.reason,
                question_text=row.question_text,
                vacancy_id=..., vacancy_title=..., employer_name=...)
              └─ builds synthetic AIMessage(tool_calls=[escalate_to_human(...)])
                 + ToolMessage(tool_call_id=..., content=<Q→A pairs>)
                 + directive user turn ("кандидат ответил, теперь ответь")
              └─ _run_recruiter(...)  — SAME tool set as always:
                     answer_recruiter_question → recruiter_drafts (pending)
                     escalate_to_human (again)  → new recruiter_questions row
                     make_todo                  → recruiter_todos
         └─ recruiter.mark_question_completed(...)   status → 'completed'
```

The resume step deliberately does **not** use a LangGraph checkpointer/
interrupt. `agent.py` already documents why the recruiter agent has no
checkpointer (full history is re-passed every poll; a persisted thread would
double the context every cycle). Feeding the answer back as a *literal*
LangChain `ToolMessage` — constructed by hand, appended to the plain message
list already built from chat history — gets the same effect ("the model sees
its own tool call answered") without touching that decision.

### Components

**1. `ai/recruiter_tools.py` — `escalate_to_human` becomes ask-only**

```python
async def do_ask(ctx: RecruiterContext, questions: list[str], reason: str) -> str:
    await recruiter.insert_question(
        ctx.user_id, ctx.negotiation_id, ctx.message_id, questions, reason,
        question_text=ctx.question_text,
        vacancy_id=ctx.vacancy_id, vacancy_title=ctx.vacancy_title,
        employer_name=ctx.employer_name,
    )
    await notify(ctx.user_id, "recruiter_question", {"negotiation_id": ctx.negotiation_id})
    ctx.acted = True
    return "asked"


@tool(return_direct=True)
async def escalate_to_human(questions: list[str], reason: str, runtime: ToolRuntime[RecruiterContext]) -> str:
    """Задать кандидату 1-3 коротких прямых вопроса вместо того, чтобы гадать
    ответ рекрутёру самому. Вопросы уходят на страницу Задачи; как только
    кандидат ответит, тебя вызовут снова с его ответами, и тогда ты
    сформулируешь реальный ответ рекрутёру через answer_recruiter_question.

    КОГДА ИСПОЛЬЗОВАТЬ:
    - Назначение/перенос времени собеседования → спроси, когда удобно.
    - Данных нет в резюме (паспорт, ИИН, ссылки, зарплатные ожидания сверх
      того, что в резюме) → спроси конкретный факт.
    - Кнопки есть, но ни одна не подходит уверенно → перечисли варианты как
      вопрос, дай кандидату выбрать словами.
    - Любая неоднозначность, где домысливать вредно.

    КОГДА НЕ ИСПОЛЬЗОВАТЬ:
    - Ответ уже есть в резюме / кнопка очевидна → answer_recruiter_question.
    - Действие вне hh (форма/Telegram/звонок) → make_todo.

    PARAMETERS:
    - questions (list[str], required): 1-3 коротких прямых вопроса на русском,
      каждый — то, что реально нужно узнать у кандидата, не риторический.
      Пример: ["Когда вам удобно на собеседование?"]
      Пример (кнопки): ["Рекрутёр спрашивает про доход 250 000 - подходит?
      Варианты: Да / Рассматриваю выше."]
    - reason (str, required): одна фраза на русском — зачем спрашиваешь
      (контекст для UI). Пример: "назначение времени интервью".

    RETURNS: "asked" при успешном сохранении.
    """
    return await do_ask(runtime.context, questions, reason)
```

`do_escalate` is removed; its one remaining caller (`HHAgent._run_recruiter`'s
no-tool-call fallback) switches to `do_ask(ctx, [text], "агент не выбрал
действие, проверьте вручную")` — same safety net, new shape.

**2. `services/recruiter.py` — new persistence functions**, same pattern as
`insert_draft`/`list_drafts`/`discard_draft`:

- `insert_question(user_id, negotiation_id, message_id, questions, reason, *, question_text=None, vacancy_id=None, vacancy_title=None, employer_name=None) -> None`
- `list_questions(user_id) -> list[dict]` — `status='pending'`
- `list_answered_questions(user_id) -> list[dict]` — `status='answered'` (poller's work queue)
- `discard_question(user_id, question_id) -> None` — `status='discarded'`
- `submit_answers(user_id, question_id, answers: list[str]) -> None` — validates `len(answers) == len(questions)`, raises `ValueError` otherwise (mirrors `send_draft`'s `ValueError` on missing row); sets `status='answered'`, `answered_at=now()`
- `mark_question_completed(user_id, question_id) -> None` — `status='completed'`, `resolved_at=now()`

**3. `ai/agent.py` — `HHAgent.resume_recruiter_with_answers`**

New method next to `answer_recruiter`/`answer_recruiter_choice`, same lazy
`_recruiter_agent` construction:

```python
async def resume_recruiter_with_answers(
    self, negotiation_id, message_id, history, client, *,
    questions: list[str], answers: list[str], reason: str,
    question_text: str | None = None,
    vacancy_id=None, vacancy_title=None, employer_name=None,
) -> None:
    ...
    ctx = RecruiterContext(self.user_id, negotiation_id, message_id, client,
                            question_text=question_text, vacancy_id=vacancy_id,
                            vacancy_title=vacancy_title, employer_name=employer_name)
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
```

Imports `AIMessage`, `ToolMessage` from `langchain_core.messages` (already a
transitive dependency via `langchain_core.rate_limiters`, already imported in
this file).

**4. `worker/recruiter_poll.py` — `poll_answered_questions`**

Rejected/archived negotiations: `poll_recruiter_chats` already fetches
`states` (via `_negotiation_states`) once per user per cycle for the
`SKIP_STATES` check on new messages — `poll_answered_questions` reuses the
same `states` dict and skips (marks `completed` without invoking the agent)
any row whose `negotiation_id` is now in `SKIP_STATES`, so an answer to a
question from a chat that got rejected in the meantime doesn't produce a
pointless draft.

```python
async def poll_answered_questions(user_id: str, agent, client, states: dict[str, str]) -> None:
    for row in await recruiter.list_answered_questions(user_id):
        if states.get(row["negotiation_id"]) in SKIP_STATES:
            await recruiter.mark_question_completed(user_id, row["id"])
            continue
        try:
            msgs = await chatik.chat_messages(user_id, row["chat_id"], row["applicant_id"])
            await agent.resume_recruiter_with_answers(
                row["negotiation_id"], row["message_id"], _history(msgs), client,
                questions=row["questions"], answers=row["answers"], reason=row["reason"],
                question_text=row["question_text"], vacancy_id=row["vacancy_id"],
                vacancy_title=row["vacancy_title"], employer_name=row["employer_name"],
            )
        except Exception:
            logger.warning("recruiter poll: resume failed for question %s", row["id"], exc_info=True)
            continue  # leave status='answered' — retried next poll
        await recruiter.mark_question_completed(user_id, row["id"])
```

Note `chat_messages` needs `chat_id`/`applicant_id`, which live on the
`recruiter_chats` cursor row (`recruiter.get_cursor` already reads that
table) — `insert_question` stores `negotiation_id`; the poller resolves
`chat_id`/`applicant_id` the same way `_process_chat`'s caller (`chats`
from `chatik.recent_chats`) does today, OR — simpler — `recruiter_questions`
also stores `chat_id`/`applicant_id` captured at ask-time (`ctx` doesn't
currently carry them, `RecruiterContext` would need those two fields plumbed
in from `_process_chat`, mirroring how `vacancy_id` already got plumbed
through in the in-flight uncommitted change to this file). This is a
mechanical, low-risk addition — flagged here so the implementation plan
budgets a step for it instead of discovering it mid-code.

Called from `poll_recruiter_chats`, once per user per cycle, before the
existing per-chat loop (so a fresh reply from an answered question doesn't
sit an extra cycle behind new-message processing):

```python
async def poll_recruiter_chats(user_id: str, agent) -> None:
    ...
    client = await load_api_client(user_id) / None as today ...
    states = {} if client is None else await _negotiation_states(client, user_id)
    await poll_answered_questions(user_id, agent, client, states)
    for ref in chats:
        ...
```

**5. `ai/prompts.py`**

`RECRUITER_TOOLS_BLOCK`'s `escalate_to_human` line changes from describing a
`draft` to describing `questions`:

```
- escalate_to_human(questions, reason): всё неоднозначное - назначение
  собеседования, запрос данных не из резюме, кнопки без подходящего варианта.
  Задай кандидату 1-3 коротких прямых вопроса вместо того, чтобы угадывать
  ответ. reason - кратко почему спрашиваешь.
```

`RECRUITER_ROLE_BLOCK`, `RECRUITER_POSITIONING_BLOCKS`, `RECRUITER_SKIP_BLOCK`
are unaffected.

**6. `services/notifications.py`**

Add `"recruiter_question"` to the `NotificationType` Literal.

**7. Database — migration `033_recruiter_questions.sql`**

```sql
CREATE TABLE IF NOT EXISTS recruiter_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES profiles(id) ON DELETE CASCADE,
  negotiation_id text NOT NULL,
  chat_id text,
  applicant_id text,
  message_id text,
  questions jsonb NOT NULL,
  answers jsonb,
  reason text,
  question_text text,
  vacancy_id text,
  vacancy_title text,
  employer_name text,
  status text NOT NULL DEFAULT 'pending',   -- 'pending'|'answered'|'completed'|'discarded'
  created_at timestamptz DEFAULT now(),
  answered_at timestamptz,
  resolved_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_recruiter_questions_user_status
  ON recruiter_questions (user_id, status);

ALTER TABLE recruiter_questions ENABLE ROW LEVEL SECURITY;  -- service_role only, no policies
```

**8. API — `api/recruiter.py` + `schemas/recruiter.py`**

```python
class AnswerQuestionsRequest(BaseModel):
    answers: list[str]

@router.get("/questions")
async def list_questions(user_id=Depends(get_current_user)) -> list[dict]:
    return await recruiter.list_questions(user_id)

@router.post("/questions/{question_id}/answer", response_model=OkResponse)
async def answer_questions(question_id: str, body: AnswerQuestionsRequest, user_id=Depends(get_current_user)) -> OkResponse:
    await recruiter.submit_answers(user_id, question_id, body.answers)
    return OkResponse()

@router.post("/questions/{question_id}/discard", response_model=OkResponse)
async def discard_question(question_id: str, user_id=Depends(get_current_user)) -> OkResponse:
    await recruiter.discard_question(user_id, question_id)
    return OkResponse()
```

`submit_answers`' `ValueError` on length mismatch surfaces as a 400 the same
way other services' `ValueError`s already do in this codebase (check existing
exception-handler wiring — likely a generic handler in `main.py`; if none
exists yet, add a minimal one scoped to this router, matching existing error
conventions).

**9. Frontend**

`hooks/useRecruiter.ts`:
```ts
export type QuestionSet = {
  id: string; negotiation_id: string;
  questions: string[]; reason: string | null; question_text: string | null;
  vacancy_id: string | null; vacancy_title: string | null; employer_name: string | null;
  created_at: string;
};
```
`RecruiterData` gains `questions: QuestionSet[]`; the hook gains
`answerQuestions(id, answers: string[])` and `discardQuestion(id)`, same
optimistic-removal pattern as `sendDraft`/`discardDraft`.

`app/(app)/todo/page.tsx`: 4th tab `{ id: "questions", label: "Вопросы" }` in
`SECTIONS`. New `QuestionsSection`/`QuestionCard` component: `VacancyMeta` +
`ChatHistory` (both reused as-is) + `reason` + `question_text` block (same
markup as `DraftCard`'s "Вопрос рекрутёра" block) + one text input per item in
`questions`, labeled with the question text + a "Отправить ответы" button
disabled until every input is non-empty + a "Отклонить" ghost button. Empty
state icon: `ISpark` (matches the "AI is asking" framing; no dedicated
question-mark icon exists in `icons.tsx`).

`lib/nav-counts.ts`: `NavCountsInput` gains `questions: unknown[]`; `todo`
count becomes `formDrafts.length + recruiterDrafts.length + todos.length +
questions.length`. `hooks/useNavCounts.ts` passes `questions` from
`useRecruiter()` through.

`components/notifications-drawer.tsx`: add `recruiter_question` to
`ICON`/`COLOR`/`TITLE` (icon: reuse `ICheck`, color: `var(--ok)`, title:
"Вопрос от ИИ-агента").
`app/(app)/dashboard/realtime-bridge.tsx`: add `recruiter_question` to
`TYPE_KIND` (`"info"`) / `TYPE_TITLE` ("ИИ-агент спрашивает вас").

## Testing

- `backend/tests/test_recruiter_tools.py` (or wherever `do_answer`/`do_escalate`
  are currently unit-tested — locate via existing test file for
  `recruiter_tools.py`): replace `do_escalate` cases with `do_ask`, assert
  `insert_question` called with the right `questions`/`reason`, `acted=True`.
- `backend/tests/test_recruiter_poll.py`: new tests for `poll_answered_questions`
  — resume called with correct args, `mark_question_completed` called on
  success, row left `answered` (not advanced) on the agent call raising.
- A `resume_recruiter_with_answers` test grounded in `agent.py`'s existing
  recruiter-agent tests (if any) — assert the synthetic `AIMessage`/
  `ToolMessage` pair is well-formed and reaches `_recruiter_agent.ainvoke`.
- Frontend: no existing test coverage on `useRecruiter.ts`/Todo page beyond
  the pure-function `lib/` tests — `computeNavCounts` gets a case for
  `questions.length` contributing to the badge (mirrors existing cases for
  `formDrafts`/`recruiterDrafts`/`todos`).

## Migration / rollout note

`escalate_to_human`'s signature change is a breaking change to the tool
contract, but it only affects the live in-process agent (rebuilt per
`HHAgent` instance, never persisted) — no backward-compat shim needed. Any
`recruiter_drafts` rows already created by the old draft-writing
`escalate_to_human` stay exactly as they are (still shown, still
sendable/discardable in "Черновики") — this change only affects *future*
escalations.
