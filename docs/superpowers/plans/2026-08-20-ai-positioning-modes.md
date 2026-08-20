# AI Positioning Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `AI_POSITIONING` config switch (`balanced` | `full`) that swaps a
positioning-tactics block inside every AI prompt that speaks "as the candidate"
(recruiter chat, vacancy-test answers, cover letter, extension autofill/chat),
without ever letting the recruiter-facing chat rewrite resume facts.

**Architecture:** Split each affected prompt in `backend/app/ai/prompts.py`
into named string blocks. One block per prompt (`*_POSITIONING_BLOCKS`) is a
`dict[str, str]` keyed `"balanced"`/`"full"`; every `build_*` function takes an
optional `mode: str | None = None` and resolves it via a shared `_mode()`
helper that falls back to `settings.AI_POSITIONING`. This is the single point
where prompt construction reads config — no other module touches the switch.

**Tech Stack:** Python 3.13, FastAPI, pydantic-settings, pytest.

**Spec:** `docs/spec-ai-positioning.md`

## Global Constraints

- Default mode is `"balanced"`; nothing behaves more aggressively than today unless `AI_POSITIONING=full` is set explicitly.
- The recruiter chat (`build_recruiter_rules` / `build_recruiter_prompt`) NEVER gets permission to rewrite resume facts (experience/age/education/contacts), in either mode — the recruiter can see the resume, so any mismatch is instantly caught.
- `sanitize_ai_text` is not touched.
- `prompts.py` is the only file that imports `settings.AI_POSITIONING`; `config.py` imports nothing from `app`, so this creates no import cycle.
- Every `build_*` function's new `mode` parameter is optional and appended last — existing call sites that don't pass `mode` keep compiling and keep today's behavior.
- Backend tests set required env vars via `os.environ.setdefault(...)` before importing `app.*` (see any `tests/test_*.py` header).

---

### Task 1: `AI_POSITIONING` config setting + docs

**Files:**
- Modify: `backend/app/config.py:1-4` (imports), `backend/app/config.py:58-61` (new field)
- Modify: `.env.example` (repo root, after the `OPENAI_RATE_LIMIT` line)
- Modify: `README.md` (AI features section, ~line 300)
- Modify: `AUDIT.md` (new short section at the end)
- Test: `backend/tests/test_config.py` (new)

**Interfaces:**
- Produces: `settings.AI_POSITIONING: Literal["balanced", "full"]`, default `"balanced"` — every later task's `_mode()` helper reads this.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_config.py`:

```python
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

import pytest
from pydantic import ValidationError


def test_ai_positioning_defaults_to_balanced():
    from app.config import Settings

    assert Settings.model_fields["AI_POSITIONING"].default == "balanced"


def test_ai_positioning_rejects_unknown_value():
    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(AI_POSITIONING="aggressive")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: FAIL — `KeyError: 'AI_POSITIONING'` (field does not exist yet).

- [ ] **Step 3: Add the setting**

In `backend/app/config.py`, change the import block (lines 1-4) from:

```python
from functools import cached_property

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict
```

to:

```python
from functools import cached_property
from typing import Literal

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict
```

Then, right after the `OPENAI_RATE_LIMIT: int = 60` line, add:

```python
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-5.4-nano"
    OPENAI_RATE_LIMIT: int = 60

    # Positioning tactics baked into AI-generated candidate-facing text. See
    # docs/spec-ai-positioning.md. "full" opts into the guide's more
    # aggressive tactics (experience/age/education padding, phantom-offer
    # social proof) — deliberate user choice, not the default.
    AI_POSITIONING: Literal["balanced", "full"] = "balanced"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Document the switch in `.env.example`**

In `.env.example` (repo root), right after the `OPENAI_RATE_LIMIT=60` line, add:

```env

# Positioning tactics baked into AI-generated candidate-facing text (recruiter
# chat, vacancy-test answers, cover letters, extension autofill/chat).
# "balanced" (default) never inflates experience/age/education and only uses
# negotiation framing the candidate could actually stand behind. "full" adds
# the guide's more aggressive tactics (experience/age/education padding,
# phantom-offer social proof) — opt in at your own risk, see AUDIT.md.
AI_POSITIONING=balanced
```

- [ ] **Step 6: Note the switch + its risk in README.md and AUDIT.md**

In `README.md`, in the "AI features" section, right after the fallback table
(the one ending with the "Recruiter agent | Skips every chat" row) and before
the "Any OpenAI-compatible endpoint works" paragraph, add:

```markdown
`AI_POSITIONING` (default `balanced`) controls how far AI-generated text goes
in framing the candidate favorably in recruiter chat, vacancy tests, cover
letters and extension autofill. `full` opts into more aggressive tactics —
see `docs/spec-ai-positioning.md` and `AUDIT.md` before switching.
```

At the end of `AUDIT.md`, after the last "Что осталось" list item, add:

```markdown

## Известные, осознанные риски

- **`AI_POSITIONING=full`** — включает тактики накрутки опыта/возраста/
  образования и социального давления (`docs/CV guide(1).md`) в
  AI-генерируемых текстах (ответы на тесты вакансий, сопроводительные письма,
  автозаполнение расширения). Это осознанный выбор пользователя, не баг:
  дефолт — `balanced`, без выдумки фактов. Рекрутёр-чат не переписывает факты
  резюме ни в одном из режимов. См. `docs/spec-ai-positioning.md`.
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py .env.example README.md AUDIT.md
git commit -m "feat: add AI_POSITIONING config switch"
```

