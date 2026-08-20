# Recruiter Question Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the recruiter agent's draft-writing `escalate_to_human` tool with a question-asking one: the agent asks the candidate 1-3 direct questions on the Todo page instead of guessing a reply; once answered, the agent is re-invoked with the answers fed back as a literal LangChain tool response and produces the real reply via `answer_recruiter_question` (still landing as an editable/sendable draft — nothing auto-sent to hh).

**Architecture:** New `recruiter_questions` table + service functions mirror the existing `recruiter_drafts`/`recruiter_todos` pattern. The `escalate_to_human` tool's side effect switches from `insert_draft` to `insert_question`. A new `HHAgent.resume_recruiter_with_answers` method builds a synthetic `AIMessage(tool_calls=[...])` + `ToolMessage(answers)` pair and re-invokes the same (checkpointer-less) recruiter agent. A new poller step, `poll_answered_questions`, reuses the existing per-user `recruiter_poll` cycle (≤120s cadence) to pick up answered rows and drive the resume — no new process, no IPC between the API and worker processes.

**Tech Stack:** FastAPI + Supabase (Postgres) backend, LangChain `create_agent` (`langchain_core.messages.AIMessage`/`ToolMessage`), Next.js App Router + React Query frontend.

**Spec:** `docs/superpowers/specs/2026-08-20-recruiter-question-flow-design.md`

## Global Constraints

- `escalate_to_human`'s signature changes from `(draft: str, reason: str)` to `(questions: list[str], reason: str)`. This is a breaking change to the live in-process tool contract only (never persisted) — no back-compat shim.
- **Correction vs. the spec:** `do_escalate` (in `ai/recruiter_tools.py`) is **not removed**. `do_answer`'s free-text branch (`answer_recruiter_question` with no quick-reply buttons) calls `do_escalate(ctx, message, "")` internally to reuse its `insert_draft` + notify + `acted=True` side effect — that call site is unrelated to the `escalate_to_human` tool and must keep working unchanged. Only the `escalate_to_human` **tool** and the `_run_recruiter` no-tool-call fallback switch to the new `do_ask`.
- No LangGraph checkpointer/interrupt. The resume is a hand-built `AIMessage`/`ToolMessage` pair appended to the plain message list already passed on every poll — matches the existing "no checkpointer" decision documented in `ai/agent.py::_build_recruiter_agent`.
- The final reply is produced on the worker's next `RECRUITER_POLL_INTERVAL_S` (120s) cycle after the user answers — not instantly from the API process (API and worker are separate processes; the API cannot reach into a running `HHAgent`).
- Every escalation outcome still lands as an editable/sendable draft in "Черновики" via the existing `recruiter_drafts` flow — nothing is ever auto-sent to hh.
- `recruiter_questions`: service_role only, `ENABLE ROW LEVEL SECURITY` with no policies — same pattern as `recruiter_drafts`/`recruiter_todos` (`infra/supabase/migrations/010_recruiter_chats.sql`).
- Frontend: the "Отправить ответы" button on a question card stays disabled until every question has a non-empty answer — no partial submits.
- Follow existing code conventions exactly: `_run(fn)` executor pattern in `services/recruiter.py`, `_Spy`/`_fluent`/`_ctx` test helpers already in the recruiter test files, `ValueError` → `HTTPException(400)` pattern from `api/forms.py`.

---

### Task 1: Migration — `recruiter_questions` table

**Files:**
- Create: `infra/supabase/migrations/033_recruiter_questions.sql`

**Interfaces:**
- Produces: table `recruiter_questions` with columns `id, user_id, negotiation_id, chat_id, applicant_id, message_id, questions (jsonb), answers (jsonb), reason, question_text, vacancy_id, vacancy_title, employer_name, status, created_at, answered_at, resolved_at`. `status` values: `'pending'|'answered'|'completed'|'discarded'`.

- [ ] **Step 1: Write the migration file**

```sql
-- ============================================================
-- 033_recruiter_questions.sql — recruiter agent asks the candidate direct
-- questions instead of drafting a guessed reply (escalate_to_human). The
-- candidate answers on the Todo page; the worker poller resumes the agent
-- with those answers fed back as a tool response, producing the real reply
-- via answer_recruiter_question (still a recruiter_drafts row).
-- Run AFTER 032_recruiter_draft_vacancy.sql
-- ============================================================

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
  status text NOT NULL DEFAULT 'pending',  -- 'pending'|'answered'|'completed'|'discarded'
  created_at timestamptz DEFAULT now(),
  answered_at timestamptz,
  resolved_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_recruiter_questions_user_status
  ON recruiter_questions (user_id, status);

ALTER TABLE recruiter_questions ENABLE ROW LEVEL SECURITY;  -- service_role only, no policies
```

- [ ] **Step 2: Verify against the local stack (best-effort)**

If the local Supabase stack is up (`docker compose ps` shows `kong`/`db` as `healthy`), run:

```bash
docker compose up migrate
docker compose logs migrate | tail -20
```

Expected: log shows `033_recruiter_questions.sql` applied, no errors. If the stack isn't running, skip this step — the migration lands on the next `docker compose up` (the `migrate` service applies every migration not yet in `public.schema_migrations`, tracked automatically).

- [ ] **Step 3: Commit**

```bash
git add infra/supabase/migrations/033_recruiter_questions.sql
git commit -m "feat(db): add recruiter_questions table for the question-flow feature"
```

---

### Task 2: `services/recruiter.py` — question persistence functions

**Files:**
- Modify: `backend/app/services/recruiter.py`
- Test: `backend/tests/test_recruiter_service.py`