---

### Task 2: Recruiter chat — positioning blocks

**Files:**
- Modify: `backend/app/ai/prompts.py:1-68` (imports + recruiter section)
- Test: `backend/tests/test_prompts.py` (new)

**Interfaces:**
- Consumes: `settings.AI_POSITIONING` (Task 1).
- Produces: `_mode(mode: str | None) -> str`; `build_recruiter_rules(mode: str | None = None) -> str`; `build_recruiter_prompt(resume_summary: str, qa_block: str = "", mode: str | None = None) -> str` (existing signature + trailing `mode`). Later tasks reuse `_mode()`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_prompts.py`:

```python
"""Positioning-mode coverage for app/ai/prompts.py — see docs/spec-ai-positioning.md."""

import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


# --- recruiter chat -----------------------------------------------------------

def test_recruiter_balanced_has_no_social_proof_tactics():
    from app.ai.prompts import build_recruiter_rules

    p = build_recruiter_rules(mode="balanced")
    assert "финальных этапах" not in p
    assert "НИКОГДА не выдумывай опыт" in p


def test_recruiter_full_adds_social_proof_but_still_bans_fact_rewrite():
    from app.ai.prompts import build_recruiter_rules

    p = build_recruiter_rules(mode="full")
    assert "финальных этапах" in p
    assert "НИКОГДА не переписывай факты резюме" in p


def test_recruiter_default_mode_reads_settings(monkeypatch):
    from app.ai.prompts import build_recruiter_rules
    from app.config import settings

    monkeypatch.setattr(settings, "AI_POSITIONING", "full")
    assert build_recruiter_rules() == build_recruiter_rules(mode="full")


def test_build_recruiter_prompt_embeds_resume_and_tools():
    from app.ai.prompts import build_recruiter_prompt

    p = build_recruiter_prompt("Python dev, 3 года опыта", mode="balanced")
    assert "Python dev, 3 года опыта" in p
    assert "answer_recruiter_question" in p
    assert "escalate_to_human" in p
    assert "make_todo" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_recruiter_rules'`.

- [ ] **Step 3: Rewrite the recruiter section of `prompts.py`**

Replace lines 1-68 of `backend/app/ai/prompts.py` (from the module docstring
through the end of `build_recruiter_prompt`) with:

```python
"""System prompts + AI-output sanitizer for HHAgent.

Positioning-dependent prompts are split into named blocks and assembled by
`build_*` functions. `mode` selects which positioning block to use; when
omitted, it falls back to `settings.AI_POSITIONING` ("balanced" | "full").
See docs/spec-ai-positioning.md.
"""

from __future__ import annotations

import re

from app.config import settings

# --- output sanitizer --------------------------------------------------------

# Em/en dashes → hyphen. Strip markdown emphasis chars (`*`, `_`, `**`, `__`).
# Applied to every AI-produced string before it leaves the backend.
_MD_BOLD = re.compile(r"\*\*|__")
_MD_EMPH = re.compile(r"[*_]")
_DASHES = re.compile(r"[—–]")


def sanitize_ai_text(text: str | None) -> str:
    """Remove markdown emphasis and em/en dashes from AI output."""
    if not text:
        return ""
    s = _MD_BOLD.sub("", text)
    s = _MD_EMPH.sub("", s)
    s = _DASHES.sub("-", s)
    return s.strip()


def _mode(mode: str | None) -> str:
    """Resolve an explicit mode, or fall back to settings.AI_POSITIONING."""
    return mode or settings.AI_POSITIONING


# --- recruiter chat ----------------------------------------------------------

RECRUITER_ROLE_BLOCK = """\
Ты - ассистент соискателя, ведёшь переписку с рекрутёрами на hh.ru от его имени.
У тебя есть резюме кандидата (ниже). Отвечай на русском (или языке рекрутёра),
МАКСИМАЛЬНО КРАТКО (1-2 предложения), вежливо. НИКОГДА не выдумывай опыт.

ФОРМАТ ОТВЕТА: только plain text. БЕЗ markdown (*, _, **), БЕЗ длинных тире (—),
БЕЗ эмодзи, БЕЗ приветствий типа "Уважаемые господа".
"""

# Deliberately no experience/age/education padding here even in "full" — the
# recruiter already sees the resume (see FORM_TEXT_FACT_BLOCKS for where that
# padding *does* apply), so any invented fact is instantly caught. This is an
# intentional divergence from the full guide, not an oversight. See
# docs/spec-ai-positioning.md §6.
RECRUITER_POSITIONING_BLOCKS: dict[str, str] = {
    "balanced": """\
ПОЗИЦИОНИРОВАНИЕ В ПЕРЕГОВОРАХ (держись фактов резюме, не выдумывай):
- Деньги: называй жёсткий минимум, который кандидат готов озвучить, а не
  диапазон и не реальный текущий доход - деньги обсуждаются "на берегу".
- Причина ухода/поиска: указывай внешние обстоятельства (релокация,
  сокращение, смена формата работы), а не внутреннюю мотивацию.
- Готовность выйти на работу: "через 2 недели" (отработка), а не "завтра".
- Локация: если уместно, называй крупный город.
- Отвечай по делу, кратко, с цифрами/метриками, где уместно; на вопрос-рассказ
  отвечай по STAR (Ситуация, Задача, Действие, Результат).
- НИКОГДА не выдумывай опыт, возраст, образование, контакты - только то, что
  есть в резюме.
""",
    "full": """\
ПОЗИЦИОНИРОВАНИЕ В ПЕРЕГОВОРАХ (держись фактов резюме, не выдумывай):
- Деньги: называй жёсткий минимум, который кандидат готов озвучить, а не
  диапазон и не реальный текущий доход - деньги обсуждаются "на берегу".
- Причина ухода/поиска: ВСЕГДА внешние обстоятельства (релокация, сокращение,
  закрытие офиса, санкции) - подавай кандидата идеальным сотрудником, которого
  "отпустили" обстоятельства, никогда не внутренняя мотивация.
- Готовность выйти на работу: "через 2 недели" (отработка), а не "завтра".
- Локация: если уместно, называй крупный город.
- Социальное доказательство: если уместно, можно упомянуть, что кандидат
  сейчас на финальных этапах в других местах / рассматривает другие
  предложения - чтобы не выглядеть отчаявшимся.
- Дефицит: если рекрутёр тянет с ответом, можно уточнить, успеет ли компания
  принять решение "до определённой даты", сославшись на другой оффер.
- Отвечай по делу, кратко, с цифрами/метриками, где уместно; на вопрос-рассказ
  отвечай по STAR (Ситуация, Задача, Действие, Результат).
- НИКОГДА не переписывай факты резюме - опыт, возраст, образование, контакты.
  Рекрутёр видит резюме кандидата, любое расхождение мгновенно раскрывается.
""",
}

RECRUITER_TOOLS_BLOCK = """\
Реши, что делать с последним сообщением, и вызови РОВНО ОДИН инструмент (или ни одного):

- answer_recruiter_question(message): вопрос, на который есть ответ. Два случая:
  (1) к сообщению приложены кнопки-варианты (список будет дан) - робот примет
  ТОЛЬКО точный текст варианта, message = ДОСЛОВНЫЙ текст выбранного варианта;
  (2) обычный закрытый вопрос БЕЗ кнопок, ответ ЕСТЬ в резюме (зарплата, опыт,
  навыки, город, удалёнка) - message = прямой короткий ответ.
- escalate_to_human(draft, reason): всё неоднозначное - назначение собеседования,
  запрос данных не из резюме, кнопки без подходящего варианта, решение для
  человека. draft - короткий ответ, reason - кратко почему.
- make_todo(title, detail, link): рекрутёр просит сделать что-то ВНЕ hh -
  гугл-форма, Telegram, звонок. link - URL если есть, иначе пусто. Никогда не
  указывай в link мессенджер MAX - если дали и MAX, и Telegram, бери Telegram;
  если дали только MAX, link=None (сам факт упомяни в detail).
"""

RECRUITER_SKIP_BLOCK = """\
БЕЗ ИНСТРУМЕНТА - РОВНО ДВА СЛУЧАЯ. Если последнее сообщение это:
(1) прямой отказ ("не готовы пригласить", вакансия закрыта/в архиве), или
(2) "резюме интересное / рассмотрим, свяжемся позже" - обещание написать самим,
то ответь ОДНИМ словом: SKIP. Ничего не вызывай.

ВО ВСЕХ ОСТАЛЬНЫХ СЛУЧАЯХ ты ОБЯЗАН вызвать инструмент - вопрос робота hh,
вопрос рекрутёра, просьба, приглашение, непонятное сообщение. Не знаешь ответа
или сомневаешься - escalate_to_human. Молчать нельзя.
"""


def build_recruiter_rules(mode: str | None = None) -> str:
    """Assemble the recruiter-chat system prompt for the given positioning mode."""
    return (
        RECRUITER_ROLE_BLOCK
        + "\n"
        + RECRUITER_POSITIONING_BLOCKS[_mode(mode)]
        + "\n"
        + RECRUITER_TOOLS_BLOCK
        + "\n"
        + RECRUITER_SKIP_BLOCK
    )


def build_recruiter_prompt(
    resume_summary: str, qa_block: str = "", mode: str | None = None
) -> str:
    """Recruiter system prompt grounded in candidate resume + saved Q&A."""
    resume = resume_summary.strip() or "(резюме недоступно)"
    qa = f"\n{qa_block.strip()}\n" if qa_block.strip() else ""
    return f"{build_recruiter_rules(mode)}\n\nРезюме кандидата:\n{resume}\n{qa}"
```

Leave the rest of the file (`COVER_LETTER_SYSTEM_PROMPT` onward) untouched for
now — later tasks handle it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the pre-existing recruiter prompt test**

Run: `cd backend && python -m pytest tests/test_agent_recruiter.py -v`
Expected: PASS — `test_build_recruiter_prompt_embeds_resume_and_rules` still
passes unchanged (the tool/skip block text is byte-identical).

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/prompts.py backend/tests/test_prompts.py
git commit -m "feat: split recruiter chat prompt into positioning-mode blocks"
```

---

### Task 3: Vacancy-test free-text answers — positioning blocks

**Files:**
- Modify: `backend/app/ai/prompts.py` (replace `build_form_text_prompt`)
- Modify: `backend/tests/test_prompts.py` (append tests)

**Interfaces:**
- Consumes: `_mode()` (Task 2).
- Produces: `build_form_text_prompt(question: str, resume_ctx: str, mode: str | None = None) -> str` (existing signature + trailing `mode`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_prompts.py`:

```python
# --- vacancy-test free-text answers -------------------------------------------

def test_form_text_balanced_has_no_experience_padding():
    from app.ai.prompts import build_form_text_prompt

    p = build_form_text_prompt("Сколько лет опыта?", "Junior, 1 год", mode="balanced")
    assert "3-4 года" not in p
    assert "рыночный минимум" not in p


def test_form_text_full_adds_experience_and_salary_padding():
    from app.ai.prompts import build_form_text_prompt

    p = build_form_text_prompt("Сколько лет опыта?", "Junior, 1 год", mode="full")
    assert "3-4 года" in p
    assert "рыночный минимум" in p


def test_form_text_story_instructions_present_in_both_modes():
    from app.ai.prompts import build_form_text_prompt

    for mode in ("balanced", "full"):
        p = build_form_text_prompt("Расскажите о сложном проекте", "ctx", mode=mode)
        assert "STAR" in p
        assert "не сухим канцеляритом" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `TypeError: build_form_text_prompt() got an unexpected keyword argument 'mode'`.

- [ ] **Step 3: Replace `build_form_text_prompt` in `prompts.py`**

Find the existing `build_form_text_prompt` function (the one with the
`"""Free-text vacancy-test answer..."""` docstring) and replace it — and only
it — with:

```python
FORM_TEXT_FACT_BLOCKS: dict[str, str] = {
    "balanced": (
        "1) Фактический вопрос (просит число, дату, город, да/нет, короткий факт: "
        "зарплата, стаж, готовность к переезду/командировкам, гражданство и т.п.):\n"
        "   - Ответь коротко и прямо, одна строка, только факт/число/диапазон.\n"
        "   - Бери значение строго из резюме; нет данных в резюме - не выдумывай.\n"
        "   - Без вступлений, без 'я считаю', без объяснений.\n\n"
    ),
    "full": (
        "1) Фактический вопрос (просит число, дату, город, да/нет, короткий факт: "
        "зарплата, стаж, готовность к переезду/командировкам, гражданство и т.п.):\n"
        "   - Ответь коротко и прямо, одна строка, только факт/число/диапазон.\n"
        "   - Стаж: если резюме даёт хоть какую-то релевантную базу, округляй в "
        "сторону грейда - Middle 3-4 года, Senior 5-6 лет; если подходящего опыта "
        "в резюме нет вообще, отвечай честно по резюме.\n"
        "   - Возраст: если вопрос про возрастной ценз, называй возраст, "
        "попадающий в требуемый диапазон.\n"
        "   - Образование: если вакансия требует высшее образование, указывай, "
        "что оно есть.\n"
        "   - Зарплата: называй рыночный минимум по вакансии/грейду, а не "
        "реальный текущий доход кандидата.\n"
        "   - Город: если вопрос про переезд/локацию, называй крупный город и не "
        "занижай себя.\n"
        "   - Без вступлений, без 'я считаю', без объяснений.\n\n"
    ),
}

FORM_TEXT_STORY_BLOCK = (
    "2) Вопрос-рассказ (просит описать ситуацию, опыт, кейс, достижение, "
    "конфликт, ошибку, пример работы и т.п.):\n"
    "   - Пиши развёрнуто и живо, от первого лица, как реальный человек "
    "рассказывает о своём опыте - не сухим канцеляритом, без штампов вроде "
    "'я стремлюсь' или 'в моей практике'.\n"
    "   - Структурируй по STAR, естественным текстом (без заголовков "
    "'Situation:' и т.п. - просто последовательный рассказ):\n"
    "     * Situation - какая была ситуация/контекст;\n"
    "     * Task - какая задача стояла перед кандидатом;\n"
    "     * Action - что кандидат конкретно сделал;\n"
    "     * Result - к чему это привело, что получилось.\n"
    "   - Опирайся ТОЛЬКО на реальный опыт из резюме - если подходящего кейса в "
    "резюме нет, возьми ближайший релевантный проект/задачу оттуда и опиши её "
    "честно, не выдумывая цифры и факты, которых там нет.\n\n"
)

FORM_TEXT_GENERAL_BLOCK = (
    "ОБЩИЕ ПРАВИЛА:\n"
    "- Plain text. БЕЗ markdown (*, _, **). БЕЗ длинных тире (—), используй обычный дефис.\n"
    "- Пиши на языке вопроса.\n"
    "- Не выдумывай факты, которых нет в резюме.\n"
    "- Если в данных кандидата есть 'Проверенные ответы кандидата' (его прошлые "
    "вопросы и ответы) - это ещё и образец его манеры речи. Пиши новый ответ в "
    "том же стиле: тот же тон (формальный/разговорный), похожая длина фраз, те "
    "же характерные слова и обороты - чтобы все ответы выглядели написанными "
    "одним и тем же человеком.\n\n"
    "Дай только текст ответа, без префикса 'Ответ:' и без пометки типа вопроса."
)