**Interfaces:**
- Consumes: `service_client` (`app.db.supabase`), `_run(fn)` (module-local executor wrapper, already defined in this file).
- Produces (consumed by Task 3's `do_ask` and Task 5/6's poller/API):
  - `insert_question(user_id: str, negotiation_id: str, message_id: str, questions: list[str], reason: str, *, question_text: str | None = None, chat_id: str | None = None, applicant_id: str | None = None, vacancy_id: str | None = None, vacancy_title: str | None = None, employer_name: str | None = None) -> None`
  - `list_questions(user_id: str) -> list[dict]`
  - `list_answered_questions(user_id: str) -> list[dict]`
  - `discard_question(user_id: str, question_id: str) -> None`
  - `submit_answers(user_id: str, question_id: str, answers: list[str]) -> None` (raises `ValueError` if the row doesn't exist or `len(answers) != len(row["questions"])`)
  - `mark_question_completed(user_id: str, question_id: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_recruiter_service.py`, after the last test (`test_send_draft_skips_qa_memory_when_unchanged`):

```python
# --- questions ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_question_writes_row():
    from app.services import recruiter
    chain = _fluent([{"id": "q1"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        await recruiter.insert_question(
            "u1", "n1", "m1", ["Когда вам удобно на собеседование?"], "scheduling",
            question_text="Когда сможете на собес?", chat_id="c1", applicant_id="me",
            vacancy_id="v1", vacancy_title="Python Dev", employer_name="Acme",
        )
    args = chain.insert.call_args[0][0]
    assert args["user_id"] == "u1"
    assert args["negotiation_id"] == "n1"
    assert args["message_id"] == "m1"
    assert args["questions"] == ["Когда вам удобно на собеседование?"]
    assert args["reason"] == "scheduling"
    assert args["chat_id"] == "c1" and args["applicant_id"] == "me"
    assert args["vacancy_id"] == "v1" and args["vacancy_title"] == "Python Dev"
    assert args["employer_name"] == "Acme"
    assert args["status"] == "pending"


@pytest.mark.asyncio
async def test_list_pending_questions():
    from app.services import recruiter
    chain = _fluent([{"id": "q1", "status": "pending"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        rows = await recruiter.list_questions("u1")
    assert rows[0]["id"] == "q1"
    chain.eq.assert_any_call("status", "pending")


@pytest.mark.asyncio
async def test_list_answered_questions_filters_status():
    from app.services import recruiter
    chain = _fluent([{"id": "q1", "status": "answered"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        rows = await recruiter.list_answered_questions("u1")
    assert rows[0]["id"] == "q1"
    chain.eq.assert_any_call("status", "answered")


@pytest.mark.asyncio
async def test_discard_question_sets_status():
    from app.services import recruiter
    chain = _fluent([{"id": "q1"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        await recruiter.discard_question("u1", "q1")
    update = chain.update.call_args[0][0]
    assert update["status"] == "discarded"
    assert "resolved_at" in update


@pytest.mark.asyncio
async def test_submit_answers_updates_row():
    from app.services import recruiter
    chain = _fluent(None)
    chain.maybe_single.return_value = chain
    chain.execute.return_value = SimpleNamespace(
        data={"id": "q1", "questions": ["Когда удобно?", "Какой формат?"]}
    )
    with patch.object(recruiter.service_client, "table", return_value=chain):
        await recruiter.submit_answers("u1", "q1", ["Среда 15:00", "Онлайн"])
    update = chain.update.call_args[0][0]
    assert update["answers"] == ["Среда 15:00", "Онлайн"]
    assert update["status"] == "answered"
    assert "answered_at" in update


@pytest.mark.asyncio
async def test_submit_answers_raises_on_missing_row():
    from app.services import recruiter
    chain = _fluent(None)
    chain.maybe_single.return_value = chain
    chain.execute.return_value = SimpleNamespace(data=None)
    with patch.object(recruiter.service_client, "table", return_value=chain):
        with pytest.raises(ValueError):
            await recruiter.submit_answers("u1", "missing", ["a"])


@pytest.mark.asyncio
async def test_submit_answers_raises_on_length_mismatch():
    from app.services import recruiter
    chain = _fluent(None)
    chain.maybe_single.return_value = chain
    chain.execute.return_value = SimpleNamespace(
        data={"id": "q1", "questions": ["Когда удобно?", "Какой формат?"]}
    )
    with patch.object(recruiter.service_client, "table", return_value=chain):
        with pytest.raises(ValueError):
            await recruiter.submit_answers("u1", "q1", ["only one answer"])
    chain.update.assert_not_called()


@pytest.mark.asyncio
async def test_mark_question_completed_sets_status():
    from app.services import recruiter
    chain = _fluent([{"id": "q1"}])
    with patch.object(recruiter.service_client, "table", return_value=chain):
        await recruiter.mark_question_completed("u1", "q1")
    update = chain.update.call_args[0][0]
    assert update["status"] == "completed"
    assert "resolved_at" in update
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_recruiter_service.py -v -k question`
Expected: FAIL with `AttributeError: module 'app.services.recruiter' has no attribute 'insert_question'` (and similarly for the other new functions).

- [ ] **Step 3: Implement the functions**

In `backend/app/services/recruiter.py`, add after `insert_todo` (before the `# --- query + send ---` section):

```python
async def insert_question(
    user_id: str, negotiation_id: str, message_id: str,
    questions: list[str], reason: str,
    question_text: str | None = None,
    chat_id: str | None = None, applicant_id: str | None = None,
    vacancy_id: str | None = None, vacancy_title: str | None = None,
    employer_name: str | None = None,
) -> None:
    def _q():
        return service_client.table("recruiter_questions").insert({
            "user_id": user_id,
            "negotiation_id": negotiation_id,
            "message_id": message_id,
            "questions": questions,
            "reason": reason,
            "question_text": question_text,
            "chat_id": chat_id,
            "applicant_id": applicant_id,
            "vacancy_id": vacancy_id,
            "vacancy_title": vacancy_title,
            "employer_name": employer_name,
            "status": "pending",
        }).execute()
    await _run(_q)
```

Add after `list_drafts` (in the `# --- query + send ---` section):

```python
async def list_questions(user_id: str) -> list[dict]:
    def _q():
        return (
            service_client.table("recruiter_questions")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .execute()
        )
    res = await _run(_q)
    return res.data or []


async def list_answered_questions(user_id: str) -> list[dict]:
    def _q():
        return (
            service_client.table("recruiter_questions")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "answered")
            .order("created_at")
            .execute()
        )
    res = await _run(_q)
    return res.data or []
```

Add after `discard_draft`:

```python
async def discard_question(user_id: str, question_id: str) -> None:
    def _q():
        return (
            service_client.table("recruiter_questions")
            .update({"status": "discarded", "resolved_at": datetime.now(UTC).isoformat()})
            .eq("user_id", user_id).eq("id", question_id)
            .execute()
        )
    await _run(_q)


async def _get_question(user_id: str, question_id: str) -> dict | None:
    def _q():
        return (
            service_client.table("recruiter_questions")
            .select("*")
            .eq("user_id", user_id).eq("id", question_id)
            .maybe_single()
            .execute()
        )
    res = await _run(_q)
    return res.data if res else None


async def submit_answers(user_id: str, question_id: str, answers: list[str]) -> None:
    row = await _get_question(user_id, question_id)
    if not row:
        raise ValueError(f"question {question_id} not found")
    if len(answers) != len(row["questions"]):
        raise ValueError(
            f"expected {len(row['questions'])} answers, got {len(answers)}"
        )

    def _q():
        return (
            service_client.table("recruiter_questions")
            .update({
                "answers": answers,
                "status": "answered",
                "answered_at": datetime.now(UTC).isoformat(),
            })
            .eq("user_id", user_id).eq("id", question_id)
            .execute()
        )
    await _run(_q)


async def mark_question_completed(user_id: str, question_id: str) -> None:
    def _q():
        return (
            service_client.table("recruiter_questions")
            .update({"status": "completed", "resolved_at": datetime.now(UTC).isoformat()})
            .eq("user_id", user_id).eq("id", question_id)
            .execute()
        )
    await _run(_q)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_recruiter_service.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/recruiter.py backend/tests/test_recruiter_service.py
git commit -m "feat: add recruiter_questions persistence functions"
```

---

### Task 3: `ai/recruiter_tools.py` + `ai/prompts.py` + `services/notifications.py` — `escalate_to_human` becomes ask-only

**Files:**
- Modify: `backend/app/ai/recruiter_tools.py`
- Modify: `backend/app/ai/prompts.py`
- Modify: `backend/app/services/notifications.py`
- Test: `backend/tests/test_recruiter_tools.py`
- Test: `backend/tests/test_agent_recruiter.py` (one existing assertion, `build_recruiter_prompt`)

**Interfaces:**
- Consumes: `recruiter.insert_question` (Task 2).
- Produces (consumed by Task 4's `ai/agent.py`):
  - `RecruiterContext` gains `chat_id: str | None = None`, `applicant_id: str | None = None` fields.
  - `do_ask(ctx: RecruiterContext, questions: list[str], reason: str) -> str` — returns `"asked"`.
  - `escalate_to_human` tool signature becomes `(questions: list[str], reason: str)`.
  - `do_escalate(ctx, draft, reason)` is **unchanged** — still called internally by `do_answer`'s free-text branch. Do not remove it.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_recruiter_tools.py`, after `test_do_escalate_inserts_draft_and_notifies`:

```python
@pytest.mark.asyncio
async def test_do_ask_inserts_question_and_notifies():
    from app.ai import recruiter_tools as rt
    ins, notif = _Spy(), _Spy()
    ctx = _ctx()
    with patch.object(rt.recruiter, "insert_question", new=ins), patch.object(rt, "notify", new=notif):
        out = await rt.do_ask(
            ctx, ["Когда вам удобно на собеседование?"], "назначение времени интервью"
        )
    assert ins.calls[0] == (
        "u1", "n9", "m5",
        ["Когда вам удобно на собеседование?"], "назначение времени интервью",
    )
    assert notif.calls[0][1] == "recruiter_question"
    assert out == "asked"
```

Update `test_recruiter_tools_list_has_all_tools` (unchanged — tool names don't change, no edit needed there).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_recruiter_tools.py -v -k do_ask`
Expected: FAIL with `AttributeError: module 'app.ai.recruiter_tools' has no attribute 'do_ask'`.

- [ ] **Step 3: Add `chat_id`/`applicant_id` to `RecruiterContext`**

In `backend/app/ai/recruiter_tools.py`, change:

```python
@dataclass
class RecruiterContext:
    user_id: str
    negotiation_id: str
    message_id: str
    # None for cookies-only connections — tools never call hh directly, they
    # only write drafts/todos for the user to review.
    client: ApiClient | None
    question_text: str | None = None
    quick_reply_labels: list[str] | None = None
    vacancy_id: str | None = None
    vacancy_title: str | None = None
    employer_name: str | None = None
    # Flipped by any successful side effect; the agent checks it after the run to
    # catch "model replied text and called nothing" (see HHAgent._run_recruiter).
    acted: bool = False
```

to:

```python
@dataclass
class RecruiterContext:
    user_id: str
    negotiation_id: str
    message_id: str
    # None for cookies-only connections — tools never call hh directly, they
    # only write drafts/todos for the user to review.
    client: ApiClient | None
    question_text: str | None = None
    quick_reply_labels: list[str] | None = None
    vacancy_id: str | None = None
    vacancy_title: str | None = None
    employer_name: str | None = None
    # chatik identifiers, carried so a pending recruiter_questions row can be
    # resumed later (poll_answered_questions needs them for chatik.chat_messages).
    chat_id: str | None = None
    applicant_id: str | None = None
    # Flipped by any successful side effect; the agent checks it after the run to
    # catch "model replied text and called nothing" (see HHAgent._run_recruiter).
    acted: bool = False
```

- [ ] **Step 4: Add `do_ask` and rewrite the `escalate_to_human` tool**

In `backend/app/ai/recruiter_tools.py`, add after `do_escalate` (keep `do_escalate` exactly as-is — `do_answer` still calls it):

```python
async def do_ask(ctx: RecruiterContext, questions: list[str], reason: str) -> str:
    """Ask the candidate 1+ short direct questions instead of drafting a reply
    ourselves. Answers come back via HHAgent.resume_recruiter_with_answers,
    fed to the agent as a tool response, which then drafts the real reply
    (recruiter_drafts, same review flow as everything else)."""
    await recruiter.insert_question(
        ctx.user_id, ctx.negotiation_id, ctx.message_id,
        [sanitize_ai_text(q) for q in questions], reason,
        question_text=ctx.question_text,
        chat_id=ctx.chat_id, applicant_id=ctx.applicant_id,
        vacancy_id=ctx.vacancy_id, vacancy_title=ctx.vacancy_title,
        employer_name=ctx.employer_name,
    )
    await notify(ctx.user_id, "recruiter_question", {"negotiation_id": ctx.negotiation_id})
    ctx.acted = True
    return "asked"
```

Replace the `escalate_to_human` tool (keep the same position in the file):

```python
@tool(return_direct=True)
async def escalate_to_human(questions: list[str], reason: str, runtime: ToolRuntime[RecruiterContext]) -> str:
    """Задать кандидату 1-3 коротких прямых вопроса вместо того, чтобы гадать
    ответ рекрутёру самому. Вопросы уходят на страницу Задачи; как только
    кандидат ответит, тебя вызовут снова с его ответами (как результат этого
    же вызова), и тогда ты сформулируешь реальный ответ рекрутёру через
    answer_recruiter_question.

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
      Формат: plain text, БЕЗ markdown, БЕЗ длинных тире (—).
      Пример: ["Когда вам удобно на собеседование?"]
      Пример (кнопки): ["Рекрутёр спрашивает про доход 250 000 - подходит?
      Варианты: Да / Рассматриваю выше."]
    - reason (str, required): одна фраза на русском - зачем спрашиваешь
      (контекст для UI). Пример: "назначение времени интервью".

    RETURNS: "asked" при успешном сохранении.

    EDGE CASES:
    - Каждый вопрос автоматически санитизируется (без markdown/тире).
    - Пользователь получит уведомление recruiter_question в UI.
    """
    return await do_ask(runtime.context, questions, reason)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_recruiter_tools.py -v`
Expected: PASS (all tests, including the pre-existing `test_do_answer_drafts_instead_of_posting` and `test_do_escalate_inserts_draft_and_notifies`, which must be untouched and still green — they exercise `do_escalate` via `do_answer`'s free-text path and directly, unrelated to this change).

- [ ] **Step 6: Update the recruiter prompt**

In `backend/app/ai/prompts.py`, change the `escalate_to_human` line inside `RECRUITER_TOOLS_BLOCK`:

```python
- escalate_to_human(draft, reason): всё неоднозначное - назначение собеседования,
  запрос данных не из резюме, кнопки без подходящего варианта, решение для
  человека. draft - короткий ответ, reason - кратко почему.
```

to:

```python
- escalate_to_human(questions, reason): всё неоднозначное - назначение
  собеседования, запрос данных не из резюме, кнопки без подходящего варианта,
  решение для человека. questions - 1-3 коротких прямых вопроса кандидату
  вместо угадывания ответа; reason - кратко почему спрашиваешь.
```

In `backend/tests/test_agent_recruiter.py`, update `test_build_recruiter_prompt_embeds_resume_and_rules` to add one assertion:

```python
def test_build_recruiter_prompt_embeds_resume_and_rules():
    from app.ai.prompts import build_recruiter_prompt
    p = build_recruiter_prompt("Python dev, 3 года опыта")
    assert "Python dev, 3 года опыта" in p
    assert "answer_recruiter_question" in p
    assert "escalate_to_human" in p
    assert "make_todo" in p
    assert "вопрос" in p.lower()
    assert "Отказ" in p or "отказ" in p
```

- [ ] **Step 7: Add the new notification type**

In `backend/app/services/notifications.py`, change:

```python
NotificationType = Literal[
    "captcha",
    "worker_stop",
    "limit_reached",
    "token_dead",
    "account_banned",
    "resume_missing",
    "recruiter_draft",
    "recruiter_todo",
    "form_approval",
    "cover_letter_written",
    "web_session_expired",
]
```

to:

```python
NotificationType = Literal[
    "captcha",
    "worker_stop",
    "limit_reached",
    "token_dead",
    "account_banned",
    "resume_missing",
    "recruiter_draft",
    "recruiter_todo",
    "recruiter_question",
    "form_approval",
    "cover_letter_written",
    "web_session_expired",
]
```

- [ ] **Step 8: Run the full backend recruiter test slice**

Run: `cd backend && python -m pytest tests/test_recruiter_tools.py tests/test_agent_recruiter.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/ai/recruiter_tools.py backend/app/ai/prompts.py backend/app/services/notifications.py backend/tests/test_recruiter_tools.py backend/tests/test_agent_recruiter.py
git commit -m "feat: escalate_to_human asks the candidate questions instead of drafting a reply"
```

---

### Task 4: `ai/agent.py` — thread `chat_id`/`applicant_id`, swap the fallback, add `resume_recruiter_with_answers`

**Files:**
- Modify: `backend/app/ai/agent.py`
- Test: `backend/tests/test_agent_recruiter.py`

**Interfaces:**
- Consumes: `RecruiterContext` (now with `chat_id`/`applicant_id`, Task 3), `do_ask` (Task 3), `recruiter_tools.RECRUITER_TOOLS`.
- Produces (consumed by Task 5's `worker/recruiter_poll.py`):
  - `HHAgent.answer_recruiter(..., chat_id: str | None = None, applicant_id: str | None = None)` — two new optional kwargs.
  - `HHAgent.answer_recruiter_choice(..., chat_id: str | None = None, applicant_id: str | None = None)` — two new optional kwargs.
  - `HHAgent.resume_recruiter_with_answers(negotiation_id: str, message_id: str, history: list[tuple[str, str]], client, *, questions: list[str], answers: list[str], reason: str, question_text: str | None = None, chat_id: str | None = None, applicant_id: str | None = None, vacancy_id: str | None = None, vacancy_title: str | None = None, employer_name: str | None = None) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_agent_recruiter.py`:

```python
@pytest.mark.asyncio
async def test_resume_recruiter_with_answers_skips_when_no_api_key():
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    with patch("app.ai.agent.settings") as s:
        s.OPENAI_API_KEY = ""
        agent._build_recruiter_agent = MagicMock(side_effect=AssertionError("must not build"))
        await agent.resume_recruiter_with_answers(
            "n1", "m1", [], client=MagicMock(),
            questions=["q"], answers=["a"], reason="r",
        )


@pytest.mark.asyncio
async def test_resume_recruiter_with_answers_feeds_tool_response():
    from app.ai.agent import HHAgent
    from langchain_core.messages import AIMessage, ToolMessage
    agent = HHAgent("u1")
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value=_reply("escalated"))
    agent._recruiter_agent = fake_agent
    agent._resume_summary = "ready"
    with patch("app.ai.agent.settings") as s:
        s.OPENAI_API_KEY = "sk-test"
        await agent.resume_recruiter_with_answers(
            "n9", "m5", [("user", "Какая зарплата?")], client=MagicMock(access_token="t"),
            questions=["Когда вам удобно на собеседование?"], answers=["Среда после 15:00"],
            reason="назначение времени интервью", chat_id="c1", applicant_id="me",
        )
    args, kwargs = fake_agent.ainvoke.call_args
    msgs = args[0]["messages"]
    assert msgs[0] == ("user", "Какая зарплата?")
    ai_msg = next(m for m in msgs if isinstance(m, AIMessage))
    assert ai_msg.tool_calls[0]["name"] == "escalate_to_human"
    assert ai_msg.tool_calls[0]["args"]["questions"] == ["Когда вам удобно на собеседование?"]
    tool_msg = next(m for m in msgs if isinstance(m, ToolMessage))
    assert tool_msg.tool_call_id == ai_msg.tool_calls[0]["id"]
    assert "Среда после 15:00" in tool_msg.content
    ctx = kwargs["context"]
    assert ctx.negotiation_id == "n9" and ctx.chat_id == "c1" and ctx.applicant_id == "me"
    assert kwargs["config"]["configurable"]["thread_id"] == "n9"
```

Update the three tests that patch the removed fallback call target. Change:

```python
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
```

to:

```python
@pytest.mark.asyncio
async def test_no_tool_call_escalates_instead_of_dropping():
    """Model answered with plain text and called nothing -> user gets a question."""
    from app.ai.agent import HHAgent
    agent = HHAgent("u1")
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value=_reply("Да, опыт с Claude API есть."))
    agent._recruiter_agent = fake_agent
    agent._resume_summary = "ready"
    with patch("app.ai.agent.settings") as s, \
         patch("app.ai.agent.do_ask", new=AsyncMock()) as esc:
        s.OPENAI_API_KEY = "sk-test"
        await agent.answer_recruiter("n1", "m1", [("user", "Есть опыт с Claude API?")],
                                     client=MagicMock(access_token="t"))
    assert esc.await_count == 1
    assert esc.await_args[0][1] == ["Да, опыт с Claude API есть."]
```

Change (in `test_skip_reply_does_not_escalate`):

```python
    with patch("app.ai.agent.settings") as s, \
         patch("app.ai.agent.do_escalate", new=AsyncMock()) as esc:
```

to:

```python
    with patch("app.ai.agent.settings") as s, \
         patch("app.ai.agent.do_ask", new=AsyncMock()) as esc:
```

Change (in `test_tool_call_suppresses_fallback`):

```python
    with patch("app.ai.agent.settings") as s, \
         patch("app.ai.agent.do_escalate", new=AsyncMock()) as esc:
```

to:

```python
    with patch("app.ai.agent.settings") as s, \
         patch("app.ai.agent.do_ask", new=AsyncMock()) as esc:
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_agent_recruiter.py -v`
Expected: FAIL — `AttributeError: <module 'app.ai.agent'> does not have the attribute 'do_ask'` (patch target doesn't exist yet) and `AttributeError: 'HHAgent' object has no attribute 'resume_recruiter_with_answers'`.

- [ ] **Step 3: Update imports**

In `backend/app/ai/agent.py`, change:

```python
from __future__ import annotations

import logging

from langchain.agents import create_agent
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
from app.ai.recruiter_tools import RECRUITER_TOOLS, RecruiterContext, do_escalate
```

to:

```python
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
```

- [ ] **Step 4: Thread `chat_id`/`applicant_id` through `answer_recruiter` and `answer_recruiter_choice`**

Change:

```python
    async def answer_recruiter(
        self, negotiation_id: str, message_id: str,
        history: list[tuple[str, str]], client,
        question_text: str | None = None,
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
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
        await self._run_recruiter(history, ctx)
```

to:

```python
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
            question_text=question_text, chat_id=chat_id, applicant_id=applicant_id,
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
        await self._run_recruiter(history, ctx)
```

Change:

```python
    async def answer_recruiter_choice(
        self, negotiation_id: str, message_id: str,
        history: list[tuple[str, str]], client, question: str, labels: list[str],
        vacancy_id: str | None = None, vacancy_title: str | None = None,
        employer_name: str | None = None,
    ) -> None:
```

to:

```python
    async def answer_recruiter_choice(
        self, negotiation_id: str, message_id: str,
        history: list[tuple[str, str]], client, question: str, labels: list[str],
        chat_id: str | None = None, applicant_id: str | None = None,
        vacancy_id: str | None = None, vacancy_title: str | None = None,
        employer_name: str | None = None,
    ) -> None:
```

and, further down in the same method, change:

```python
        ctx = RecruiterContext(
            self.user_id, negotiation_id, message_id, client,
            question_text=question, quick_reply_labels=labels,
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
```

to:

```python
        ctx = RecruiterContext(
            self.user_id, negotiation_id, message_id, client,
            question_text=question, quick_reply_labels=labels,
            chat_id=chat_id, applicant_id=applicant_id,
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
```

- [ ] **Step 5: Swap the `_run_recruiter` fallback to `do_ask`**

Change:

```python
        logger.warning("recruiter: chat %s — no tool call, escalating", nid)
        await do_escalate(ctx, text, "агент не выбрал действие, проверьте вручную")
```

to:

```python
        logger.warning("recruiter: chat %s — no tool call, escalating", nid)
        await do_ask(ctx, [text], "агент не выбрал действие, проверьте вручную")
```

- [ ] **Step 6: Add `resume_recruiter_with_answers`**

Add as a new method, right after `answer_recruiter_choice` and before `_run_recruiter`:

```python
    async def resume_recruiter_with_answers(
        self, negotiation_id: str, message_id: str,
        history: list[tuple[str, str]], client, *,
        questions: list[str], answers: list[str], reason: str,
        question_text: str | None = None,
        chat_id: str | None = None, applicant_id: str | None = None,
        vacancy_id: str | None = None, vacancy_title: str | None = None,
        employer_name: str | None = None,
    ) -> None:
        """Re-invoke the recruiter agent after the candidate answered a pending
        escalate_to_human question set. The answers are fed back as a literal
        LangChain tool response (no checkpointer needed — see
        _build_recruiter_agent) so the model sees its own question answered
        and drafts the real reply via answer_recruiter_question."""
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
            question_text=question_text, chat_id=chat_id, applicant_id=applicant_id,
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
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_agent_recruiter.py -v`
Expected: PASS.

- [ ] **Step 8: Run the full backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (integration/e2e tests self-skip without the local stack, per `CLAUDE.md`).

- [ ] **Step 9: Commit**

```bash
git add backend/app/ai/agent.py backend/tests/test_agent_recruiter.py
git commit -m "feat: HHAgent.resume_recruiter_with_answers resumes after the candidate answers"
```

---

### Task 5: `worker/recruiter_poll.py` — pass `chat_id`/`applicant_id`, add `poll_answered_questions`

**Files:**
- Modify: `backend/app/worker/recruiter_poll.py`
- Test: `backend/tests/test_recruiter_poll.py`

**Interfaces:**
- Consumes: `recruiter.list_answered_questions`, `recruiter.mark_question_completed` (Task 2), `agent.resume_recruiter_with_answers` (Task 4).
- Produces: `poll_answered_questions(user_id: str, agent, client, states: dict[str, str]) -> None`, called from `poll_recruiter_chats` once per cycle.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_recruiter_poll.py`, update `_patches` to append two new default patches (append only — existing tests index into this list positionally, e.g. `p[5]`, and must keep working):

```python
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
        patch.object(rp, "_vacancy_meta", new=AsyncMock(return_value=("Python Dev", "Acme"))),
        patch.object(rp.recruiter, "list_answered_questions", new=AsyncMock(return_value=[])),
        patch.object(rp.recruiter, "mark_question_completed", new=AsyncMock()),
    ]
```

Add these assertions to the existing `test_poll_routes_real_recruiter_to_free_text`, right after the existing `vacancy_title`/`employer_name` assertions:

```python
    assert kwargs["chat_id"] == "c1"
    assert kwargs["applicant_id"] == "me"
```

Add these assertions to `test_poll_routes_bot_buttons_to_choice`, right after the existing `vacancy_id`/`vacancy_title` assertion on `ckw`:

```python
    assert ckw["chat_id"] == "c1" and ckw["applicant_id"] == "me"
```

Add new tests at the end of the file:

```python
@pytest.mark.asyncio
async def test_poll_answered_questions_resumes_and_completes():
    from app.worker import recruiter_poll as rp
    row = {
        "id": "q1", "negotiation_id": "n9", "message_id": "m5",
        "questions": ["Когда удобно?"], "answers": ["Среда"], "reason": "scheduling",
        "question_text": "Когда сможете на собес?", "chat_id": "c1", "applicant_id": "me",
        "vacancy_id": "v1", "vacancy_title": "Python Dev", "employer_name": "Acme",
    }
    agent = MagicMock()
    agent.resume_recruiter_with_answers = AsyncMock()
    with patch.object(rp.recruiter, "list_answered_questions", new=AsyncMock(return_value=[row])), \
         patch.object(rp.recruiter, "mark_question_completed", new=AsyncMock()) as complete, \
         patch.object(rp.chatik, "chat_messages", new=AsyncMock(return_value=[])):
        await rp.poll_answered_questions("u1", agent, MagicMock(), states={})
    agent.resume_recruiter_with_answers.assert_awaited_once()
    args, kwargs = agent.resume_recruiter_with_answers.await_args
    assert args[0] == "n9" and args[1] == "m5"
    assert kwargs["questions"] == ["Когда удобно?"] and kwargs["answers"] == ["Среда"]
    assert kwargs["chat_id"] == "c1" and kwargs["applicant_id"] == "me"
    complete.assert_awaited_once_with("u1", "q1")


@pytest.mark.asyncio
async def test_poll_answered_questions_skips_rejected_negotiation():
    from app.worker import recruiter_poll as rp
    row = {
        "id": "q1", "negotiation_id": "n9", "message_id": "m5", "questions": ["Q"],
        "answers": ["A"], "reason": "r", "question_text": None, "chat_id": "c1",
        "applicant_id": "me", "vacancy_id": None, "vacancy_title": None, "employer_name": None,
    }
    agent = MagicMock()
    agent.resume_recruiter_with_answers = AsyncMock()
    with patch.object(rp.recruiter, "list_answered_questions", new=AsyncMock(return_value=[row])), \
         patch.object(rp.recruiter, "mark_question_completed", new=AsyncMock()) as complete:
        await rp.poll_answered_questions(
            "u1", agent, MagicMock(), states={"n9": "discard_after_interview"}
        )
    agent.resume_recruiter_with_answers.assert_not_awaited()
    complete.assert_awaited_once_with("u1", "q1")


@pytest.mark.asyncio
async def test_poll_answered_questions_leaves_row_on_failure():
    from app.worker import recruiter_poll as rp
    row = {
        "id": "q1", "negotiation_id": "n9", "message_id": "m5", "questions": ["Q"],
        "answers": ["A"], "reason": "r", "question_text": None, "chat_id": "c1",
        "applicant_id": "me", "vacancy_id": None, "vacancy_title": None, "employer_name": None,
    }
    agent = MagicMock()
    agent.resume_recruiter_with_answers = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(rp.recruiter, "list_answered_questions", new=AsyncMock(return_value=[row])), \
         patch.object(rp.recruiter, "mark_question_completed", new=AsyncMock()) as complete, \
         patch.object(rp.chatik, "chat_messages", new=AsyncMock(return_value=[])):
        await rp.poll_answered_questions("u1", agent, MagicMock(), states={})  # must not raise
    complete.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_recruiter_poll.py -v`
Expected: FAIL — `AttributeError: module 'app.worker.recruiter_poll' has no attribute 'poll_answered_questions'`, and the two updated existing tests fail on the new `kwargs["chat_id"]`/`ckw["chat_id"]` assertions (`KeyError`).

- [ ] **Step 3: Pass `chat_id`/`applicant_id` in `_process_chat`**

In `backend/app/worker/recruiter_poll.py`, change:

```python
        await agent.answer_recruiter_choice(
            nid, mid, _history(msgs), client, target["text"], target["buttons"],
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
    else:
        # Free text — from a real recruiter OR from the hh bot (it also asks open
        # questions without buttons; skipping those dropped them silently).
        # The agent decides: reply / escalate / todo, or SKIP on a rejection.
        await agent.answer_recruiter(
            nid, mid, _history(msgs), client, question_text=target["text"] or None,
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
```

to:

```python
        await agent.answer_recruiter_choice(
            nid, mid, _history(msgs), client, target["text"], target["buttons"],
            chat_id=ref["chat_id"], applicant_id=ref["applicant_id"],
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
    else:
        # Free text — from a real recruiter OR from the hh bot (it also asks open
        # questions without buttons; skipping those dropped them silently).
        # The agent decides: reply / escalate / todo, or SKIP on a rejection.
        await agent.answer_recruiter(
            nid, mid, _history(msgs), client, question_text=target["text"] or None,
            chat_id=ref["chat_id"], applicant_id=ref["applicant_id"],
            vacancy_id=vacancy_id, vacancy_title=vacancy_title, employer_name=employer_name,
        )
```

- [ ] **Step 4: Add `poll_answered_questions`**

In `backend/app/worker/recruiter_poll.py`, add after `_history` (before `_process_chat`):

```python
async def poll_answered_questions(user_id: str, agent, client, states: dict[str, str]) -> None:
    """Resume the recruiter agent for every question set the candidate has
    answered on the Todo page, feeding the answers back as a tool response.
    Errors are logged and never crash the loop — the row stays 'answered' and
    is retried next poll."""
    for row in await recruiter.list_answered_questions(user_id):
        if states.get(row["negotiation_id"]) in SKIP_STATES:
            await recruiter.mark_question_completed(user_id, row["id"])
            continue
        try:
            msgs = await chatik.chat_messages(user_id, row["chat_id"], row["applicant_id"])
            await agent.resume_recruiter_with_answers(
                row["negotiation_id"], row["message_id"], _history(msgs), client,
                questions=row["questions"], answers=row["answers"], reason=row["reason"],
                question_text=row["question_text"], chat_id=row["chat_id"],
                applicant_id=row["applicant_id"], vacancy_id=row["vacancy_id"],
                vacancy_title=row["vacancy_title"], employer_name=row["employer_name"],
            )
        except Exception:
            logger.warning(
                "recruiter poll: resume failed for question %s", row["id"], exc_info=True,
            )
            continue
        await recruiter.mark_question_completed(user_id, row["id"])
```

- [ ] **Step 5: Wire it into `poll_recruiter_chats`**

Change:

```python
    try:
        states = {} if client is None else await _negotiation_states(client, user_id)
        if client is not None:
            original = client.access_token
        for ref in chats:
```

to:

```python
    try:
        states = {} if client is None else await _negotiation_states(client, user_id)
        if client is not None:
            original = client.access_token
        await poll_answered_questions(user_id, agent, client, states)
        for ref in chats:
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_recruiter_poll.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/worker/recruiter_poll.py backend/tests/test_recruiter_poll.py
git commit -m "feat: poll_answered_questions resumes the recruiter agent on the existing poll cycle"
```

---

### Task 6: `schemas/recruiter.py` + `api/recruiter.py` — questions endpoints

**Files:**
- Modify: `backend/app/schemas/recruiter.py`
- Modify: `backend/app/api/recruiter.py`
- Test: `backend/tests/test_recruiter_api.py`

**Interfaces:**
- Consumes: `recruiter.list_questions`, `recruiter.submit_answers`, `recruiter.discard_question` (Task 2).
- Produces: `GET /api/recruiter/questions`, `POST /api/recruiter/questions/{id}/answer`, `POST /api/recruiter/questions/{id}/discard`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_recruiter_api.py`:

```python
def test_list_questions(client):
    with patch("app.api.recruiter.recruiter.list_questions", new=AsyncMock(return_value=[{"id": "q1"}])):
        r = client.get("/api/recruiter/questions")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "q1"


def test_answer_questions(client):
    with patch("app.api.recruiter.recruiter.submit_answers", new=AsyncMock()) as sub:
        r = client.post("/api/recruiter/questions/q1/answer", json={"answers": ["Среда 15:00"]})
    assert r.status_code == 200
    sub.assert_awaited_once_with("u1", "q1", ["Среда 15:00"])


def test_answer_questions_length_mismatch_returns_400(client):
    with patch(
        "app.api.recruiter.recruiter.submit_answers",
        new=AsyncMock(side_effect=ValueError("expected 2 answers, got 1")),
    ):
        r = client.post("/api/recruiter/questions/q1/answer", json={"answers": ["only one"]})
    assert r.status_code == 400


def test_discard_question(client):
    with patch("app.api.recruiter.recruiter.discard_question", new=AsyncMock()) as disc:
        r = client.post("/api/recruiter/questions/q1/discard")
    assert r.status_code == 200
    disc.assert_awaited_once_with("u1", "q1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_recruiter_api.py -v -k question`
Expected: FAIL with `404 Not Found` (routes don't exist yet).

- [ ] **Step 3: Add the request schema**

In `backend/app/schemas/recruiter.py`, add:

```python
class AnswerQuestionsRequest(BaseModel):
    answers: list[str]
```

- [ ] **Step 4: Add the endpoints**

In `backend/app/api/recruiter.py`, change the import line:

```python
from fastapi import APIRouter, Depends
```

to:

```python
from fastapi import APIRouter, Depends, HTTPException
```

Change:

```python
from app.schemas.recruiter import OkResponse, SendDraftRequest
```

to:

```python
from app.schemas.recruiter import AnswerQuestionsRequest, OkResponse, SendDraftRequest
```

Add at the end of the file:

```python
@router.get("/questions")
async def list_questions(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await recruiter.list_questions(user_id)


@router.post("/questions/{question_id}/answer", response_model=OkResponse)
async def answer_questions(
    question_id: str, body: AnswerQuestionsRequest, user_id: str = Depends(get_current_user)
) -> OkResponse:
    try:
        await recruiter.submit_answers(user_id, question_id, body.answers)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return OkResponse()


@router.post("/questions/{question_id}/discard", response_model=OkResponse)
async def discard_question(question_id: str, user_id: str = Depends(get_current_user)) -> OkResponse:
    await recruiter.discard_question(user_id, question_id)
    return OkResponse()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_recruiter_api.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full backend test suite + lint**

Run: `cd backend && python -m pytest tests/ -v && ruff check app/`
Expected: PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/recruiter.py backend/app/api/recruiter.py backend/tests/test_recruiter_api.py
git commit -m "feat: add /api/recruiter/questions endpoints"
```

---

### Task 7: `hooks/useRecruiter.ts` — `QuestionSet` type + `answerQuestions`/`discardQuestion`

**Files:**
- Modify: `frontend/src/hooks/useRecruiter.ts`

**Interfaces:**
- Consumes: `GET /api/recruiter/questions`, `POST /api/recruiter/questions/{id}/answer`, `POST /api/recruiter/questions/{id}/discard` (Task 6).
- Produces (consumed by Task 9's Todo page):
  - `export type QuestionSet = { id: string; negotiation_id: string; questions: string[]; reason: string | null; question_text: string | null; vacancy_id: string | null; vacancy_title: string | null; employer_name: string | null; created_at: string; }`
  - `useRecruiter()` return value gains `questions: QuestionSet[]`, `answerQuestions(id: string, answers: string[]): Promise<void>`, `discardQuestion(id: string): Promise<void>`.

There is no automated test coverage for this hook in the existing codebase (only pure `lib/` helpers are unit-tested — see `CLAUDE.md`'s Frontend section). Verification for this task is the TypeScript compiler plus the manual check in Task 9.

- [ ] **Step 1: Add the `QuestionSet` type**

In `frontend/src/hooks/useRecruiter.ts`, add after the `Todo` type:

```ts
export type QuestionSet = {
  id: string;
  negotiation_id: string;
  questions: string[];
  reason: string | null;
  question_text: string | null;
  vacancy_id: string | null;
  vacancy_title: string | null;
  employer_name: string | null;
  created_at: string;
};
```

- [ ] **Step 2: Extend `RecruiterData` and the query function**

Change:

```ts
type RecruiterData = { drafts: Draft[]; todos: Todo[] };

export const recruiterQueryKey = ["recruiter"] as const;

const EMPTY: RecruiterData = { drafts: [], todos: [] };

/** Shared between the todo page and the sidebar badge via one query cache entry. */
export function useRecruiter() {
  const qc = useQueryClient();
  const { data, error, isLoading } = useQuery({
    queryKey: recruiterQueryKey,
    queryFn: async (): Promise<RecruiterData> => {
      const [drafts, todos] = await Promise.all([
        apiFetch<Draft[]>("/api/recruiter/drafts"),
        apiFetch<Todo[]>("/api/recruiter/todos"),
      ]);
      return { drafts, todos };
    },
    staleTime: 60_000,
  });
```

to:

```ts
type RecruiterData = { drafts: Draft[]; todos: Todo[]; questions: QuestionSet[] };

export const recruiterQueryKey = ["recruiter"] as const;

const EMPTY: RecruiterData = { drafts: [], todos: [], questions: [] };

/** Shared between the todo page and the sidebar badge via one query cache entry. */
export function useRecruiter() {
  const qc = useQueryClient();
  const { data, error, isLoading } = useQuery({
    queryKey: recruiterQueryKey,
    queryFn: async (): Promise<RecruiterData> => {
      const [drafts, todos, questions] = await Promise.all([
        apiFetch<Draft[]>("/api/recruiter/drafts"),
        apiFetch<Todo[]>("/api/recruiter/todos"),
        apiFetch<QuestionSet[]>("/api/recruiter/questions"),
      ]);
      return { drafts, todos, questions };
    },
    staleTime: 60_000,
  });
```

- [ ] **Step 3: Add `answerQuestions` and `discardQuestion`, extend the return value**

Change:

```ts
  const resolveTodo = useCallback(
    async (id: string, action: "done" | "dismiss") => {
      await apiFetch(`/api/recruiter/todos/${id}/${action}`, { method: "POST" });
      patch((prev) => ({ ...prev, todos: prev.todos.filter((t) => t.id !== id) }));
    },
    [patch],
  );

  return {
    drafts: data?.drafts ?? EMPTY.drafts,
    todos: data?.todos ?? EMPTY.todos,
    loading: isLoading,
    error: error instanceof Error ? error.message : null,
    refresh,
    sendDraft,
    discardDraft,
    resolveTodo,
  };
}
```

to:

```ts
  const resolveTodo = useCallback(
    async (id: string, action: "done" | "dismiss") => {
      await apiFetch(`/api/recruiter/todos/${id}/${action}`, { method: "POST" });
      patch((prev) => ({ ...prev, todos: prev.todos.filter((t) => t.id !== id) }));
    },
    [patch],
  );

  const answerQuestions = useCallback(
    async (id: string, answers: string[]) => {
      await apiFetch(`/api/recruiter/questions/${id}/answer`, {
        method: "POST",
        body: JSON.stringify({ answers }),
      });
      patch((prev) => ({ ...prev, questions: prev.questions.filter((q) => q.id !== id) }));
    },
    [patch],
  );

  const discardQuestion = useCallback(
    async (id: string) => {
      await apiFetch(`/api/recruiter/questions/${id}/discard`, { method: "POST" });
      patch((prev) => ({ ...prev, questions: prev.questions.filter((q) => q.id !== id) }));
    },
    [patch],
  );

  return {
    drafts: data?.drafts ?? EMPTY.drafts,
    todos: data?.todos ?? EMPTY.todos,
    questions: data?.questions ?? EMPTY.questions,
    loading: isLoading,
    error: error instanceof Error ? error.message : null,
    refresh,
    sendDraft,
    discardDraft,
    resolveTodo,
    answerQuestions,
    discardQuestion,
  };
}
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors (this task's edits are additive; Task 9 wires the new return values into the page, so an `unused variable`-style error is not possible here since these are exported/returned, not declared-and-unused).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useRecruiter.ts
git commit -m "feat: useRecruiter fetches and manages recruiter question sets"
```

---

### Task 8: Nav badge — `lib/nav-counts.ts` + `hooks/useNavCounts.ts`

**Files:**
- Modify: `frontend/src/lib/nav-counts.ts`
- Modify: `frontend/src/hooks/useNavCounts.ts`
- Test: `frontend/src/lib/nav-counts.test.ts`

**Interfaces:**
- Consumes: `useRecruiter()`'s `questions` (Task 7).
- Produces: `NavCountsInput` gains `questions: unknown[]`; `computeNavCounts(...).todo` includes `questions.length`.

- [ ] **Step 1: Write the failing test**

In `frontend/src/lib/nav-counts.test.ts`, update every existing `computeNavCounts({...})` call to include `questions: []` (four call sites: "is all zeros for empty input", "sums unread across chats", "adds the three todo sources together", "passes the notification count through"). Example for the first:

```ts
  it("is all zeros for empty input", () => {
    expect(
      computeNavCounts({
        chats: [],
        formDrafts: [],
        recruiterDrafts: [],
        todos: [],
        questions: [],
        unreadNotifications: 0,
      }),
    ).toEqual({ chats: 0, todo: 0, notifications: 0 });
  });
```

Apply the same `questions: []` addition to the other three existing calls (`chats: [{ unread: 2 }, ...]`, `formDrafts: [{}, {}]`, and `unreadNotifications: 12`).

Add a new test:

```ts
  it("includes recruiter questions in the todo count", () => {
    const r = computeNavCounts({
      chats: [],
      formDrafts: [],
      recruiterDrafts: [],
      todos: [],
      questions: [{}, {}],
      unreadNotifications: 0,
    });
    expect(r.todo).toBe(2);
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- nav-counts`
Expected: FAIL — TypeScript error, `questions` does not exist on type `NavCountsInput` (or, if TS errors don't block vitest, the new test fails with `r.todo === 0`).

- [ ] **Step 3: Implement**

In `frontend/src/lib/nav-counts.ts`, change:

```ts
export type NavCountsInput = {
  chats: { unread: number }[];
  formDrafts: unknown[];
  recruiterDrafts: unknown[];
  todos: unknown[];
  unreadNotifications: number;
};

export function computeNavCounts(input: NavCountsInput): NavCounts {
  return {
    chats: input.chats.reduce((sum, c) => sum + (c.unread ?? 0), 0),
    todo: input.formDrafts.length + input.recruiterDrafts.length + input.todos.length,
    notifications: input.unreadNotifications,
  };
}
```

to:

```ts
export type NavCountsInput = {
  chats: { unread: number }[];
  formDrafts: unknown[];
  recruiterDrafts: unknown[];
  todos: unknown[];
  questions: unknown[];
  unreadNotifications: number;
};

export function computeNavCounts(input: NavCountsInput): NavCounts {
  return {
    chats: input.chats.reduce((sum, c) => sum + (c.unread ?? 0), 0),
    todo:
      input.formDrafts.length +
      input.recruiterDrafts.length +
      input.todos.length +
      input.questions.length,
    notifications: input.unreadNotifications,
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- nav-counts`
Expected: PASS.

- [ ] **Step 5: Wire `questions` through `useNavCounts`**

In `frontend/src/hooks/useNavCounts.ts`, change:

```ts
  const { chats } = useChats(false, { enabled: !!hh?.connected });
  const { drafts: formDrafts } = useFormDrafts();
  const { drafts: recruiterDrafts, todos } = useRecruiter();
```

to:

```ts
  const { chats } = useChats(false, { enabled: !!hh?.connected });
  const { drafts: formDrafts } = useFormDrafts();
  const { drafts: recruiterDrafts, todos, questions } = useRecruiter();
```

Change:

```ts
  return useMemo(
    () =>
      computeNavCounts({
        chats: chats ?? [],
        formDrafts,
        recruiterDrafts,
        todos,
        unreadNotifications,
      }),
    [chats, formDrafts, recruiterDrafts, todos, unreadNotifications],
  );
```

to:

```ts
  return useMemo(
    () =>
      computeNavCounts({
        chats: chats ?? [],
        formDrafts,
        recruiterDrafts,
        todos,
        questions,
        unreadNotifications,
      }),
    [chats, formDrafts, recruiterDrafts, todos, questions, unreadNotifications],
  );
```

- [ ] **Step 6: Type-check + run full frontend test suite**

Run: `cd frontend && npx tsc --noEmit && npm test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/nav-counts.ts frontend/src/lib/nav-counts.test.ts frontend/src/hooks/useNavCounts.ts
git commit -m "feat: sidebar Todo badge counts pending recruiter questions"
```

---

### Task 9: Todo page — «Вопросы» tab

**Files:**
- Modify: `frontend/src/app/(app)/todo/page.tsx`

**Interfaces:**
- Consumes: `QuestionSet`, `questions`, `answerQuestions`, `discardQuestion` (Task 7); `VacancyMeta`, `ChatHistory`, `Card`, `Btn`, `EmptyState` (already defined in this file / imported from `@/components/otclick/ui`); `ISpark` icon.

No automated test coverage exists for this page (see Task 7's note). Verification is `tsc --noEmit` plus a manual dev-server check.

- [ ] **Step 1: Import `QuestionSet` and `ISpark`**

Change:

```tsx
import { ICheck, IDoc, IMail } from "@/components/otclick/icons";
import { useRecruiter, type Draft, type Todo } from "@/hooks/useRecruiter";
```

to:

```tsx
import { ICheck, IDoc, IMail, ISpark } from "@/components/otclick/icons";
import { useRecruiter, type Draft, type QuestionSet, type Todo } from "@/hooks/useRecruiter";
```

- [ ] **Step 2: Add the tab to `SECTIONS`**

Change:

```tsx
const SECTIONS = [
  { id: "forms", label: "Анкеты" },
  { id: "drafts", label: "Черновики" },
  { id: "tasks", label: "Задачи" },
] as const;
```

to:

```tsx
const SECTIONS = [
  { id: "forms", label: "Анкеты" },
  { id: "questions", label: "Вопросы" },
  { id: "drafts", label: "Черновики" },
  { id: "tasks", label: "Задачи" },
] as const;
```

- [ ] **Step 3: Add `QuestionCard`**

Add after the `DraftCard` component (before `FormsSection`):

```tsx
function QuestionCard({
  q,
  onAnswer,
  onDiscard,
}: {
  q: QuestionSet;
  onAnswer: (id: string, answers: string[]) => void;
  onDiscard: (id: string) => void;
}) {
  const [answers, setAnswers] = useState<string[]>(q.questions.map(() => ""));
  const allFilled = answers.every((a) => a.trim().length > 0);
  const meta: VacancyRef = {
    vacancy_id: q.vacancy_id,
    vacancy_name: q.vacancy_title,
    employer_name: q.employer_name,
  };
  return (
    <Card style={{ display: "grid", gap: 10, gridTemplateColumns: "minmax(0, 1fr)" }}>
      <VacancyMeta meta={meta} />
      <ChatHistory negotiationId={q.negotiation_id} vacancyId={q.vacancy_id} />
      {q.question_text && (
        <div
          style={{
            background: "var(--bg-deep)",
            borderLeft: "3px solid var(--coral)",
            borderRadius: 10,
            padding: "10px 12px",
            display: "grid",
            gap: 4,
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "var(--muted)",
              fontWeight: 600,
              letterSpacing: 0.4,
              textTransform: "uppercase",
            }}
          >
            Вопрос рекрутёра
          </div>
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.45,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              color: "var(--ink)",
            }}
          >
            {q.question_text}
          </div>
        </div>
      )}
      {q.reason && <div style={{ fontSize: 13, color: "var(--muted)" }}>ИИ спрашивает: {q.reason}</div>}
      <div style={{ display: "grid", gap: 10 }}>
        {q.questions.map((question, i) => (
          <div key={i} style={{ display: "grid", gap: 6, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, overflowWrap: "anywhere" }}>{question}</div>
            <textarea
              value={answers[i]}
              onChange={(e) =>
                setAnswers((prev) => prev.map((a, idx) => (idx === i ? e.target.value : a)))
              }
              rows={2}
              style={{
                width: "100%",
                resize: "vertical",
                padding: 8,
                borderRadius: 10,
                border: "1px solid var(--line)",
                background: "var(--bg-deep)",
                color: "var(--ink)",
                fontSize: 13,
              }}
            />
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Btn kind="primary" size="sm" disabled={!allFilled} onClick={() => onAnswer(q.id, answers)}>
          Отправить ответы
        </Btn>
        <Btn kind="ghost" size="sm" onClick={() => onDiscard(q.id)}>
          Отклонить
        </Btn>
      </div>
    </Card>
  );
}
```

- [ ] **Step 4: Add `QuestionsSection`**

Add after `FormsSection` (before `DraftsSection`):

```tsx
function QuestionsSection({
  questions,
  answerQuestions,
  discardQuestion,
}: {
  questions: QuestionSet[];
  answerQuestions: (id: string, answers: string[]) => void;
  discardQuestion: (id: string) => void;
}) {
  return (
    <div style={{ display: "grid", gap: 12, minWidth: 0, gridTemplateColumns: "minmax(0, 1fr)" }}>
      {questions.length === 0 && (
        <EmptyState
          icon={<ISpark size={22} />}
          title="Вопросов нет"
          description="Когда ИИ не сможет ответить рекрутёру сам, он спросит вас здесь, а затем сформулирует финальный ответ."
        />
      )}
      {questions.map((q) => (
        <QuestionCard key={q.id} q={q} onAnswer={answerQuestions} onDiscard={discardQuestion} />
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Wire it into `RecruiterPage`**

Change:

```tsx
export default function RecruiterPage() {
  const { drafts, todos, loading, error, sendDraft, discardDraft, resolveTodo } = useRecruiter();
  const {
    drafts: formDrafts,
    loading: formLoading,
    error: formError,
    approve: approveForm,
    discard: discardForm,
  } = useFormDrafts();

  const [active, setActive] = useState<SectionId>("forms");

  const counts: Record<SectionId, number> = {
    forms: formDrafts.length,
    drafts: drafts.length,
    tasks: todos.length,
  };
```

to:

```tsx
export default function RecruiterPage() {
  const {
    drafts, todos, questions, loading, error,
    sendDraft, discardDraft, resolveTodo, answerQuestions, discardQuestion,
  } = useRecruiter();
  const {
    drafts: formDrafts,
    loading: formLoading,
    error: formError,
    approve: approveForm,
    discard: discardForm,
  } = useFormDrafts();

  const [active, setActive] = useState<SectionId>("forms");

  const counts: Record<SectionId, number> = {
    forms: formDrafts.length,
    questions: questions.length,
    drafts: drafts.length,
    tasks: todos.length,
  };
```

Change:

```tsx
          {active === "forms" && (
            <FormsSection formDrafts={formDrafts} approveForm={approveForm} discardForm={discardForm} />
          )}
          {active === "drafts" && (
            <DraftsSection drafts={drafts} sendDraft={sendDraft} discardDraft={discardDraft} />
          )}
          {active === "tasks" && <TasksSection todos={todos} resolveTodo={resolveTodo} />}
```

to:

```tsx
          {active === "forms" && (
            <FormsSection formDrafts={formDrafts} approveForm={approveForm} discardForm={discardForm} />
          )}
          {active === "questions" && (
            <QuestionsSection
              questions={questions}
              answerQuestions={answerQuestions}
              discardQuestion={discardQuestion}
            />
          )}
          {active === "drafts" && (
            <DraftsSection drafts={drafts} sendDraft={sendDraft} discardDraft={discardDraft} />
          )}
          {active === "tasks" && <TasksSection todos={todos} resolveTodo={resolveTodo} />}
```

- [ ] **Step 6: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Manual verification in the browser**

Run: `cd frontend && npm run dev`

Open `/todo`, confirm the «Вопросы» tab renders (empty state if there are no pending `recruiter_questions` rows in the local DB — this is expected until Task 1-6's backend flow produces one against a real hh account). Confirm the tab order is Анкеты / Вопросы / Черновики / Задачи and the badge counts update.

- [ ] **Step 8: Commit**

```bash
git add "frontend/src/app/(app)/todo/page.tsx"
git commit -m "feat: add Вопросы tab to the Todo page"
```

---

### Task 10: Notifications wiring — `notifications-drawer.tsx` + `realtime-bridge.tsx`

**Files:**
- Modify: `frontend/src/components/notifications-drawer.tsx`
- Modify: `frontend/src/app/(app)/dashboard/realtime-bridge.tsx`

**Interfaces:**
- Consumes: the `"recruiter_question"` notification type (Task 3).

- [ ] **Step 1: `notifications-drawer.tsx`**

Change:

```tsx
const ICON: Record<string, React.ReactNode> = {
  captcha: <IShield size={14} />,
  limit_reached: <IBolt size={14} />,
  token_dead: <IClose size={14} />,
  account_banned: <IClose size={14} />,
  worker_stop: <ILink size={14} />,
  resume_missing: <ILink size={14} />,
  recruiter_todo: <ICheck size={14} />,
  recruiter_draft: <ICheck size={14} />,
  form_approval: <ICheck size={14} />,
  cover_letter_written: <ICheck size={14} />,
  web_session_expired: <IClose size={14} />,
};

const COLOR: Record<string, string> = {
  captcha: "var(--coral)",
  limit_reached: "var(--yellow)",
  token_dead: "var(--err)",
  account_banned: "var(--err)",
  worker_stop: "var(--muted-2)",
  resume_missing: "var(--muted-2)",
  recruiter_todo: "var(--ok)",
  recruiter_draft: "var(--ok)",
  form_approval: "var(--yellow)",
  cover_letter_written: "var(--ok)",
  web_session_expired: "var(--err)",
};

const TITLE: Record<string, string> = {
  captcha: "Нужна капча",
  limit_reached: "Достигнут дневной лимит",
  worker_stop: "Worker остановлен",
  token_dead: "Токен hh умер",
  account_banned: "Аккаунт hh заблокирован",
  resume_missing: "Резюме недоступно",
  recruiter_todo: "Новая задача от рекрутёра",
  recruiter_draft: "Черновик ответа рекрутёру",
  form_approval: "Анкета ждёт подтверждения",
  cover_letter_written: "ИИ написал сопроводительное",
  web_session_expired: "Сессия hh истекла - переподключите аккаунт",
};
```

to:

```tsx
const ICON: Record<string, React.ReactNode> = {
  captcha: <IShield size={14} />,
  limit_reached: <IBolt size={14} />,
  token_dead: <IClose size={14} />,
  account_banned: <IClose size={14} />,
  worker_stop: <ILink size={14} />,
  resume_missing: <ILink size={14} />,
  recruiter_todo: <ICheck size={14} />,
  recruiter_draft: <ICheck size={14} />,
  recruiter_question: <ICheck size={14} />,
  form_approval: <ICheck size={14} />,
  cover_letter_written: <ICheck size={14} />,
  web_session_expired: <IClose size={14} />,
};

const COLOR: Record<string, string> = {
  captcha: "var(--coral)",
  limit_reached: "var(--yellow)",
  token_dead: "var(--err)",
  account_banned: "var(--err)",
  worker_stop: "var(--muted-2)",
  resume_missing: "var(--muted-2)",
  recruiter_todo: "var(--ok)",
  recruiter_draft: "var(--ok)",
  recruiter_question: "var(--ok)",
  form_approval: "var(--yellow)",
  cover_letter_written: "var(--ok)",
  web_session_expired: "var(--err)",
};

const TITLE: Record<string, string> = {
  captcha: "Нужна капча",
  limit_reached: "Достигнут дневной лимит",
  worker_stop: "Worker остановлен",
  token_dead: "Токен hh умер",
  account_banned: "Аккаунт hh заблокирован",
  resume_missing: "Резюме недоступно",
  recruiter_todo: "Новая задача от рекрутёра",
  recruiter_draft: "Черновик ответа рекрутёру",
  recruiter_question: "Вопрос от ИИ-агента",
  form_approval: "Анкета ждёт подтверждения",
  cover_letter_written: "ИИ написал сопроводительное",
  web_session_expired: "Сессия hh истекла - переподключите аккаунт",
};
```

- [ ] **Step 2: `realtime-bridge.tsx`**

Change:

```tsx
const TYPE_KIND: Record<string, ToastKind> = {
  captcha: "warning",
  limit_reached: "warning",
  worker_stop: "info",
  token_dead: "error",
  account_banned: "error",
  resume_missing: "error",
  recruiter_todo: "info",
  recruiter_draft: "info",
  form_approval: "info",
  cover_letter_written: "success",
  web_session_expired: "error",
};

const TYPE_TITLE: Record<string, string> = {
  captcha: "Нужна капча на hh",
  limit_reached: "Достигнут дневной лимит",
  worker_stop: "Worker остановлен",
  token_dead: "Токен hh умер — переподключи аккаунт",
  account_banned: "Аккаунт hh заблокирован",
  resume_missing: "Резюме недоступно",
  recruiter_todo: "Новая задача от рекрутёра",
  recruiter_draft: "Черновик ответа рекрутёру",
  form_approval: "Анкета ждёт подтверждения",
  cover_letter_written: "ИИ написал сопроводительное",
  web_session_expired: "Сессия hh истекла - переподключите аккаунт",
};
```

to:

```tsx
const TYPE_KIND: Record<string, ToastKind> = {
  captcha: "warning",
  limit_reached: "warning",
  worker_stop: "info",
  token_dead: "error",
  account_banned: "error",
  resume_missing: "error",
  recruiter_todo: "info",
  recruiter_draft: "info",
  recruiter_question: "info",
  form_approval: "info",
  cover_letter_written: "success",
  web_session_expired: "error",
};

const TYPE_TITLE: Record<string, string> = {
  captcha: "Нужна капча на hh",
  limit_reached: "Достигнут дневной лимит",
  worker_stop: "Worker остановлен",
  token_dead: "Токен hh умер — переподключи аккаунт",
  account_banned: "Аккаунт hh заблокирован",
  resume_missing: "Резюме недоступно",
  recruiter_todo: "Новая задача от рекрутёра",
  recruiter_draft: "Черновик ответа рекрутёру",
  recruiter_question: "ИИ-агент спрашивает вас",
  form_approval: "Анкета ждёт подтверждения",
  cover_letter_written: "ИИ написал сопроводительное",
  web_session_expired: "Сессия hh истекла - переподключите аккаунт",
};
```

- [ ] **Step 3: Type-check + run full frontend test suite**

Run: `cd frontend && npx tsc --noEmit && npm test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/notifications-drawer.tsx "frontend/src/app/(app)/dashboard/realtime-bridge.tsx"
git commit -m "feat: wire recruiter_question into the notification drawer and toasts"
```

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-08-20-recruiter-question-flow-design.md` maps to a task — data model (Task 1), tool change (Task 3), resume mechanism (Task 4), poller integration (Task 5), API (Task 6), frontend (Tasks 7-10). The spec's `poll_answered_questions(user_id, agent, client)` signature is corrected here to `poll_answered_questions(user_id, agent, client, states)` per the spec's own later "Rejected/archived negotiations" refinement — both mentions in this plan are consistent with the final 4-arg form.
- **Correction applied:** the spec said `do_escalate` "is removed" — Task 3's Global-Constraints note and Step 3/4 correct this: `do_escalate` is retained because `do_answer` depends on it internally. This was caught by re-reading `recruiter_tools.py` during planning, not by re-deciding the design.
- **Placeholder scan:** no TBD/TODO; every step has literal code, not descriptions.
- **Type consistency check:** `RecruiterContext.chat_id`/`applicant_id` (Task 3) → consumed by `answer_recruiter`/`answer_recruiter_choice`/`resume_recruiter_with_answers` (Task 4) → consumed by `_process_chat`/`poll_answered_questions` (Task 5) — same field names throughout. `insert_question`'s positional-arg order (`user_id, negotiation_id, message_id, questions, reason`, Task 2) matches `do_ask`'s call in Task 3 and the `_Spy`-based test assertion. `QuestionSet` (Task 7) field names match the `recruiter_questions` row shape returned by `list_questions`/`list_answered_questions` (Task 2) and consumed by `QuestionCard`/`QuestionsSection` (Task 9).