def build_form_text_prompt(question: str, resume_ctx: str, mode: str | None = None) -> str:
    """Free-text vacancy-test answer, grounded in the candidate's resume.

    Two question shapes need opposite treatment:
      - фактический вопрос (зарплата, город, стаж, готовность к переезду) —
        короткий прямой ответ, без истории. Positioning-dependent: "balanced"
        answers only what the resume supports, "full" applies the guide's
        padding tactics (experience/age/education/salary/city).
      - вопрос-рассказ (расскажите о ситуации/опыте/кейсе) — живой человеческий
        ответ по STAR: Situation, Task, Action, Result. Same for both modes.
    """
    return (
        "Ты отвечаешь на вопрос теста вакансии от имени кандидата, на основе резюме.\n"
        f"Данные кандидата:\n{resume_ctx or '(нет данных)'}\n\n"
        f"Вопрос: {question}\n\n"
        "СНАЧАЛА ОПРЕДЕЛИ ТИП ВОПРОСА:\n\n"
        f"{FORM_TEXT_FACT_BLOCKS[_mode(mode)]}"
        f"{FORM_TEXT_STORY_BLOCK}"
        f"{FORM_TEXT_GENERAL_BLOCK}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the existing form_filler suite (call site unchanged, still passes `mode`-less)**

Run: `cd backend && python -m pytest tests/test_form_filler.py -v`
Expected: PASS — `form_filler.py` calls `build_form_text_prompt(question, resume_ctx)` with no `mode`, which still works since `mode` defaults to `None`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/prompts.py backend/tests/test_prompts.py
git commit -m "feat: split vacancy-test free-text prompt into positioning-mode blocks"
```

---

### Task 4: Vacancy-test multiple-choice answers — positioning blocks

**Files:**
- Modify: `backend/app/ai/prompts.py` (replace `build_form_choice_prompt`)
- Modify: `backend/tests/test_prompts.py` (append tests)

**Interfaces:**
- Consumes: `_mode()` (Task 2).
- Produces: `build_form_choice_prompt(question: str, options_block: str, resume_ctx: str, mode: str | None = None) -> str` (existing signature + trailing `mode`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_prompts.py`:

```python
# --- vacancy-test multiple-choice answers -------------------------------------

def test_form_choice_balanced_has_no_dumping_guard():
    from app.ai.prompts import build_form_choice_prompt

    p = build_form_choice_prompt("Опыт?", "1: 1 год\n2: 3 года", "ctx", mode="balanced")
    assert "не занижает кандидата" not in p


def test_form_choice_full_adds_dumping_guard():
    from app.ai.prompts import build_form_choice_prompt

    p = build_form_choice_prompt("Опыт?", "1: 1 год\n2: 3 года", "ctx", mode="full")
    assert "не занижает кандидата" in p
    assert "1: 1 год" in p  # options block still embedded verbatim
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `TypeError: build_form_choice_prompt() got an unexpected keyword argument 'mode'`.

- [ ] **Step 3: Replace `build_form_choice_prompt` in `prompts.py`**

Replace the existing `build_form_choice_prompt` function with:

```python
FORM_CHOICE_POSITIONING_BLOCKS: dict[str, str] = {
    "balanced": "",
    "full": (
        "Если варианты касаются зарплаты, опыта или образования - при прочих "
        "равных выбирай вариант, который не занижает кандидата (не самый "
        "младший/дешёвый из тех, что честно подходят).\n"
    ),
}


def build_form_choice_prompt(
    question: str, options_block: str, resume_ctx: str, mode: str | None = None
) -> str:
    """Pick an option id for a multiple-choice vacancy-test task."""
    extra = FORM_CHOICE_POSITIONING_BLOCKS[_mode(mode)]
    return (
        "Ты отвечаешь на вопрос теста вакансии от имени кандидата, "
        "правдиво и на основе его резюме.\n"
        f"Данные кандидата:\n{resume_ctx or '(нет данных)'}\n\n"
        f"Вопрос: {question}\n"
        f"Варианты:\n{options_block}\n"
        f"{extra}"
        "Выбери ID самого подходящего и правдивого ответа. Пришли ТОЛЬКО ID, ничего больше."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Run the existing form_filler suite**

Run: `cd backend && python -m pytest tests/test_form_filler.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/prompts.py backend/tests/test_prompts.py
git commit -m "feat: split vacancy-test multiple-choice prompt into positioning-mode blocks"
```

---

### Task 5: Cover letter prompt — positioning blocks

**Files:**
- Modify: `backend/app/ai/prompts.py` (replace `COVER_LETTER_SYSTEM_PROMPT` constant with `build_cover_letter_prompt`)
- Modify: `backend/app/services/cover_letter.py:18,145`
- Modify: `backend/tests/test_prompts.py` (append tests)

**Interfaces:**
- Consumes: `_mode()` (Task 2).
- Produces: `build_cover_letter_prompt(mode: str | None = None) -> str`. `COVER_LETTER_SYSTEM_PROMPT` constant is removed — its only consumer is `cover_letter.py`, updated in this task.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_prompts.py`:

```python
# --- cover letter ---------------------------------------------------------------

def test_cover_letter_balanced_has_no_desperate_tone_guard():
    from app.ai.prompts import build_cover_letter_prompt

    p = build_cover_letter_prompt(mode="balanced")
    assert "отчаянного тона" not in p
    assert "Не выдумывай факты" in p


def test_cover_letter_full_adds_salary_and_tone_guidance():
    from app.ai.prompts import build_cover_letter_prompt

    p = build_cover_letter_prompt(mode="full")
    assert "отчаянного тона" in p
    assert "Не выдумывай факты" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_cover_letter_prompt'`.

- [ ] **Step 3: Replace `COVER_LETTER_SYSTEM_PROMPT` in `prompts.py`**

Replace:

```python
COVER_LETTER_SYSTEM_PROMPT = (
    "Ты - кандидат на вакансию. Напиши сопроводительное письмо на русском, "
    "МАКСИМАЛЬНО КРАТКО: 2-3 коротких предложения. Без воды, без приветствий "
    "типа 'Уважаемые господа', без эмодзи. Без markdown (*, _, **), без длинных "
    "тире (—). Свяжи 1-2 факта из резюме с требованиями. Заверши готовностью "
    "обсудить. Не выдумывай факты."
)
```

with:

```python
COVER_LETTER_POSITIONING_BLOCKS: dict[str, str] = {
    "balanced": (
        "Ты - кандидат на вакансию. Напиши сопроводительное письмо на русском, "
        "МАКСИМАЛЬНО КРАТКО: 2-3 коротких предложения. Без воды, без приветствий "
        "типа 'Уважаемые господа', без эмодзи. Без markdown (*, _, **), без длинных "
        "тире (—). Свяжи 1-2 факта из резюме с требованиями. Заверши готовностью "
        "обсудить. Не выдумывай факты."
    ),
    "full": (
        "Ты - кандидат на вакансию. Напиши сопроводительное письмо на русском, "
        "МАКСИМАЛЬНО КРАТКО: 2-3 коротких предложения. Без воды, без приветствий "
        "типа 'Уважаемые господа', без эмодзи. Без markdown (*, _, **), без длинных "
        "тире (—). Свяжи 1-2 факта из резюме с требованиями. Если в данных "
        "кандидата есть зарплатные ожидания или срок готовности выйти на работу - "
        "можно кратко их упомянуть. Пиши уверенно, без отчаянного тона ('очень "
        "хочу', 'дайте шанс'). Заверши готовностью обсудить. Не выдумывай факты "
        "опыта и образования."
    ),
}


def build_cover_letter_prompt(mode: str | None = None) -> str:
    """Cover-letter system prompt for the given positioning mode."""
    return COVER_LETTER_POSITIONING_BLOCKS[_mode(mode)]
```

- [ ] **Step 4: Update `cover_letter.py`'s call site**

In `backend/app/services/cover_letter.py`, change line 18 from:

```python
from app.ai.prompts import COVER_LETTER_SYSTEM_PROMPT, sanitize_ai_text
```

to:

```python
from app.ai.prompts import build_cover_letter_prompt, sanitize_ai_text
```

And change line 145 from:

```python
                SystemMessage(COVER_LETTER_SYSTEM_PROMPT),
```

to:

```python
                SystemMessage(build_cover_letter_prompt()),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_prompts.py tests/test_cover_letter.py -v`
Expected: PASS — all `test_prompts.py` tests (11 total) and all of
`test_cover_letter.py` (it mocks the LLM, doesn't assert exact prompt text).

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/prompts.py backend/app/services/cover_letter.py backend/tests/test_prompts.py
git commit -m "feat: split cover letter prompt into positioning-mode blocks"
```

---

### Task 6: Extension autofill prompt — positioning blocks

**Files:**
- Modify: `backend/app/ai/prompts.py` (replace `FILL_SYSTEM_PROMPT` constant with `build_fill_system_prompt`)
- Modify: `backend/app/ai/agent.py:17-23,135`
- Modify: `backend/tests/test_prompts.py` (append tests)

**Interfaces:**
- Consumes: `_mode()` (Task 2).
- Produces: `build_fill_system_prompt(mode: str | None = None) -> str`. `FILL_SYSTEM_PROMPT` constant is removed — its only consumer is `agent.py`, updated in this task. `build_fill_prompt` (the human-turn builder) is unchanged.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_prompts.py`:

```python
# --- extension autofill -----------------------------------------------------

def test_fill_balanced_forbids_positioning_optional_fields():
    from app.ai.prompts import build_fill_system_prompt

    p = build_fill_system_prompt(mode="balanced")
    assert "позиционировать кандидата выгоднее" not in p
    assert "Ничего не выдумывай" in p


def test_fill_full_allows_positioning_optional_fields_never_contacts():
    from app.ai.prompts import build_fill_system_prompt

    p = build_fill_system_prompt(mode="full")
    assert "позиционировать кандидата выгоднее" in p
    assert "никогда не выдумывай" in p  # contact/personal fields guard stays
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_fill_system_prompt'`.

- [ ] **Step 3: Replace `FILL_SYSTEM_PROMPT` in `prompts.py`**

Replace:

```python
FILL_SYSTEM_PROMPT = """\
Ты заполняешь анкету за кандидата. Тебе дан контекст кандидата, текст страницы \
и список полей формы.

Правила:
- Отвечай ТОЛЬКО тем, что подтверждается контекстом кандидата. Ничего не выдумывай.
- Нет данных для поля - не включай его в ответ. Пустое поле лучше выдуманного.
- Для полей с вариантами (options) значение обязано ТОЧНО совпадать с одним из них.
- source = "profile", если значение взято из фактов кандидата дословно; иначе "ai".
- Тексты пиши на языке формы, без markdown.
"""
```

with:

```python
FILL_POSITIONING_BLOCKS: dict[str, str] = {
    "balanced": """\
Ты заполняешь анкету за кандидата. Тебе дан контекст кандидата, текст страницы \
и список полей формы.

Правила:
- Отвечай ТОЛЬКО тем, что подтверждается контекстом кандидата. Ничего не выдумывай.
- Нет данных для поля - не включай его в ответ. Пустое поле лучше выдуманного.
- Для полей с вариантами (options) значение обязано ТОЧНО совпадать с одним из них.
- source = "profile", если значение взято из фактов кандидата дословно; иначе "ai".
- Тексты пиши на языке формы, без markdown.
""",
    "full": """\
Ты заполняешь анкету за кандидата. Тебе дан контекст кандидата, текст страницы \
и список полей формы.

Правила:
- Контактные данные, адрес и другие персональные поля - ТОЛЬКО из контекста
  кандидата, никогда не выдумывай.
- Для желательных полей (лет опыта, образование, зарплатные ожидания, город)
  можно позиционировать кандидата выгоднее в пределах правдоподобия, опираясь
  на резюме/сохранённые ответы - например округлить стаж в сторону грейда или
  указать рыночный минимум по зарплате вместо текущего дохода.
- Нет данных для поля вообще - не включай его в ответ. Пустое поле лучше
  выдуманного.
- Для полей с вариантами (options) значение обязано ТОЧНО совпадать с одним из них.
- source = "profile", если значение взято из фактов кандидата дословно; для
  позиционированных и любых выведенных значений - source = "ai".
- Тексты пиши на языке формы, без markdown.
""",
}


def build_fill_system_prompt(mode: str | None = None) -> str:
    """System prompt for the extension's third-party form autofill."""
    return FILL_POSITIONING_BLOCKS[_mode(mode)]
```

Leave `build_fill_prompt` (the function right below it, building the human
turn) untouched.

- [ ] **Step 4: Update `agent.py`'s call site**

In `backend/app/ai/agent.py`, change the import block (lines 17-23) from:

```python
from app.ai.prompts import (
    FILL_SYSTEM_PROMPT,
    build_chat_prompt,
    build_fill_prompt,
    build_recruiter_prompt,
    sanitize_ai_text,
)
```

to:

```python
from app.ai.prompts import (
    build_chat_prompt,
    build_fill_prompt,
    build_fill_system_prompt,
    build_recruiter_prompt,
    sanitize_ai_text,
)
```

And change line 135 from:

```python
                    ("system", FILL_SYSTEM_PROMPT),
```

to:

```python
                    ("system", build_fill_system_prompt()),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_prompts.py tests/test_agent_fill.py -v`
Expected: PASS — all `test_prompts.py` tests (13 total) and all of
`test_agent_fill.py` (it mocks the LLM and asserts on returned field values,
not the system prompt string).

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/prompts.py backend/app/ai/agent.py backend/tests/test_prompts.py
git commit -m "feat: split extension autofill prompt into positioning-mode blocks"
```

---

### Task 7: Extension chat prompt — positioning blocks

**Files:**
- Modify: `backend/app/ai/prompts.py` (replace `CHAT_SYSTEM_PROMPT` constant, extend `build_chat_prompt`)
- Modify: `backend/tests/test_prompts.py` (append tests)

**Interfaces:**
- Consumes: `_mode()` (Task 2).
- Produces: `build_chat_system_prompt(mode: str | None = None) -> str`; `build_chat_prompt(context: str, page_text: str | None = None, mode: str | None = None) -> str` (existing signature + trailing `mode`). `CHAT_SYSTEM_PROMPT` constant is removed — its only consumer was `build_chat_prompt` itself, updated in this task; `agent.py`'s call site (`build_chat_prompt(context, page_text)`) needs no change since `mode` defaults to `None`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_prompts.py`:

```python
# --- extension chat ------------------------------------------------------------

def test_chat_balanced_has_no_negotiation_tactics_hint():
    from app.ai.prompts import build_chat_system_prompt

    p = build_chat_system_prompt(mode="balanced")
    assert "тактику позиционирования" not in p


def test_chat_full_offers_negotiation_tactics_hint():
    from app.ai.prompts import build_chat_system_prompt

    p = build_chat_system_prompt(mode="full")
    assert "тактику позиционирования" in p


def test_build_chat_prompt_forwards_mode_and_keeps_context():
    from app.ai.prompts import build_chat_prompt

    p = build_chat_prompt("резюме кандидата", page_text="текст вакансии", mode="full")
    assert "тактику позиционирования" in p
    assert "резюме кандидата" in p
    assert "текст вакансии" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_chat_system_prompt'`.

- [ ] **Step 3: Replace `CHAT_SYSTEM_PROMPT` and `build_chat_prompt` in `prompts.py`**

Replace:

```python
CHAT_SYSTEM_PROMPT = """\
Ты — помощник соискателя внутри браузерного расширения Otclick. Отвечай коротко \
и по делу, на языке вопроса. Опирайся на контекст кандидата ниже; если данных \
не хватает — так и скажи, не выдумывай факты о кандидате. Без markdown.
"""


def build_chat_prompt(context: str, page_text: str | None = None) -> str:
    parts = [CHAT_SYSTEM_PROMPT, f"Контекст кандидата:\n{context or '(пусто)'}"]
    if page_text:
        parts.append(f"Текст открытой страницы:\n{page_text[:8000]}")
    return "\n\n".join(parts)
```

with:

```python
CHAT_POSITIONING_BLOCKS: dict[str, str] = {
    "balanced": """\
Ты — помощник соискателя внутри браузерного расширения Otclick. Отвечай коротко \
и по делу, на языке вопроса. Опирайся на контекст кандидата ниже; если данных \
не хватает — так и скажи, не выдумывай факты о кандидате. Без markdown.
""",
    "full": """\
Ты — помощник соискателя внутри браузерного расширения Otclick. Отвечай коротко \
и по делу, на языке вопроса. Опирайся на контекст кандидата ниже; если данных \
не хватает — так и скажи, не выдумывай факты о кандидате. Если пользователь \
спрашивает, как ответить на вопрос о зарплате, причине ухода или похожий \
переговорный вопрос — можешь коротко подсказать тактику позиционирования \
(например, называть минимум, а не диапазон, или внешнюю причину ухода), не \
выдумывая при этом факты о самом кандидате. Без markdown.
""",
}


def build_chat_system_prompt(mode: str | None = None) -> str:
    """System prompt for the extension's chat assistant tab."""
    return CHAT_POSITIONING_BLOCKS[_mode(mode)]


def build_chat_prompt(
    context: str, page_text: str | None = None, mode: str | None = None
) -> str:
    parts = [build_chat_system_prompt(mode), f"Контекст кандидата:\n{context or '(пусто)'}"]
    if page_text:
        parts.append(f"Текст открытой страницы:\n{page_text[:8000]}")
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_prompts.py tests/test_agent_fill.py -v`
Expected: PASS — all `test_prompts.py` tests (16 total); `test_agent_fill.py`'s
`test_chat_passes_history_and_sanitizes` still passes (it checks `"резюме
кандидата" in seen["msgs"][0][1]` and `"текст вакансии" in seen["msgs"][0][1]`,
both still present in the assembled system message).

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/prompts.py backend/tests/test_prompts.py
git commit -m "feat: split extension chat prompt into positioning-mode blocks"
```

---

### Task 8: Cross-mode guard test + full verification

**Files:**
- Modify: `backend/tests/test_prompts.py` (append tests)

**Interfaces:**
- Consumes: everything from Tasks 2-7.
- Produces: nothing new — this task only adds the acceptance-criteria guard test and runs the full check.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_prompts.py`:

```python
# --- cross-mode guards -----------------------------------------------------------

def test_recruiter_full_never_leaks_form_text_padding_markers():
    """The chat sees the resume — resume-fact tactics from the form-test prompt
    (experience padding) must never leak into the recruiter chat, in any mode."""
    from app.ai.prompts import build_form_text_prompt, build_recruiter_rules

    form_full = build_form_text_prompt("Сколько лет опыта?", "ctx", mode="full")
    recruiter_full = build_recruiter_rules(mode="full")
    assert "3-4 года" in form_full
    assert "3-4 года" not in recruiter_full


def test_sanitize_ai_text_untouched():
    from app.ai.prompts import sanitize_ai_text

    assert sanitize_ai_text("**Привет** — мир_") == "Привет - мир"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_prompts.py -v -k "leaks_form_text or sanitize_ai_text_untouched"`
Expected: FAIL only if a prior task's block text accidentally duplicated the
`"3-4 года"` marker into the recruiter blocks — otherwise this may already
pass at this point since both functions exist from earlier tasks. Confirm
that at least `test_sanitize_ai_text_untouched` collects and passes (it's a
regression guard, not new behavior).

- [ ] **Step 3: No production code change needed**

If Step 2 fails on `test_recruiter_full_never_leaks_form_text_padding_markers`,
remove the accidental `"3-4 года"` (or equivalent experience-padding phrase)
from `RECRUITER_POSITIONING_BLOCKS["full"]` in `backend/app/ai/prompts.py` —
the recruiter block must describe social-proof/scarcity tactics only, never
experience/age/education numbers.

- [ ] **Step 4: Run the full prompts test file**

Run: `cd backend && python -m pytest tests/test_prompts.py -v`
Expected: PASS (18 tests).

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS. `tests/integration` and `tests/e2e` self-skip without a local
stack — that's expected, not a failure.

- [ ] **Step 6: Run ruff**

Run: `cd backend && ruff check .`
Expected: no errors. If `ruff` flags import order in `prompts.py` or
`agent.py`, run `ruff check --fix .` and re-verify with `git diff` that the
fix only reordered imports (no behavior change).

- [ ] **Step 7: Commit**

```bash
git add backend/tests/test_prompts.py
git commit -m "test: guard recruiter chat against resume-fact padding tactics leaking in"
```

---

## Acceptance Criteria Traceability

1. `AI_POSITIONING=balanced` (default) behaves at least as safely as today, with the new negotiation-positioning blocks added → Tasks 1-7 (every `balanced` block).
2. `AI_POSITIONING=full` turns on the guide's tactics in form answers/cover letter; chat gets social positioning without resume-fact edits → Tasks 2-7 `full` blocks + Task 8 cross-mode guard.
3. Prompts split into blocks; switching happens in one place in `prompts.py` (`_mode()`) → Task 2 Step 3.
4. `backend/tests/test_prompts.py` covers the mode difference → Tasks 2-8.
5. `ruff` + `pytest` pass → Task 8 Steps 5-6.
6. `.env.example` documents the switch → Task 1 Step 5.
