# Firefox Form-Autofill Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Расширение для Firefox, которое заполняет анкеты в Google Forms, Yandex Forms и Microsoft Forms контекстом кандидата из Otclick-HH и даёт вкладку чата с ИИ.

**Architecture:** Расширение — форк OtclickUS (`extension/`, gitignored) в новый tracked-каталог `ext/`: `snapshot.ts` собирает поля страницы по всем фреймам, background шлёт их на бэкенд, `FormFiller` проставляет ответы, submit жмёт человек. Бэкенд — новый роутер `/api/extension/*` в `backend/app`, контекст кандидата собирается из уже существующих `form_filler.load_resume` + `_resume_summary` + `qa_memory.prompt_block`, LLM — два новых метода на существующем `HHAgent`. Миграций БД нет.

**Tech Stack:** WXT 0.19 + TypeScript + vitest (расширение), FastAPI + langchain-openai + pytest (бэкенд), Supabase (auth, локальный стек).

## Global Constraints

- Расширение собирается ТОЛЬКО под Firefox: `wxt build -b firefox`. Chrome не поддерживаем.
- Внутри `ext/` использовать `browser` из `wxt/browser`, НЕ `chrome.*`.
- Расширение НИКОГДА не нажимает submit/«Отправить» в форме.
- Ни одно поле не заполняется выдуманным значением: нет уверенного ответа — поле пропускается.
- Пустой `OPENAI_API_KEY` не должен ронять ни один эндпоинт (инвариант проекта).
- Весь код и комментарии — на английском (как в остальном репозитории), пользовательские строки в UI — на русском.
- Все ответы LLM проходят через `app.ai.prompts.sanitize_ai_text`.
- Никаких новых миграций Supabase и новых зависимостей в `backend/pyproject.toml`.
- Каждая задача заканчивается коммитом; тесты пишутся до реализации.

**Формат поля (единый контракт extension ↔ backend, используется во всех задачах):**

```ts
{
  frame_id: number;      // id фрейма из browser.webNavigation.getAllFrames
  ref: string;           // id элемента внутри снапшота
  selector: string;      // CSS-селектор для повторного поиска
  field_type: string;    // text | textarea | select | radio | checkbox | file
  value: string;
  source: "profile" | "ai";
  filename?: string;     // только для field_type === "file"
  required?: boolean;
}
```

---

## Структура файлов

**Бэкенд (создаётся):**

| Файл | Ответственность |
|---|---|
| `backend/app/services/candidate_context.py` | сборка контекста кандидата и словаря вербатим-фактов |
| `backend/app/services/extension_resume.py` | скачивание PDF резюме с hh (байты) |
| `backend/app/api/extension.py` | 5 HTTP-эндпоинтов |
| `backend/tests/test_candidate_context.py` | тесты контекста |
| `backend/tests/test_extension_api.py` | тесты роутера |
| `backend/tests/test_agent_fill.py` | тесты `fill_form_fields` / `chat` |

**Бэкенд (правится):** `backend/app/ai/prompts.py` (два билдера промптов), `backend/app/ai/agent.py` (два метода), `backend/app/api/router.py` (регистрация роутера).

**Расширение (`ext/`, создаётся копированием из `extension/`):**

| Файл | Ответственность |
|---|---|
| `ext/wxt.config.ts` | манифест под Firefox |
| `ext/entrypoints/background.ts` | auth, HTTP к бэкенду, роутинг сообщений |
| `ext/entrypoints/content.ts` | снапшот, применение значений, монтирование панели |
| `ext/entrypoints/otclick-sync.content.ts` | подхват Supabase-сессии с домена Otclick |
| `ext/lib/snapshot.ts` | сбор полей + `FormFiller` (перенос без правок) |
| `ext/lib/marks.ts` | подсветка (перенос без правок) |
| `ext/lib/deterministic-fill.ts` | заполнение фактов и файла без LLM |
| `ext/lib/api.ts` | HTTP-клиент нашего бэкенда (переписывается) |
| `ext/lib/auth.ts` | JWT в `browser.storage.local` + refresh |
| `ext/lib/panel.ts` | новая панель на 3 вкладки (пишется заново вместо `sidebar.ts`) |
| `ext/lib/chat-store.ts` | история чата в `browser.storage.local` |

---

## Task 0: Проверить, что резюме с hh ещё отдаётся

Определяет, идём ли мы по основному пути (резюме с hh) или по фолбэку (ручная загрузка PDF). Ничего не коммитит, кроме заметки.

**Files:**
- Create: `docs/superpowers/plans/2026-08-01-firefox-extension-task0-notes.md`

**Interfaces:**
- Consumes: ничего.
- Produces: подтверждение, что `load_resume(user_id)` возвращает dict и что в нём есть `download.pdf.url`.

- [ ] **Step 1: Поднять стек и получить user_id подключённого пользователя**

```bash
cd /Users/nurma/vscode_projects/AIautoclicker
docker compose up -d
docker exec -it aiautoclicker-db psql -U postgres -d postgres \
  -c "select user_id from hh_credentials limit 1;"
```

Ожидаемо: одна строка с uuid. Если таблица пуста — подключить hh через веб-кабинет (`http://localhost:3000`) и повторить.

- [ ] **Step 2: Запросить полное резюме через существующий код**

```bash
cd backend && python - <<'EOF'
import asyncio, json
from app.services.form_filler import load_resume, _resume_summary
uid = "ПОДСТАВИТЬ_UUID_ИЗ_ШАГА_1"
r = asyncio.run(load_resume(uid))
print("keys:", sorted(r)[:25])
print("download:", json.dumps(r.get("download"), ensure_ascii=False))
print("contact:", json.dumps(r.get("contact"), ensure_ascii=False)[:400])
print("summary head:", _resume_summary(r)[:400])
EOF
```

Ожидаемо: словарь с ключами `title`, `experience`, `contact`, `download`; в `download` — `{"pdf": {"url": "https://api.hh.ru/resumes/.../download/...?type=pdf"}, ...}`.

- [ ] **Step 3: Проверить, что PDF скачивается по токену**

```bash
cd backend && python - <<'EOF'
import asyncio, requests
from app.services.form_filler import load_resume
from app.services.hh_credentials import load_api_client
uid = "ПОДСТАВИТЬ_UUID_ИЗ_ШАГА_1"
r = asyncio.run(load_resume(uid))
url = r["download"]["pdf"]["url"]
c = asyncio.run(load_api_client(uid))
resp = requests.get(url, headers={"Authorization": f"Bearer {c.access_token}"}, timeout=30)
print(resp.status_code, resp.headers.get("Content-Type"), len(resp.content))
EOF
```

Ожидаемо: `200 application/pdf <много байт>`.

- [ ] **Step 4: Записать вывод шагов 2–3 в файл заметок и зафиксировать вердикт**

В файле `docs/superpowers/plans/2026-08-01-firefox-extension-task0-notes.md` — вывод команд и одна из двух строк:

```
ВЕРДИКТ: hh отдаёт резюме и PDF — идём по основному плану.
```
или
```
ВЕРДИКТ: hh закрыл доступ (код ошибки: XXX) — нужен фолбэк с ручной загрузкой PDF.
ОСТАНОВИТЬСЯ и согласовать фолбэк с заказчиком перед Task 1.
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-08-01-firefox-extension-task0-notes.md
git commit -m "docs: task0 spike — hh resume availability check"
```

---

## Task 1: `candidate_context` — контекст кандидата и вербатим-факты

**Files:**
- Create: `backend/app/services/candidate_context.py`
- Test: `backend/tests/test_candidate_context.py`

**Interfaces:**
- Consumes: `app.services.form_filler.load_resume(user_id, resume_row_id=None) -> dict`, `app.services.form_filler._resume_summary(resume) -> str`, `app.services.qa_memory.prompt_block(user_id) -> str`.
- Produces:
  - `facts(resume: dict) -> dict[str, str]` — вербатим-факты, пустые значения выброшены. Ключи: `full_name`, `first_name`, `last_name`, `email`, `phone`, `city`, `citizenship`, `title`.
  - `async build(user_id: str) -> tuple[str, dict[str, str]]` — `(context_text, facts)`. При любой ошибке загрузки резюме возвращает `("", {})`, не поднимает исключение.
  - `known_values(facts: dict[str, str]) -> set[str]` — множество нормализованных (lower+strip) значений фактов.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_candidate_context.py`:

```python
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import AsyncMock, patch

import pytest

RESUME = {
    "title": "Python-разработчик",
    "first_name": "Иван",
    "last_name": "Петров",
    "area": {"name": "Алматы"},
    "citizenship": [{"name": "Казахстан"}],
    "skill_set": ["Python", "FastAPI"],
    "contact": [
        {"type": {"id": "email"}, "value": "ivan@example.com"},
        {"type": {"id": "cell"}, "value": {"formatted": "+7 777 111 22 33"}},
    ],
}


def test_facts_extracts_contacts_and_name():
    from app.services.candidate_context import facts

    f = facts(RESUME)
    assert f["full_name"] == "Иван Петров"
    assert f["first_name"] == "Иван"
    assert f["email"] == "ivan@example.com"
    assert f["phone"] == "+7 777 111 22 33"
    assert f["city"] == "Алматы"
    assert f["title"] == "Python-разработчик"


def test_facts_drops_empty_values():
    from app.services.candidate_context import facts

    f = facts({"title": "", "first_name": "Иван"})
    assert "title" not in f
    assert f["first_name"] == "Иван"


def test_known_values_is_normalized():
    from app.services.candidate_context import facts, known_values

    kv = known_values(facts(RESUME))
    assert "ivan@example.com" in kv
    assert "иван петров" in kv


@pytest.mark.asyncio
async def test_build_joins_summary_and_qa():
    from app.services import candidate_context

    with (
        patch.object(candidate_context, "load_resume", new=AsyncMock(return_value=RESUME)),
        patch.object(candidate_context.qa_memory, "prompt_block", new=AsyncMock(return_value="- В: Опыт?\n  О: 5 лет")),
    ):
        text, f = await candidate_context.build("u1")
    assert "Python-разработчик" in text
    assert "5 лет" in text
    assert f["email"] == "ivan@example.com"


@pytest.mark.asyncio
async def test_build_survives_resume_failure():
    from app.services import candidate_context

    with patch.object(candidate_context, "load_resume", new=AsyncMock(side_effect=RuntimeError("hh down"))):
        text, f = await candidate_context.build("u1")
    assert text == ""
    assert f == {}
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `cd backend && python -m pytest tests/test_candidate_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.candidate_context'`

- [ ] **Step 3: Реализовать сервис**

`backend/app/services/candidate_context.py`:

```python
"""Candidate context for the browser extension's LLM calls.

Reuses what the hh worker already has: `form_filler.load_resume` fetches the
full hh resume, `_resume_summary` renders it, `qa_memory` adds the user's
curated answers. Nothing is stored — the resume is fetched per request and
cached upstream by the API client.
"""

from __future__ import annotations

import logging

from app.services import qa_memory
from app.services.form_filler import _resume_summary, load_resume

logger = logging.getLogger(__name__)


def _contact(resume: dict, type_id: str) -> str:
    for c in resume.get("contact") or []:
        if (c.get("type") or {}).get("id") != type_id:
            continue
        value = c.get("value")
        if isinstance(value, dict):
            return str(value.get("formatted") or "").strip()
        return str(value or "").strip()
    return ""


def _named(value) -> str:
    """hh returns dicts ({'name': ...}) and lists of dicts for area/citizenship."""
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    if isinstance(value, list):
        return ", ".join(x for x in (_named(v) for v in value) if x)
    return str(value or "").strip()


def facts(resume: dict) -> dict[str, str]:
    """Verbatim facts the extension may fill without asking the LLM."""
    first = str(resume.get("first_name") or "").strip()
    last = str(resume.get("last_name") or "").strip()
    out = {
        "full_name": " ".join(x for x in (first, last) if x),
        "first_name": first,
        "last_name": last,
        "email": _contact(resume, "email"),
        "phone": _contact(resume, "cell") or _contact(resume, "home"),
        "city": _named(resume.get("area")),
        "citizenship": _named(resume.get("citizenship")),
        "title": str(resume.get("title") or "").strip(),
    }
    return {k: v for k, v in out.items() if v}


def known_values(f: dict[str, str]) -> set[str]:
    return {v.strip().lower() for v in f.values() if v.strip()}


async def build(user_id: str) -> tuple[str, dict[str, str]]:
    """(context text for the prompt, verbatim facts). ('', {}) on any failure."""
    try:
        resume = await load_resume(user_id)
    except Exception:
        logger.warning("candidate_context: resume load failed for %s", user_id, exc_info=True)
        return "", {}
    parts = [_resume_summary(resume)]
    qa = await qa_memory.prompt_block(user_id)
    if qa:
        parts.append("Ранее подтверждённые ответы кандидата:\n" + qa)
    return "\n\n".join(p for p in parts if p), facts(resume)
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd backend && python -m pytest tests/test_candidate_context.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/candidate_context.py backend/tests/test_candidate_context.py
git commit -m "feat: candidate context builder for the extension"
```

---

## Task 2: `HHAgent.fill_form_fields` — решение значений полей

**Files:**
- Modify: `backend/app/ai/prompts.py` (добавить в конец файла)
- Modify: `backend/app/ai/agent.py` (добавить метод в класс `HHAgent`)
- Test: `backend/tests/test_agent_fill.py`

**Interfaces:**
- Consumes: `self.llm` (`ChatOpenAI | None`) из `HHAgent.__init__`; `app.ai.prompts.sanitize_ai_text`.
- Produces:
  - `prompts.FILL_SYSTEM_PROMPT: str`
  - `prompts.build_fill_prompt(context: str, page_text: str, snapshot: list[dict]) -> str`
  - `HHAgent.fill_form_fields(context: str, page_text: str, snapshot: list[dict], known: set[str] | None = None) -> list[dict]` — список полей формата из Global Constraints (без `frame_id`, его проставляет роутер).
  - `agent.snap_to_option(value: str, options: list[str]) -> str | None` — модульная функция, привязывающая ответ к реальной опции; `None`, если совпадения нет.

Элемент снапшота, который приходит на вход (подмножество `SnapshotEl` из расширения):
`{"ref": "f3", "label": "Ваш город", "field_type": "select", "options": ["Алматы", "Астана"], "required": true}`.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_agent_fill.py`:

```python
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import MagicMock

import pytest

SNAPSHOT = [
    {"ref": "f1", "label": "Ваше имя", "field_type": "text", "required": True},
    {"ref": "f2", "label": "Город", "field_type": "select", "options": ["Алматы", "Астана"]},
]


def test_snap_to_option_exact_and_case_insensitive():
    from app.ai.agent import snap_to_option

    assert snap_to_option("Алматы", ["Алматы", "Астана"]) == "Алматы"
    assert snap_to_option("  астана ", ["Алматы", "Астана"]) == "Астана"


def test_snap_to_option_returns_none_when_no_match():
    from app.ai.agent import snap_to_option

    assert snap_to_option("Караганда", ["Алматы", "Астана"]) is None


@pytest.mark.asyncio
async def test_fill_form_fields_without_llm_returns_empty():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = None
    assert await agent.fill_form_fields("ctx", "page", SNAPSHOT) == []


@pytest.mark.asyncio
async def test_fill_form_fields_maps_refs_and_snaps_options():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = MagicMock()
    agent.llm.with_structured_output.return_value.ainvoke = _async_return(
        {"fields": [
            {"ref": "f1", "value": "Иван Петров", "source": "profile"},
            {"ref": "f2", "value": "астана", "source": "ai"},
        ]}
    )
    out = await agent.fill_form_fields("ctx", "page", SNAPSHOT, known={"иван петров"})
    by_ref = {f["ref"]: f for f in out}
    assert by_ref["f1"]["value"] == "Иван Петров"
    assert by_ref["f1"]["source"] == "profile"
    assert by_ref["f2"]["value"] == "Астана"          # snapped to a real option
    assert by_ref["f1"]["field_type"] == "text"


@pytest.mark.asyncio
async def test_fill_form_fields_demotes_unknown_profile_value():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = MagicMock()
    agent.llm.with_structured_output.return_value.ainvoke = _async_return(
        {"fields": [{"ref": "f1", "value": "Сергей Выдуманный", "source": "profile"}]}
    )
    out = await agent.fill_form_fields("ctx", "page", SNAPSHOT, known={"иван петров"})
    assert out[0]["source"] == "ai"


@pytest.mark.asyncio
async def test_fill_form_fields_drops_empty_and_unsnappable():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = MagicMock()
    agent.llm.with_structured_output.return_value.ainvoke = _async_return(
        {"fields": [
            {"ref": "f1", "value": "   ", "source": "ai"},
            {"ref": "f2", "value": "Караганда", "source": "ai"},
            {"ref": "нет-такого", "value": "x", "source": "ai"},
        ]}
    )
    assert await agent.fill_form_fields("ctx", "page", SNAPSHOT) == []


@pytest.mark.asyncio
async def test_fill_form_fields_survives_llm_error():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = MagicMock()

    async def boom(*a, **kw):
        raise RuntimeError("openai down")

    agent.llm.with_structured_output.return_value.ainvoke = boom
    assert await agent.fill_form_fields("ctx", "page", SNAPSHOT) == []


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `cd backend && python -m pytest tests/test_agent_fill.py -v`
Expected: FAIL — `ImportError: cannot import name 'snap_to_option'`

- [ ] **Step 3: Добавить промпт в `backend/app/ai/prompts.py`**

Дописать в конец файла:

```python
FILL_SYSTEM_PROMPT = """\
Ты заполняешь анкету за кандидата. Тебе дан контекст кандидата, текст страницы \
и список полей формы.

Правила:
- Отвечай ТОЛЬКО тем, что подтверждается контекстом кандидата. Ничего не выдумывай.
- Нет данных для поля — не включай его в ответ. Пустое поле лучше выдуманного.
- Для полей с вариантами (options) значение обязано ТОЧНО совпадать с одним из них.
- source = "profile", если значение взято из фактов кандидата дословно; иначе "ai".
- Тексты пиши на языке формы, без markdown.
"""


def build_fill_prompt(context: str, page_text: str, snapshot: list[dict]) -> str:
    lines = []
    for el in snapshot:
        opts = el.get("options") or []
        opts_s = f" | варианты: {'; '.join(str(o) for o in opts)}" if opts else ""
        req = " | обязательное" if el.get("required") else ""
        lines.append(
            f"- ref={el.get('ref')} | тип: {el.get('field_type')} | "
            f"вопрос: {el.get('label') or ''}{opts_s}{req}"
        )
    return (
        f"Контекст кандидата:\n{context or '(пусто)'}\n\n"
        f"Текст страницы:\n{page_text[:12000]}\n\n"
        f"Поля формы:\n" + "\n".join(lines)
    )
```

- [ ] **Step 4: Добавить метод и `snap_to_option` в `backend/app/ai/agent.py`**

Импорты — дописать к существующему блоку `from app.ai.prompts import ...`:

```python
from app.ai.prompts import FILL_SYSTEM_PROMPT, build_fill_prompt, build_recruiter_prompt, sanitize_ai_text
from pydantic import BaseModel, Field
```

Перед классом `HHAgent` добавить:

```python
class _FillField(BaseModel):
    ref: str
    value: str
    source: str = Field(default="ai")


class _FillPlan(BaseModel):
    fields: list[_FillField] = Field(default_factory=list)


def snap_to_option(value: str, options: list[str]) -> str | None:
    """Map the model's answer onto a real option. None ⇒ no confident match,
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
```

Внутрь класса `HHAgent` (после `filter_relevant_vacancies`):

```python
    async def fill_form_fields(
        self,
        context: str,
        page_text: str,
        snapshot: list[dict],
        known: set[str] | None = None,
    ) -> list[dict]:
        """Decide one value per snapshot field. Empty list when there is no LLM,
        the call fails, or nothing could be answered confidently — the extension
        then leaves those fields to the user."""
        if not self.llm or not snapshot:
            return []
        try:
            plan = await self.llm.with_structured_output(_FillPlan).ainvoke(
                [("system", FILL_SYSTEM_PROMPT),
                 ("human", build_fill_prompt(context, page_text, snapshot))]
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
            out.append({
                "ref": f.ref,
                "selector": el.get("selector") or "",
                "field_type": el.get("field_type") or "text",
                "value": value,
                "source": source,
                "required": bool(el.get("required")),
            })
        return out
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `cd backend && python -m pytest tests/test_agent_fill.py -v`
Expected: 7 passed

- [ ] **Step 6: Прогнать весь бэкенд — ничего не сломано**

Run: `cd backend && python -m pytest tests/ -q`
Expected: все прежние тесты по-прежнему проходят (integration/e2e скипаются без стека)

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai/agent.py backend/app/ai/prompts.py backend/tests/test_agent_fill.py
git commit -m "feat: HHAgent.fill_form_fields for extension autofill"
```

---

## Task 3: `HHAgent.chat` — чат с контекстом кандидата

**Files:**
- Modify: `backend/app/ai/prompts.py`
- Modify: `backend/app/ai/agent.py`
- Test: `backend/tests/test_agent_fill.py` (дописать в тот же файл)

**Interfaces:**
- Consumes: `self.llm`, `prompts.sanitize_ai_text`.
- Produces:
  - `prompts.build_chat_prompt(context: str, page_text: str | None) -> str` — системный промпт.
  - `HHAgent.chat(context: str, messages: list[dict], page_text: str | None = None) -> str` — `messages` это `[{"role": "user"|"assistant", "content": str}, ...]`. Без LLM возвращает `"ИИ недоступен: не настроен OPENAI_API_KEY."`, при ошибке — `"Не удалось получить ответ. Попробуйте ещё раз."`.

- [ ] **Step 1: Написать падающие тесты (дописать в `backend/tests/test_agent_fill.py`)**

```python
@pytest.mark.asyncio
async def test_chat_without_llm_returns_message():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    agent.llm = None
    out = await agent.chat("ctx", [{"role": "user", "content": "привет"}])
    assert "OPENAI_API_KEY" in out


@pytest.mark.asyncio
async def test_chat_passes_history_and_sanitizes():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")
    seen = {}

    async def fake_ainvoke(msgs, *a, **kw):
        seen["msgs"] = msgs
        return type("R", (), {"content": "**Готово** — вот ответ"})()

    agent.llm = MagicMock()
    agent.llm.ainvoke = fake_ainvoke
    out = await agent.chat(
        "резюме кандидата",
        [{"role": "user", "content": "первый"}, {"role": "assistant", "content": "ага"},
         {"role": "user", "content": "второй"}],
        page_text="текст вакансии",
    )
    assert out == "Готово - вот ответ"
    roles = [m[0] for m in seen["msgs"]]
    assert roles == ["system", "human", "ai", "human"]
    assert "резюме кандидата" in seen["msgs"][0][1]
    assert "текст вакансии" in seen["msgs"][0][1]


@pytest.mark.asyncio
async def test_chat_survives_llm_error():
    from app.ai.agent import HHAgent

    agent = HHAgent("u1")

    async def boom(*a, **kw):
        raise RuntimeError("openai down")

    agent.llm = MagicMock()
    agent.llm.ainvoke = boom
    out = await agent.chat("ctx", [{"role": "user", "content": "привет"}])
    assert "Не удалось" in out
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd backend && python -m pytest tests/test_agent_fill.py -k chat -v`
Expected: FAIL — `AttributeError: 'HHAgent' object has no attribute 'chat'`

- [ ] **Step 3: Добавить билдер промпта в `backend/app/ai/prompts.py`**

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

- [ ] **Step 4: Добавить метод в `HHAgent` (после `fill_form_fields`)**

Импорт дополнить: `from app.ai.prompts import CHAT_SYSTEM_PROMPT, FILL_SYSTEM_PROMPT, build_chat_prompt, build_fill_prompt, build_recruiter_prompt, sanitize_ai_text`

```python
    MAX_CHAT_TURNS = 20

    async def chat(
        self, context: str, messages: list[dict], page_text: str | None = None
    ) -> str:
        """Free-form chat grounded in the candidate's resume + Q&A memory.
        History comes from the extension (nothing is stored server-side)."""
        if not self.llm:
            return "ИИ недоступен: не настроен OPENAI_API_KEY."
        msgs: list[tuple[str, str]] = [("system", build_chat_prompt(context, page_text))]
        for m in messages[-self.MAX_CHAT_TURNS:]:
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
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        return sanitize_ai_text(content)
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `cd backend && python -m pytest tests/test_agent_fill.py -v`
Expected: 10 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/agent.py backend/app/ai/prompts.py backend/tests/test_agent_fill.py
git commit -m "feat: HHAgent.chat for the extension chat tab"
```

---

## Task 4: PDF резюме с hh

**Files:**
- Create: `backend/app/services/extension_resume.py`
- Test: `backend/tests/test_extension_resume.py`

**Interfaces:**
- Consumes: `app.services.form_filler.load_resume`, `app.services.hh_credentials.load_api_client`.
- Produces: `async fetch_resume_pdf(user_id: str) -> tuple[bytes, str] | None` — `(содержимое, имя файла)` либо `None`, если резюме/ссылки нет или hh ответил не 200.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_extension_resume.py`:

```python
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

RESUME = {
    "title": "Python-разработчик",
    "download": {"pdf": {"url": "https://api.hh.ru/resumes/x/download/cv.pdf?type=pdf"}},
}


@pytest.mark.asyncio
async def test_fetch_returns_bytes_and_filename():
    from app.services import extension_resume

    resp = MagicMock(status_code=200, content=b"%PDF-1.4 fake")
    client = MagicMock(access_token="tok")
    with (
        patch.object(extension_resume, "load_resume", new=AsyncMock(return_value=RESUME)),
        patch.object(extension_resume, "load_api_client", new=AsyncMock(return_value=client)),
        patch.object(extension_resume.requests, "get", return_value=resp) as get,
    ):
        out = await extension_resume.fetch_resume_pdf("u1")
    assert out == (b"%PDF-1.4 fake", "cv.pdf")
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_fetch_returns_none_without_download_link():
    from app.services import extension_resume

    with patch.object(extension_resume, "load_resume", new=AsyncMock(return_value={"title": "x"})):
        assert await extension_resume.fetch_resume_pdf("u1") is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_http_error():
    from app.services import extension_resume

    resp = MagicMock(status_code=403, content=b"")
    with (
        patch.object(extension_resume, "load_resume", new=AsyncMock(return_value=RESUME)),
        patch.object(extension_resume, "load_api_client", new=AsyncMock(return_value=MagicMock(access_token="t"))),
        patch.object(extension_resume.requests, "get", return_value=resp),
    ):
        assert await extension_resume.fetch_resume_pdf("u1") is None


@pytest.mark.asyncio
async def test_fetch_returns_none_when_resume_load_fails():
    from app.services import extension_resume

    with patch.object(extension_resume, "load_resume", new=AsyncMock(side_effect=RuntimeError("hh down"))):
        assert await extension_resume.fetch_resume_pdf("u1") is None
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd backend && python -m pytest tests/test_extension_resume.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.extension_resume'`

- [ ] **Step 3: Реализовать**

`backend/app/services/extension_resume.py`:

```python
"""Download the user's hh resume as a PDF for the extension's file inputs.

`ApiClient.request` always JSON-decodes the response, so the binary is fetched
with a plain `requests.get` carrying the same bearer token.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import requests

from app.services.form_filler import load_resume
from app.services.hh_credentials import load_api_client

logger = logging.getLogger(__name__)

TIMEOUT_S = 30


async def fetch_resume_pdf(user_id: str) -> tuple[bytes, str] | None:
    """(pdf bytes, filename) or None when hh has no downloadable resume."""
    try:
        resume = await load_resume(user_id)
    except Exception:
        logger.warning("extension resume: load failed for %s", user_id, exc_info=True)
        return None
    url = ((resume.get("download") or {}).get("pdf") or {}).get("url")
    if not url:
        return None
    try:
        client = await load_api_client(user_id)
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: requests.get(
                url,
                headers={"Authorization": f"Bearer {client.access_token}"},
                timeout=TIMEOUT_S,
            ),
        )
    except Exception:
        logger.warning("extension resume: download failed for %s", user_id, exc_info=True)
        return None
    if resp.status_code != 200 or not resp.content:
        logger.info("extension resume: hh returned %s for %s", resp.status_code, user_id)
        return None
    name = urlparse(url).path.rsplit("/", 1)[-1] or "resume.pdf"
    return resp.content, name
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd backend && python -m pytest tests/test_extension_resume.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/extension_resume.py backend/tests/test_extension_resume.py
git commit -m "feat: fetch hh resume PDF for the extension"
```

---

## Task 5: Роутер `/api/extension/*`

**Files:**
- Create: `backend/app/api/extension.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_extension_api.py`

**Interfaces:**
- Consumes: `candidate_context.build`, `candidate_context.known_values`, `HHAgent.fill_form_fields`, `HHAgent.chat`, `extension_resume.fetch_resume_pdf`, `qa_memory.upsert`, `deps.get_current_user`.
- Produces: HTTP-контракт из спеки (5 эндпоинтов, префикс `/api/extension`).

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_extension_api.py`:

```python
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

FACTS = {"full_name": "Иван Петров", "email": "ivan@example.com"}


@pytest.fixture
def client():
    from app.api.deps import get_current_user
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: "u1"
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_context_returns_facts(client):
    with (
        patch("app.api.extension.candidate_context.build", new=AsyncMock(return_value=("ctx", FACTS))),
        patch("app.api.extension.extension_resume.fetch_resume_pdf", new=AsyncMock(return_value=(b"x", "cv.pdf"))),
    ):
        r = client.get("/api/extension/context")
    assert r.status_code == 200
    assert r.json() == {"facts": FACTS, "has_resume_file": True, "resume_filename": "cv.pdf"}


def test_fill_returns_fields_per_frame(client):
    fields = [{"ref": "f1", "selector": "#a", "field_type": "text",
               "value": "Иван Петров", "source": "profile", "required": True}]
    with (
        patch("app.api.extension.candidate_context.build", new=AsyncMock(return_value=("ctx", FACTS))),
        patch("app.api.extension.HHAgent.fill_form_fields", new=AsyncMock(return_value=fields)),
    ):
        r = client.post("/api/extension/fill", json={
            "url": "https://docs.google.com/forms/d/e/x/viewform",
            "page_text": "вакансия",
            "frames": [{"frame_id": 0, "snapshot": [{"ref": "f1", "label": "Имя", "field_type": "text"}]}],
        })
    assert r.status_code == 200
    body = r.json()
    assert body["frames"][0]["frame_id"] == 0
    assert body["frames"][0]["fields"][0]["frame_id"] == 0
    assert body["frames"][0]["fields"][0]["value"] == "Иван Петров"


def test_fill_rejects_oversized_payload(client):
    huge = [{"ref": f"f{i}", "label": "x", "field_type": "text"} for i in range(501)]
    r = client.post("/api/extension/fill", json={
        "url": "https://x", "page_text": "y",
        "frames": [{"frame_id": 0, "snapshot": huge}],
    })
    assert r.status_code == 422


def test_chat_returns_answer(client):
    with (
        patch("app.api.extension.candidate_context.build", new=AsyncMock(return_value=("ctx", FACTS))),
        patch("app.api.extension.HHAgent.chat", new=AsyncMock(return_value="ответ")),
    ):
        r = client.post("/api/extension/chat", json={
            "messages": [{"role": "user", "content": "привет"}],
        })
    assert r.status_code == 200
    assert r.json() == {"answer": "ответ"}


def test_qa_saves_items(client):
    with patch("app.api.extension.qa_memory.upsert", new=AsyncMock()) as up:
        r = client.post("/api/extension/qa", json={
            "items": [{"question": "Опыт?", "answer": "5 лет"}, {"question": " ", "answer": "x"}],
        })
    assert r.status_code == 200
    assert r.json() == {"saved": 1}
    up.assert_awaited_once()


def test_resume_file_streams_pdf(client):
    with patch("app.api.extension.extension_resume.fetch_resume_pdf",
               new=AsyncMock(return_value=(b"%PDF-1.4", "cv.pdf"))):
        r = client.get("/api/extension/resume-file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == b"%PDF-1.4"


def test_resume_file_404_when_missing(client):
    with patch("app.api.extension.extension_resume.fetch_resume_pdf", new=AsyncMock(return_value=None)):
        r = client.get("/api/extension/resume-file")
    assert r.status_code == 404
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd backend && python -m pytest tests/test_extension_api.py -v`
Expected: FAIL — 404 на всех маршрутах (роутера ещё нет)

- [ ] **Step 3: Реализовать роутер**

`backend/app/api/extension.py`:

```python
"""Browser-extension endpoints: form autofill + chat, grounded in hh resume."""

from __future__ import annotations

import logging

from app.ai.agent import HHAgent
from app.api.deps import get_current_user
from app.services import candidate_context, extension_resume, qa_memory
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extension", tags=["extension"])

MAX_FIELDS_PER_FRAME = 500
MAX_FRAMES = 20
MAX_PAGE_TEXT = 40_000


class FrameSnapshot(BaseModel):
    frame_id: int
    snapshot: list[dict] = Field(max_length=MAX_FIELDS_PER_FRAME)


class FillRequest(BaseModel):
    url: str = Field(max_length=2000)
    page_text: str = Field(default="", max_length=MAX_PAGE_TEXT)
    frames: list[FrameSnapshot] = Field(max_length=MAX_FRAMES)


class ChatMessage(BaseModel):
    role: str
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(max_length=60)
    page_text: str | None = Field(default=None, max_length=MAX_PAGE_TEXT)


class QAItem(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=4000)


class QARequest(BaseModel):
    items: list[QAItem] = Field(max_length=100)


@router.get("/context")
async def get_context(user_id: str = Depends(get_current_user)) -> dict:
    """Verbatim facts for deterministic fill + whether a PDF resume exists."""
    _, facts = await candidate_context.build(user_id)
    pdf = await extension_resume.fetch_resume_pdf(user_id)
    return {
        "facts": facts,
        "has_resume_file": pdf is not None,
        "resume_filename": pdf[1] if pdf else None,
    }


@router.post("/fill")
async def fill(body: FillRequest, user_id: str = Depends(get_current_user)) -> dict:
    """Decide values for every frame's fields. Never submits anything."""
    context, facts = await candidate_context.build(user_id)
    known = candidate_context.known_values(facts)
    agent = HHAgent(user_id)
    out = []
    for frame in body.frames:
        fields = await agent.fill_form_fields(
            context, body.page_text, frame.snapshot, known=known
        )
        for f in fields:
            f["frame_id"] = frame.frame_id
        out.append({"frame_id": frame.frame_id, "fields": fields})
    return {"frames": out}


@router.post("/chat")
async def chat(body: ChatRequest, user_id: str = Depends(get_current_user)) -> dict:
    context, _ = await candidate_context.build(user_id)
    answer = await HHAgent(user_id).chat(
        context, [m.model_dump() for m in body.messages], page_text=body.page_text
    )
    return {"answer": answer}


@router.post("/qa")
async def save_qa(body: QARequest, user_id: str = Depends(get_current_user)) -> dict:
    """Persist the answers the user edited, so the next form reuses them."""
    saved = 0
    for item in body.items:
        question, answer = item.question.strip(), item.answer.strip()
        if not question or not answer:
            continue
        try:
            await qa_memory.upsert(user_id, question, answer, source="form")
            saved += 1
        except Exception:
            logger.warning("extension qa: upsert failed for %s", question[:60], exc_info=True)
    return {"saved": saved}


@router.get("/resume-file")
async def resume_file(user_id: str = Depends(get_current_user)) -> Response:
    pdf = await extension_resume.fetch_resume_pdf(user_id)
    if pdf is None:
        raise HTTPException(status_code=404, detail="no resume file")
    content, name = pdf
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )
```

- [ ] **Step 4: Зарегистрировать роутер в `backend/app/api/router.py`**

В блоке импорта добавить `extension` в алфавитном порядке (после `chats`), и ниже добавить строку:

```python
api_router.include_router(extension.router)
```

- [ ] **Step 5: Проверить сигнатуру `qa_memory.upsert`**

Run: `cd backend && sed -n '45,68p' app/services/qa_memory.py`
Ожидаемо: параметры `(user_id, question, answer, source=..., vacancy_id=...)`. Если имена отличаются — привести вызов в `save_qa` к фактической сигнатуре и поправить тест.

- [ ] **Step 6: Запустить тесты — убедиться, что проходят**

Run: `cd backend && python -m pytest tests/test_extension_api.py -v`
Expected: 7 passed

- [ ] **Step 7: Прогнать весь бэкенд и линтер**

Run: `cd backend && python -m pytest tests/ -q && ruff check app tests`
Expected: всё зелёное

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/extension.py backend/app/api/router.py backend/tests/test_extension_api.py
git commit -m "feat: /api/extension endpoints for the browser extension"
```

---

## Task 6: Скелет `ext/` — сборка под Firefox

Здесь расширение ещё ничего не умеет; критерий — оно собирается и грузится в Firefox.

**Files:**
- Create: `ext/` (копия `extension/` с удалением лишнего)
- Modify: `ext/wxt.config.ts`, `ext/package.json`, `.gitignore`

**Interfaces:**
- Produces: рабочий WXT-проект в `ext/`, собираемый `npm run build`; каталоги `ext/lib/`, `ext/entrypoints/` с перенесёнными `snapshot.ts`, `marks.ts`, `deterministic-fill.ts`.

- [ ] **Step 1: Скопировать проект без мусора**

```bash
cd /Users/nurma/vscode_projects/AIautoclicker
rsync -a --exclude node_modules --exclude .wxt --exclude .output \
      --exclude benchmark --exclude benchmark-fill --exclude benchmark-llm \
      --exclude store-assets extension/ ext/
rm -f ext/STORE.md ext/README.md
rm -f ext/lib/linkedin-agent.ts ext/lib/agent-api.ts ext/lib/agent-log.ts \
      ext/lib/agent-search.ts ext/lib/agent-types.ts ext/lib/ats-cache.ts \
      ext/lib/tailor-cache.ts ext/lib/resume-text-cache.ts ext/lib/profile-cache.ts \
      ext/lib/sidebar.ts ext/lib/api.ts ext/lib/detect.ts
rm -rf ext/tests
ls ext/lib
```

Ожидаемо в `ext/lib`: `auth.ts`, `deterministic-fill.ts`, `log.ts`, `marks.ts`, `perf.ts`, `session-sync.ts`, `snapshot.ts`, `theme-sync.ts`.

- [ ] **Step 2: Заменить `ext/wxt.config.ts` целиком**

```ts
import { defineConfig } from "wxt";

// Firefox-only build. Chrome's `key` / `externally_connectable` have no Firefox
// equivalent — the web session is adopted by a content script instead
// (entrypoints/otclick-sync.content.ts).
export default defineConfig({
  manifest: {
    name: "Otclick Autofill",
    description: "Заполняет анкеты вашими данными. Отправляете вы сами.",
    version: "0.1.0",
    browser_specific_settings: {
      gecko: { id: "autofill@otclick.org", strict_min_version: "128.0" },
    },
    permissions: ["storage", "webNavigation"],
    host_permissions: [
      "https://docs.google.com/*",
      "https://forms.gle/*",
      "https://forms.yandex.ru/*",
      "https://forms.yandex.kz/*",
      "https://forms.office.com/*",
      "http://localhost/*",
    ],
    optional_host_permissions: ["<all_urls>"],
    action: {},
    commands: {
      "trigger-autofill": {
        suggested_key: { default: "Alt+Shift+O" },
        description: "Заполнить эту страницу",
      },
    },
    web_accessible_resources: [{ resources: ["fonts/*"], matches: ["<all_urls>"] }],
    icons: { 16: "/icon/16.png", 32: "/icon/32.png", 48: "/icon/48.png", 128: "/icon/128.png" },
  },
});
```

- [ ] **Step 3: Почистить `ext/package.json`**

Заменить блоки `name`/`version`/`scripts`/`devDependencies` на:

```json
{
  "name": "otclick-ext",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "wxt -b firefox",
    "build": "wxt build -b firefox",
    "zip": "wxt zip -b firefox",
    "typecheck": "tsc --noEmit",
    "test": "vitest run"
  },
  "dependencies": {
    "@supabase/supabase-js": "^2.45.0"
  },
  "devDependencies": {
    "@types/jsdom": "^28.0.3",
    "jsdom": "^29.1.1",
    "typescript": "^5.5.0",
    "vitest": "^2.0.0",
    "wxt": "^0.19.0"
  }
}
```

- [ ] **Step 4: Временно упростить точки входа, чтобы проект собрался**

`ext/entrypoints/content.ts` — заменить весь файл на заглушку:

```ts
import { defineContentScript } from "wxt/sandbox";

export default defineContentScript({
  matches: ["<all_urls>"],
  allFrames: true,
  main() {
    console.log("[otclick] content script loaded");
  },
});
```

`ext/entrypoints/background.ts` — заменить весь файл на:

```ts
import { defineBackground } from "wxt/sandbox";

export default defineBackground(() => {
  console.log("[otclick] background loaded");
});
```

`ext/entrypoints/otclick-sync.content.ts` оставить как есть (он маленький и уже читает cookie).

- [ ] **Step 5: Заменить `chrome.` на `browser.` в оставшихся файлах**

```bash
cd ext
grep -rl "chrome\." lib entrypoints | xargs sed -i '' 's/\bchrome\./browser./g'
grep -rn "^import\|browser\." lib/auth.ts | head
```

Затем в каждый файл, где появился `browser.`, добавить первым импортом:

```ts
import { browser } from "wxt/browser";
```

- [ ] **Step 6: Установить зависимости и собрать**

```bash
cd ext && npm install && npm run build
```

Expected: `✔ Built extension` и каталог `.output/firefox-mv3/`. Ошибки типов в удалённых импортах чинить удалением этих импортов.

- [ ] **Step 7: Загрузить в Firefox вручную**

`about:debugging#/runtime/this-firefox` → «Load Temporary Add-on» → `ext/.output/firefox-mv3/manifest.json`.
Expected: расширение появилось в списке, в консоли — `[otclick] background loaded`.

- [ ] **Step 8: Разрешить `ext/` в git**

В `.gitignore` рядом со строкой `extension/` добавить комментарий и убедиться, что `ext/` не игнорируется:

```bash
cd /Users/nurma/vscode_projects/AIautoclicker
printf '\n# ext/ is the tracked Firefox extension; extension/ above is the OtclickUS source copy\n' >> .gitignore
git check-ignore -v ext || echo "ext/ tracked — ok"
```

- [ ] **Step 9: Commit**

```bash
git add ext .gitignore
git commit -m "feat: ext/ skeleton — WXT project targeting Firefox"
```

---

## Task 7: Авторизация — панель знает, кто вошёл

**Files:**
- Modify: `ext/lib/auth.ts`
- Create: `ext/lib/api.ts`
- Modify: `ext/entrypoints/background.ts`
- Modify: `ext/entrypoints/otclick-sync.content.ts`
- Create: `ext/.env.example`
- Test: `ext/tests/auth.test.ts`

**Interfaces:**
- Consumes: `readSupabaseSession(): SessionTokens | null` из `lib/session-sync.ts`.
- Produces:
  - `auth.getValidJwt(): Promise<string | null>` (уже есть, переиспользуется)
  - `auth.persistExternalSession(access_token, refresh_token): Promise<string>` (уже есть)
  - `auth.isExpiringSoon(jwt, skewS?): boolean` (уже есть)
  - Сообщение фону `{type: "AUTH_STATUS"}` → `{loggedIn: boolean, email: string}`
  - Сообщение фону `{type: "OPEN_APP", path: string}` → открывает `VITE_APP_BASE + path`
  - `api.apiFetch<T>(path: string, init?: RequestInit): Promise<T>` — добавляет `Authorization: Bearer <jwt>`, кидает `Error("unauthorized")` при 401.

- [ ] **Step 1: Написать падающий тест на `isExpiringSoon`**

`ext/tests/auth.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { isExpiringSoon } from "../lib/auth";

function jwtWithExp(secondsFromNow: number): string {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + secondsFromNow }));
  return `h.${payload}.s`;
}

describe("isExpiringSoon", () => {
  it("is false for a fresh token", () => {
    expect(isExpiringSoon(jwtWithExp(3600))).toBe(false);
  });

  it("is true inside the skew window", () => {
    expect(isExpiringSoon(jwtWithExp(30))).toBe(true);
  });

  it("is true for garbage", () => {
    expect(isExpiringSoon("not-a-jwt")).toBe(true);
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd ext && npm test`
Expected: FAIL — файла `vitest.config.ts` может не хватать конфигурации окружения; при ошибке `document is not defined` добавить в `ext/vitest.config.ts` `test: { environment: "jsdom" }`.

- [ ] **Step 3: Создать `ext/.env.example` и локальный `.env`**

```bash
cat > ext/.env.example <<'EOF'
VITE_API_BASE=http://localhost:8000
VITE_APP_BASE=http://localhost:3000
VITE_SUPABASE_URL=http://localhost:54321
VITE_SUPABASE_ANON_KEY=
EOF
cp ext/.env.example ext/.env
grep '^SUPABASE_ANON_KEY=' .env | sed 's/^SUPABASE_ANON_KEY=/VITE_SUPABASE_ANON_KEY=/' >> ext/.env
```

Добавить `ext/.env` в `.gitignore`.

- [ ] **Step 4: Поправить `ext/lib/auth.ts`**

Заменить `openWebSignIn` (в нём Chrome-специфичный `?ext=1&extid=`) на:

```ts
export function openWebSignIn(): void {
  // Firefox has no externally_connectable: the user just signs in on the site
  // and otclick-sync.content.ts adopts the cookie session on that tab.
  browser.tabs.create({ url: `${APP_BASE}/auth` });
}
```

Остальное (`getValidJwt`, `persistExternalSession`, `signOut`, `isExpiringSoon`) остаётся как есть.

Важно: `session-sync.ts` вычисляет project ref из хоста `<ref>.supabase.co`; локальный стек живёт на `http://localhost:54321`, где такого ref нет. Заменить `projectRef()` на:

```ts
// Local self-hosted Supabase has no <ref>.supabase.co host — GoTrue there
// writes the cookie as `sb-localhost-auth-token`. Use the first hostname label
// either way.
function projectRef(): string | null {
  try {
    return new URL(SUPABASE_URL).hostname.split(".")[0] || null;
  } catch {
    return null;
  }
}
```

(логика та же — убедиться, что для `localhost` возвращается `"localhost"`, и при ручной проверке в шаге 8 сверить фактическое имя cookie в devtools; если оно другое — подставить фактический префикс.)

- [ ] **Step 5: Создать `ext/lib/api.ts`**

```ts
import { getValidJwt } from "./auth";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const jwt = await getValidJwt();
  if (!jwt) throw new Error("unauthorized");
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
      Authorization: `Bearer ${jwt}`,
    },
  });
  if (resp.status === 401) throw new Error("unauthorized");
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status}`);
  return (await resp.json()) as T;
}

export interface ExtContext {
  facts: Record<string, string>;
  has_resume_file: boolean;
  resume_filename: string | null;
}

export const fetchContext = () => apiFetch<ExtContext>("/api/extension/context");
```

- [ ] **Step 6: Реализовать `ext/entrypoints/background.ts`**

```ts
import { defineBackground } from "wxt/sandbox";
import { browser } from "wxt/browser";
import { getValidJwt, openWebSignIn, persistExternalSession, signOut } from "../lib/auth";

const APP_BASE = import.meta.env.VITE_APP_BASE ?? "http://localhost:3000";

export default defineBackground(() => {
  browser.runtime.onMessage.addListener((msg: any, _sender, sendResponse) => {
    void handle(msg).then(sendResponse).catch((e) => sendResponse({ error: String(e) }));
    return true; // async response
  });

  browser.action.onClicked.addListener(async (tab) => {
    if (tab.id != null) await browser.tabs.sendMessage(tab.id, { type: "TOGGLE_PANEL" });
  });
});

async function handle(msg: any): Promise<unknown> {
  switch (msg?.type) {
    case "AUTH_STATUS": {
      const jwt = await getValidJwt();
      const { email } = await browser.storage.local.get("email");
      return { loggedIn: Boolean(jwt), email: email ?? "" };
    }
    case "SIGN_IN":
      openWebSignIn();
      return { ok: true };
    case "SIGN_OUT":
      await signOut();
      return { ok: true };
    case "OPEN_APP":
      await browser.tabs.create({ url: `${APP_BASE}${msg.path ?? ""}` });
      return { ok: true };
    case "ADOPT_SESSION": {
      const email = await persistExternalSession(msg.access_token, msg.refresh_token);
      return { ok: true, email };
    }
    default:
      return { error: `unknown message: ${msg?.type}` };
  }
}
```

- [ ] **Step 7: Привести `ext/entrypoints/otclick-sync.content.ts` к новому сообщению**

Файл должен матчиться на домен приложения и слать фону сессию:

```ts
import { defineContentScript } from "wxt/sandbox";
import { browser } from "wxt/browser";
import { readSupabaseSession } from "../lib/session-sync";

export default defineContentScript({
  matches: ["http://localhost/*", "https://otclick.org/*"],
  main() {
    const push = () => {
      const s = readSupabaseSession();
      if (!s) return;
      void browser.runtime.sendMessage({
        type: "ADOPT_SESSION",
        access_token: s.access_token,
        refresh_token: s.refresh_token,
      });
    };
    push();
    // The session cookie appears a beat after a fresh login redirect.
    setTimeout(push, 2000);
  },
});
```

- [ ] **Step 8: Ручная проверка входа**

```bash
cd ext && npm run build
```

Перезагрузить временное дополнение в Firefox, открыть `http://localhost:3000`, войти, затем в консоли фона (`about:debugging` → Inspect):

```js
await browser.runtime.sendMessage({ type: "AUTH_STATUS" })
```

Expected: `{loggedIn: true, email: "..."}`. Если `loggedIn: false` — посмотреть в devtools вкладки имя cookie (`document.cookie`) и поправить префикс в `session-sync.ts`.

- [ ] **Step 9: Запустить тесты**

Run: `cd ext && npm test && npm run typecheck`
Expected: 3 passed, типы чистые

- [ ] **Step 10: Commit**

```bash
git add ext .gitignore
git commit -m "feat(ext): supabase session adoption + authed api client"
```

---

## Task 8: Заполнение формы — снапшот, запрос, применение

**Files:**
- Modify: `ext/lib/api.ts`
- Modify: `ext/entrypoints/background.ts`
- Modify: `ext/entrypoints/content.ts`
- Test: `ext/tests/fill-flow.test.ts`

**Interfaces:**
- Consumes: `snapshot()` / `snapshotWithOptions()` / `applyFill(fields)` из `lib/snapshot.ts`, `marks.ts`, `apiFetch`.
- Produces:
  - `api.callFill(payload): Promise<{frames: {frame_id: number; fields: FilledField[]}[]}>`
  - `api.FilledField` — тип поля из Global Constraints.
  - Сообщение `{type: "FILL_PAGE", url, page_text, frames}` → тот же ответ.
  - Сообщение `{type: "TOGGLE_PANEL"}` в content-скрипте (пока просто вызывает заполнение; панель появится в Task 10).

- [ ] **Step 1: Написать падающий тест на сборку payload**

`ext/tests/fill-flow.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildFillPayload, mergeFrameFields } from "../lib/api";

describe("buildFillPayload", () => {
  it("trims page text and keeps frames", () => {
    const payload = buildFillPayload({
      url: "https://docs.google.com/forms/x",
      pageText: "a".repeat(50_000),
      frames: [{ frame_id: 0, snapshot: [{ ref: "f1" } as any] }],
    });
    expect(payload.page_text.length).toBe(40_000);
    expect(payload.frames[0].frame_id).toBe(0);
  });
});

describe("mergeFrameFields", () => {
  it("returns only the fields of the requested frame", () => {
    const merged = mergeFrameFields(
      { frames: [
        { frame_id: 0, fields: [{ ref: "a" } as any] },
        { frame_id: 7, fields: [{ ref: "b" } as any] },
      ] },
      7,
    );
    expect(merged.map((f) => f.ref)).toEqual(["b"]);
  });

  it("returns an empty list for an unknown frame", () => {
    expect(mergeFrameFields({ frames: [] }, 3)).toEqual([]);
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd ext && npm test`
Expected: FAIL — `buildFillPayload is not exported`

- [ ] **Step 3: Дописать `ext/lib/api.ts`**

```ts
export interface FilledField {
  frame_id: number;
  ref: string;
  selector: string;
  field_type: string;
  value: string;
  source: "profile" | "ai";
  filename?: string;
  required?: boolean;
}

export interface FillResponse {
  frames: { frame_id: number; fields: FilledField[] }[];
}

const MAX_PAGE_TEXT = 40_000;

export function buildFillPayload(input: {
  url: string;
  pageText: string;
  frames: { frame_id: number; snapshot: unknown[] }[];
}) {
  return {
    url: input.url,
    page_text: input.pageText.slice(0, MAX_PAGE_TEXT),
    frames: input.frames,
  };
}

export function mergeFrameFields(resp: FillResponse, frameId: number): FilledField[] {
  return resp.frames.find((f) => f.frame_id === frameId)?.fields ?? [];
}

export const callFill = (payload: ReturnType<typeof buildFillPayload>) =>
  apiFetch<FillResponse>("/api/extension/fill", {
    method: "POST",
    body: JSON.stringify(payload),
  });
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd ext && npm test`
Expected: 6 passed (3 из Task 7 + 3 новых)

- [ ] **Step 5: Добавить обработчик `FILL_PAGE` в `ext/entrypoints/background.ts`**

В `handle()` добавить ветку:

```ts
    case "FILL_PAGE":
      return await callFill(buildFillPayload({
        url: msg.url,
        pageText: msg.page_text ?? "",
        frames: msg.frames ?? [],
      }));
```

и импорт: `import { buildFillPayload, callFill } from "../lib/api";`

- [ ] **Step 6: Реализовать `ext/entrypoints/content.ts`**

```ts
import { defineContentScript } from "wxt/sandbox";
import { browser } from "wxt/browser";
import { applyFill, snapshotWithOptions } from "../lib/snapshot";
import { mergeFrameFields, type FillResponse } from "../lib/api";
import { renderMarks, type MarkField } from "../lib/marks";

export default defineContentScript({
  matches: ["<all_urls>"],
  allFrames: true,
  async main() {
    browser.runtime.onMessage.addListener((msg: any) => {
      if (msg?.type === "TOGGLE_PANEL" || msg?.type === "TRIGGER_AUTOFILL") {
        void runFill();
      }
      return undefined;
    });
  },
});

async function runFill(): Promise<void> {
  const els = await snapshotWithOptions();
  if (els.length === 0) return;
  const resp = (await browser.runtime.sendMessage({
    type: "FILL_PAGE",
    url: location.href,
    page_text: document.body.innerText,
    // frame_id 0: single-frame v1. Cross-frame fan-out lands in a later task.
    frames: [{ frame_id: 0, snapshot: els }],
  })) as FillResponse;
  const fields = mergeFrameFields(resp, 0);
  const applied = await applyFill(fields as never);
  renderMarks(withLabels(applied as never, els as never));
}

// renderMarks needs a human label per field; the backend only echoes refs, so
// join the labels back from the snapshot we just took. The same enriched list
// is what Task 12 diffs against to find the user's edits.
function withLabels(
  fields: { ref: string; selector: string; source: string; field_type?: string; required?: boolean }[],
  els: { ref: string; label?: string }[],
): MarkField[] {
  const labels = new Map(els.map((e) => [e.ref, e.label ?? ""]));
  return fields.map((f) => ({
    selector: f.selector,
    source: f.source as MarkField["source"],
    label: labels.get(f.ref) ?? "",
    field_type: f.field_type,
    required: f.required,
  }));
}
```

- [ ] **Step 7: Ручная проверка на живой Google-форме**

```bash
cd ext && npm run build
```

Перезагрузить дополнение, открыть любую свою Google-форму с текстовыми полями, нажать иконку.
Expected: поля заполнены, в консоли вкладки нет ошибок, submit не нажат.

- [ ] **Step 8: Проверить на Yandex Forms и forms.office.com**

Открыть по одной форме каждого сервиса, нажать иконку.
Expected: заполнено большинство текстовых полей и выбраны варианты в radio/select. Если поле не заполнилось — записать его `label`/`field_type` в `ext/NOTES.md` для следующей итерации (не чинить сейчас).

- [ ] **Step 9: Commit**

```bash
git add ext
git commit -m "feat(ext): page snapshot → backend fill → apply values"
```

---

## Task 9: Детерминированное заполнение и прикрепление PDF

**Files:**
- Modify: `ext/lib/deterministic-fill.ts`
- Modify: `ext/entrypoints/background.ts`
- Modify: `ext/entrypoints/content.ts`
- Test: `ext/tests/deterministic-fill.test.ts`

**Interfaces:**
- Consumes: `fetchContext(): Promise<ExtContext>` из Task 7, `FilledField` из Task 8.
- Produces: `deterministicFields(els: SnapshotEl[], facts: Record<string, string>, resume?: {url: string; filename: string}): FilledField[]` — поля, заполняемые без LLM (`source: "profile"`).

- [ ] **Step 1: Написать падающий тест**

`ext/tests/deterministic-fill.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { deterministicFields } from "../lib/deterministic-fill";

const FACTS = { full_name: "Иван Петров", email: "ivan@example.com", phone: "+7 777 111 22 33" };

const els = [
  { ref: "f1", selector: "#email", field_type: "text", label: "Ваш e-mail" },
  { ref: "f2", selector: "#name", field_type: "text", label: "Фамилия и имя" },
  { ref: "f3", selector: "#why", field_type: "textarea", label: "Почему вы?" },
  { ref: "f4", selector: "#cv", field_type: "file", label: "Резюме" },
] as any;

describe("deterministicFields", () => {
  it("fills email and name, leaves open questions to the LLM", () => {
    const out = deterministicFields(els, FACTS);
    const byRef = Object.fromEntries(out.map((f) => [f.ref, f]));
    expect(byRef.f1.value).toBe("ivan@example.com");
    expect(byRef.f2.value).toBe("Иван Петров");
    expect(byRef.f3).toBeUndefined();
    expect(byRef.f1.source).toBe("profile");
  });

  it("attaches the resume file only when one is available", () => {
    expect(deterministicFields(els, FACTS).find((f) => f.ref === "f4")).toBeUndefined();
    const withCv = deterministicFields(els, FACTS, { url: "blob:x", filename: "cv.pdf" });
    expect(withCv.find((f) => f.ref === "f4")?.filename).toBe("cv.pdf");
  });

  it("returns nothing without facts", () => {
    expect(deterministicFields(els, {})).toEqual([]);
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd ext && npm test -- deterministic-fill`
Expected: FAIL — `deterministicFields is not exported`

- [ ] **Step 3: Переписать `ext/lib/deterministic-fill.ts`**

```ts
import type { FilledField } from "./api";

// label → fact key. Matched case-insensitively against the field's label.
const RULES: { key: string; re: RegExp }[] = [
  { key: "email", re: /e-?mail|почт|электрон/i },
  { key: "phone", re: /phone|телефон|моб/i },
  { key: "full_name", re: /^(ф\.?и\.?о|имя и фамилия|фамилия и имя|full name|your name)/i },
  { key: "first_name", re: /^(имя|first name)\b/i },
  { key: "last_name", re: /^(фамилия|last name|surname)\b/i },
  { key: "city", re: /город|city|населённый пункт/i },
  { key: "title", re: /должность|позици|position|role/i },
];

export function deterministicFields(
  els: { ref: string; selector: string; field_type: string; label?: string; required?: boolean }[],
  facts: Record<string, string>,
  resume?: { url: string; filename: string },
): FilledField[] {
  const out: FilledField[] = [];
  for (const el of els) {
    if (el.field_type === "file") {
      if (resume) {
        out.push({ frame_id: 0, ref: el.ref, selector: el.selector, field_type: "file",
                   value: resume.url, filename: resume.filename, source: "profile",
                   required: Boolean(el.required) });
      }
      continue;
    }
    if (el.field_type !== "text") continue; // textarea = open question → LLM
    const label = el.label ?? "";
    const rule = RULES.find((r) => r.re.test(label));
    const value = rule ? facts[rule.key] : undefined;
    if (!value) continue;
    out.push({ frame_id: 0, ref: el.ref, selector: el.selector, field_type: "text",
               value, source: "profile", required: Boolean(el.required) });
  }
  return out;
}
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd ext && npm test`
Expected: 9 passed

- [ ] **Step 5: Отдать фону URL резюме**

В `ext/entrypoints/background.ts` добавить ветку в `handle()`:

```ts
    case "CONTEXT": {
      const ctx = await fetchContext();
      if (!ctx.has_resume_file) return { facts: ctx.facts, resume: null };
      // The <input type=file> path needs a fetchable URL; the content script
      // can't send the backend's Authorization header, so fetch here and hand
      // over a blob URL.
      const jwt = await getValidJwt();
      const r = await fetch(`${import.meta.env.VITE_API_BASE}/api/extension/resume-file`, {
        headers: { Authorization: `Bearer ${jwt}` },
      });
      if (!r.ok) return { facts: ctx.facts, resume: null };
      const url = URL.createObjectURL(await r.blob());
      return { facts: ctx.facts, resume: { url, filename: ctx.resume_filename ?? "resume.pdf" } };
    }
```

и импорт `fetchContext` из `../lib/api`.

- [ ] **Step 6: Использовать в `content.ts` — сначала факты, потом LLM**

В `runFill()` перед вызовом `FILL_PAGE`:

```ts
  const ctx = (await browser.runtime.sendMessage({ type: "CONTEXT" })) as {
    facts: Record<string, string>;
    resume: { url: string; filename: string } | null;
  };
  const quick = deterministicFields(els as never, ctx.facts, ctx.resume ?? undefined);
  if (quick.length) {
    renderMarks(withLabels(await applyFill(quick as never) as never, els as never));
  }
  const remaining = els.filter((e) => !quick.some((q) => q.ref === e.ref));
```

и дальше в снапшот для `FILL_PAGE` отправлять `remaining` вместо `els`.

- [ ] **Step 7: Ручная проверка**

```bash
cd ext && npm run build
```

Открыть форму с полями «Имя», «E-mail» и «Резюме (файл)», нажать иконку.
Expected: имя и почта заполнены мгновенно (до ответа LLM), файл прикреплён, имя файла видно в поле.

- [ ] **Step 8: Commit**

```bash
git add ext
git commit -m "feat(ext): deterministic facts fill + hh resume attachment"
```

---

## Task 10: Панель с тремя вкладками

Старый `sidebar.ts` (2109 строк) не переносится — 14 из его 24 колбэков относятся к вырезанным функциям. Пишем новую панель.

**Files:**
- Create: `ext/lib/panel.ts`
- Modify: `ext/entrypoints/content.ts`
- Test: `ext/tests/panel.test.ts`

**Interfaces:**
- Consumes: ничего из старого sidebar.
- Produces:
  - `mountPanel(cb: PanelCallbacks): PanelController`
  - `PanelCallbacks = { onFill(): void; onSignIn(): void; onSignOut(): void; onSend(text: string): Promise<string>; onSaveEdits(): void }`
  - `PanelController = { toggle(): void; setAuth(loggedIn: boolean, email: string): void; setState(s: "idle"|"working"|"done"|"error", data?: {error?: string; filled?: number}): void; appendChat(role: "user"|"assistant", text: string): void; setTab(t: "fill"|"chat"|"settings"): void }`
  - `renderFilledList(fields: {label: string; value: string; source: string}[]): string` — чистая функция для теста.

- [ ] **Step 1: Написать падающий тест на чистый рендер**

`ext/tests/panel.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { renderFilledList } from "../lib/panel";

describe("renderFilledList", () => {
  it("marks AI values apart from profile values", () => {
    const html = renderFilledList([
      { label: "E-mail", value: "a@b.c", source: "profile" },
      { label: "Почему вы?", value: "Потому что", source: "ai" },
    ]);
    expect(html).toContain("E-mail");
    expect(html).toContain("otc-src-ai");
    expect(html).toContain("otc-src-profile");
  });

  it("escapes user content", () => {
    const html = renderFilledList([{ label: "<img src=x onerror=1>", value: "v", source: "ai" }]);
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  it("shows an empty state", () => {
    expect(renderFilledList([])).toContain("Пока ничего не заполнено");
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd ext && npm test -- panel`
Expected: FAIL — модуля нет

- [ ] **Step 3: Написать `ext/lib/panel.ts`**

```ts
import { browser } from "wxt/browser";

export type Tab = "fill" | "chat" | "settings";
export type FillState = "idle" | "working" | "done" | "error";

export interface PanelCallbacks {
  onFill: () => void;
  onSignIn: () => void;
  onSignOut: () => void;
  onSend: (text: string) => Promise<string>;
  onSaveEdits: () => void;
}

export interface PanelController {
  toggle: () => void;
  setAuth: (loggedIn: boolean, email: string) => void;
  setState: (s: FillState, data?: { error?: string; filled?: number }) => void;
  setFilled: (fields: { label: string; value: string; source: string }[]) => void;
  appendChat: (role: "user" | "assistant", text: string) => void;
  setTab: (t: Tab) => void;
}

const HOST_ID = "otclick-panel-root";

export function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

export function renderFilledList(
  fields: { label: string; value: string; source: string }[],
): string {
  if (fields.length === 0) return `<p class="otc-empty">Пока ничего не заполнено</p>`;
  return `<ul class="otc-list">${fields
    .map((f) => `<li class="otc-src-${esc(f.source)}"><span class="otc-k">${esc(f.label)}</span>` +
                `<span class="otc-v">${esc(f.value)}</span></li>`)
    .join("")}</ul>`;
}

const CSS = `
:host { all: initial; }
.otc-wrap { position: fixed; top: 0; right: 0; width: 360px; height: 100vh; z-index: 2147483647;
  background: #fff; color: #111; font: 14px/1.4 system-ui, sans-serif;
  box-shadow: -2px 0 12px rgba(0,0,0,.15); display: flex; flex-direction: column; }
.otc-wrap[hidden] { display: none; }
.otc-tabs { display: flex; border-bottom: 1px solid #e5e5e5; }
.otc-tabs button { flex: 1; padding: 10px; border: 0; background: none; cursor: pointer; }
.otc-tabs button[aria-selected="true"] { font-weight: 600; border-bottom: 2px solid #111; }
.otc-body { flex: 1; overflow: auto; padding: 12px; }
.otc-list { list-style: none; margin: 0; padding: 0; }
.otc-list li { padding: 6px 0; border-bottom: 1px solid #f0f0f0; display: flex; gap: 8px; }
.otc-k { flex: 0 0 40%; color: #666; }
.otc-src-ai .otc-v { color: #7a3cc0; }
.otc-empty { color: #888; }
.otc-foot { padding: 12px; border-top: 1px solid #e5e5e5; display: flex; gap: 8px; }
button.otc-primary { padding: 8px 14px; background: #111; color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
.otc-chat-msg { margin-bottom: 10px; white-space: pre-wrap; }
.otc-chat-msg.user { text-align: right; color: #333; }
`;

export function mountPanel(cb: PanelCallbacks): PanelController {
  document.getElementById(HOST_ID)?.remove();
  const host = document.createElement("div");
  host.id = HOST_ID;
  const root = host.attachShadow({ mode: "open" });
  document.documentElement.appendChild(host);

  root.innerHTML = `
    <style>${CSS}</style>
    <div class="otc-wrap" hidden>
      <div class="otc-tabs">
        <button data-tab="fill" aria-selected="true">Заполнение</button>
        <button data-tab="chat" aria-selected="false">Чат</button>
        <button data-tab="settings" aria-selected="false">Настройки</button>
      </div>
      <div class="otc-body" data-pane="fill">
        <p class="otc-status"></p>
        <div class="otc-filled"></div>
      </div>
      <div class="otc-body" data-pane="chat" hidden>
        <div class="otc-chat"></div>
      </div>
      <div class="otc-body" data-pane="settings" hidden>
        <p class="otc-email"></p>
        <button class="otc-signin otc-primary">Войти</button>
        <button class="otc-signout otc-primary" hidden>Выйти</button>
      </div>
      <div class="otc-foot" data-foot="fill">
        <button class="otc-fill otc-primary">Заполнить</button>
        <button class="otc-save otc-primary" hidden>Сохранить правки</button>
      </div>
      <div class="otc-foot" data-foot="chat" hidden>
        <input class="otc-chat-input" placeholder="Спросите что угодно" style="flex:1" />
        <button class="otc-send otc-primary">→</button>
      </div>
    </div>`;

  const $ = <T extends Element>(sel: string) => root.querySelector(sel) as T;
  const wrap = $<HTMLDivElement>(".otc-wrap");

  const setTab = (tab: Tab) => {
    root.querySelectorAll("[data-tab]").forEach((b) =>
      b.setAttribute("aria-selected", String(b.getAttribute("data-tab") === tab)));
    root.querySelectorAll("[data-pane]").forEach((p) =>
      ((p as HTMLElement).hidden = p.getAttribute("data-pane") !== tab));
    root.querySelectorAll("[data-foot]").forEach((f) =>
      ((f as HTMLElement).hidden = f.getAttribute("data-foot") !== tab));
  };
  root.querySelectorAll("[data-tab]").forEach((b) =>
    b.addEventListener("click", () => setTab(b.getAttribute("data-tab") as Tab)));

  $(".otc-fill").addEventListener("click", () => cb.onFill());
  $(".otc-save").addEventListener("click", () => cb.onSaveEdits());
  $(".otc-signin").addEventListener("click", () => cb.onSignIn());
  $(".otc-signout").addEventListener("click", () => cb.onSignOut());

  const chatBox = $<HTMLDivElement>(".otc-chat");
  const appendChat = (role: "user" | "assistant", text: string) => {
    const div = document.createElement("div");
    div.className = `otc-chat-msg ${role}`;
    div.textContent = text;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
  };
  const send = async () => {
    const input = $<HTMLInputElement>(".otc-chat-input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    appendChat("user", text);
    appendChat("assistant", await cb.onSend(text));
  };
  $(".otc-send").addEventListener("click", () => void send());
  $<HTMLInputElement>(".otc-chat-input").addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Enter") void send();
  });

  return {
    toggle: () => (wrap.hidden = !wrap.hidden),
    setTab,
    setAuth: (loggedIn, email) => {
      $(".otc-email").textContent = loggedIn ? email : "Вы не вошли";
      ($(".otc-signin") as HTMLElement).hidden = loggedIn;
      ($(".otc-signout") as HTMLElement).hidden = !loggedIn;
    },
    setState: (s, data) => {
      const text = {
        idle: "", working: "Заполняю…",
        done: `Готово: ${data?.filled ?? 0} полей. Проверьте и отправьте форму сами.`,
        error: data?.error ?? "Ошибка",
      }[s];
      $(".otc-status").textContent = text;
      ($(".otc-save") as HTMLElement).hidden = s !== "done";
    },
    setFilled: (fields) => { $(".otc-filled").innerHTML = renderFilledList(fields); },
    appendChat,
  };
}
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd ext && npm test`
Expected: 12 passed

- [ ] **Step 5: Смонтировать панель в `content.ts`**

В `main()` (только в верхнем фрейме — `window.top === window`):

```ts
    if (window.top !== window) return; // panel lives in the top frame only
    const panel = mountPanel({
      onFill: () => void runFill(panel),
      onSignIn: () => void browser.runtime.sendMessage({ type: "SIGN_IN" }),
      onSignOut: () => void browser.runtime.sendMessage({ type: "SIGN_OUT" }),
      onSend: async (text) => "чат подключается в следующей задаче",
      onSaveEdits: () => void 0,
    });
    const auth = (await browser.runtime.sendMessage({ type: "AUTH_STATUS" })) as
      { loggedIn: boolean; email: string };
    panel.setAuth(auth.loggedIn, auth.email);
```

`runFill` принимает `panel` и вызывает `panel.setState("working")` / `setFilled(...)` / `setState("done", {filled})`; при `Error("unauthorized")` — `setState("error", {error: "Войдите в аккаунт Otclick"})` и `setTab("settings")`.

- [ ] **Step 6: Ручная проверка**

```bash
cd ext && npm run build
```

Открыть форму, нажать иконку: панель открывается справа, показывает email, кнопка «Заполнить» работает, список заполненного отображается, ИИ-значения отличаются цветом.

- [ ] **Step 7: Commit**

```bash
git add ext
git commit -m "feat(ext): three-tab panel replacing the OtclickUS sidebar"
```

---

## Task 11: Чат с ИИ

**Files:**
- Create: `ext/lib/chat-store.ts`
- Modify: `ext/lib/api.ts`
- Modify: `ext/entrypoints/background.ts`
- Modify: `ext/entrypoints/content.ts`
- Test: `ext/tests/chat-store.test.ts`

**Interfaces:**
- Consumes: `apiFetch`.
- Produces:
  - `chat-store`: `loadHistory(): Promise<ChatMsg[]>`, `appendMessage(m: ChatMsg): Promise<ChatMsg[]>`, `clearHistory(): Promise<void>`, `ChatMsg = {role: "user"|"assistant"; content: string}`; хранится не более 40 последних сообщений.
  - `api.callChat(messages: ChatMsg[], pageText?: string): Promise<string>`
  - Сообщение `{type: "CHAT", messages, page_text}` → `{answer: string}`

- [ ] **Step 1: Написать падающий тест**

`ext/tests/chat-store.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

const store: Record<string, unknown> = {};
vi.mock("wxt/browser", () => ({
  browser: {
    storage: {
      local: {
        get: async (k: string) => ({ [k]: store[k] }),
        set: async (o: Record<string, unknown>) => Object.assign(store, o),
        remove: async (k: string) => { delete store[k]; },
      },
    },
  },
}));

import { appendMessage, clearHistory, loadHistory, MAX_HISTORY } from "../lib/chat-store";

beforeEach(async () => { await clearHistory(); });

describe("chat-store", () => {
  it("starts empty", async () => {
    expect(await loadHistory()).toEqual([]);
  });

  it("appends and persists in order", async () => {
    await appendMessage({ role: "user", content: "раз" });
    const after = await appendMessage({ role: "assistant", content: "два" });
    expect(after.map((m) => m.content)).toEqual(["раз", "два"]);
    expect(await loadHistory()).toHaveLength(2);
  });

  it("keeps only the last MAX_HISTORY messages", async () => {
    for (let i = 0; i < MAX_HISTORY + 5; i++) {
      await appendMessage({ role: "user", content: `m${i}` });
    }
    const hist = await loadHistory();
    expect(hist).toHaveLength(MAX_HISTORY);
    expect(hist[0].content).toBe("m5");
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd ext && npm test -- chat-store`
Expected: FAIL — модуля нет

- [ ] **Step 3: Написать `ext/lib/chat-store.ts`**

```ts
import { browser } from "wxt/browser";

export interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

const KEY = "otc_chat_history";
export const MAX_HISTORY = 40;

export async function loadHistory(): Promise<ChatMsg[]> {
  const got = await browser.storage.local.get(KEY);
  const list = (got as Record<string, unknown>)[KEY];
  return Array.isArray(list) ? (list as ChatMsg[]) : [];
}

export async function appendMessage(m: ChatMsg): Promise<ChatMsg[]> {
  const next = [...(await loadHistory()), m].slice(-MAX_HISTORY);
  await browser.storage.local.set({ [KEY]: next });
  return next;
}

export async function clearHistory(): Promise<void> {
  await browser.storage.local.remove(KEY);
}
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd ext && npm test`
Expected: 15 passed

- [ ] **Step 5: Добавить `callChat` в `ext/lib/api.ts`**

```ts
import type { ChatMsg } from "./chat-store";

export const callChat = (messages: ChatMsg[], pageText?: string) =>
  apiFetch<{ answer: string }>("/api/extension/chat", {
    method: "POST",
    body: JSON.stringify({ messages, page_text: pageText ?? null }),
  }).then((r) => r.answer);
```

- [ ] **Step 6: Добавить ветку `CHAT` в фон**

```ts
    case "CHAT":
      return { answer: await callChat(msg.messages ?? [], msg.page_text ?? undefined) };
```

- [ ] **Step 7: Подключить чат в `content.ts`**

Заменить заглушку `onSend`:

```ts
      onSend: async (text) => {
        const history = await appendMessage({ role: "user", content: text });
        const resp = (await browser.runtime.sendMessage({
          type: "CHAT",
          messages: history,
          page_text: seePageEnabled ? document.body.innerText.slice(0, 20000) : null,
        })) as { answer?: string; error?: string };
        const answer = resp.answer ?? "Не удалось получить ответ.";
        await appendMessage({ role: "assistant", content: answer });
        return answer;
      },
```

`seePageEnabled` — константа `true` в v1 (чекбокс в панели добавляется здесь же, если останется время; если нет — оставить `true` и отметить в `ext/NOTES.md`).

При монтировании панели восстановить историю:

```ts
    for (const m of await loadHistory()) panel.appendChat(m.role, m.content);
```

- [ ] **Step 8: Ручная проверка**

```bash
cd ext && npm run build
```

Открыть форму, вкладка «Чат», спросить «Какой у меня опыт работы?».
Expected: ответ опирается на резюме с hh. Перезагрузить страницу — история сохранилась.

- [ ] **Step 9: Commit**

```bash
git add ext
git commit -m "feat(ext): chat tab with local history and candidate context"
```

---

## Task 12: Сохранение правок в qa_memory

**Files:**
- Modify: `ext/entrypoints/content.ts`
- Modify: `ext/entrypoints/background.ts`
- Create: `ext/lib/edits.ts`
- Test: `ext/tests/edits.test.ts`

**Interfaces:**
- Consumes: `FilledField` (Task 8), `apiFetch`.
- Produces:
  - `collectEdits(applied: FilledField[], current: {ref: string; label: string; value: string}[]): {question: string; answer: string}[]` — только изменённые пользователем поля, пустые отбрасываются.
  - `api.saveQA(items): Promise<number>`
  - Сообщение `{type: "SAVE_QA", items}` → `{saved: number}`

- [ ] **Step 1: Написать падающий тест**

`ext/tests/edits.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { collectEdits } from "../lib/edits";

const applied = [
  { ref: "f1", value: "Иван", label: "Имя" },
  { ref: "f2", value: "3 года", label: "Опыт" },
] as any;

describe("collectEdits", () => {
  it("returns only the fields the user changed", () => {
    const out = collectEdits(applied, [
      { ref: "f1", label: "Имя", value: "Иван" },
      { ref: "f2", label: "Опыт", value: "5 лет" },
    ]);
    expect(out).toEqual([{ question: "Опыт", answer: "5 лет" }]);
  });

  it("skips cleared fields and unlabelled ones", () => {
    const out = collectEdits(applied, [
      { ref: "f1", label: "Имя", value: "" },
      { ref: "f2", label: "", value: "что-то" },
    ]);
    expect(out).toEqual([]);
  });

  it("ignores fields that were never filled by us", () => {
    expect(collectEdits(applied, [{ ref: "f9", label: "Другое", value: "x" }])).toEqual([]);
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd ext && npm test -- edits`
Expected: FAIL — модуля нет

- [ ] **Step 3: Написать `ext/lib/edits.ts`**

```ts
import type { FilledField } from "./api";

/** Q&A pairs worth remembering: a field we filled whose value the user then
 *  changed to something non-empty. Unchanged values teach us nothing. */
export function collectEdits(
  applied: (FilledField & { label?: string })[],
  current: { ref: string; label: string; value: string }[],
): { question: string; answer: string }[] {
  const before = new Map(applied.map((f) => [f.ref, f]));
  const out: { question: string; answer: string }[] = [];
  for (const cur of current) {
    const prev = before.get(cur.ref);
    if (!prev) continue;
    const question = (cur.label ?? "").trim();
    const answer = (cur.value ?? "").trim();
    if (!question || !answer) continue;
    if (answer === (prev.value ?? "").trim()) continue;
    out.push({ question, answer });
  }
  return out;
}
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd ext && npm test`
Expected: 18 passed

- [ ] **Step 5: Добавить `saveQA` в `ext/lib/api.ts` и ветку в фон**

```ts
export const saveQA = (items: { question: string; answer: string }[]) =>
  apiFetch<{ saved: number }>("/api/extension/qa", {
    method: "POST",
    body: JSON.stringify({ items }),
  }).then((r) => r.saved);
```

Фон:

```ts
    case "SAVE_QA":
      return { saved: await saveQA(msg.items ?? []) };
```

- [ ] **Step 6: Подключить в `content.ts`**

Запомнить в модульной переменной `lastApplied: (FilledField & { label: string })[]` — тот же список, что `runFill` уже собирает через `withLabels` (взять `ref` из ответа бэкенда, `label` из снапшота). В `onSaveEdits`:

```ts
      onSaveEdits: () => void (async () => {
        const current = (await snapshotWithOptions()).map((el: any) => ({
          ref: el.ref, label: el.label ?? "", value: el.value ?? "",
        }));
        const items = collectEdits(lastApplied as never, current);
        if (items.length === 0) { panel.setState("done", { filled: lastApplied.length }); return; }
        const resp = (await browser.runtime.sendMessage({ type: "SAVE_QA", items })) as { saved: number };
        panel.setState("done", { filled: resp.saved });
      })(),
```

`SnapshotEl` не хранит текущее значение поля. В `ext/lib/marks.ts` уже есть внутренняя функция `readFieldValue(el)`, покрывающая input/textarea/select/contenteditable — добавить ей `export` и использовать здесь вместе с `findEl(el.selector)` из `lib/snapshot.ts`:

```ts
const value = (() => {
  const node = findEl(el.selector);
  return node ? readFieldValue(node).trim() : "";
})();
```

- [ ] **Step 7: Ручная проверка сквозного цикла**

```bash
cd ext && npm run build
```

1. Заполнить форму, изменить один ответ вручную, нажать «Сохранить правки».
2. Открыть `http://localhost:3000` → страница Q&A памяти.
   Expected: новая пара «вопрос — ваш ответ» видна в списке.

- [ ] **Step 8: Commit**

```bash
git add ext
git commit -m "feat(ext): persist user edits to qa_memory"
```

---

## Task 13: CI и документация

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `ext/README.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: скрипты `npm run typecheck`, `npm test`, `npm run build` из `ext/package.json`.
- Produces: зелёный CI-джоб `ext` на каждый PR.

- [ ] **Step 1: Добавить джоб в `.github/workflows/ci.yml`**

Скопировать структуру существующего фронтенд-джоба, поменяв рабочий каталог:

```yaml
  ext:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ext
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npm ci
      - run: npm run typecheck
      - run: npm test
      - run: npm run build
        env:
          VITE_API_BASE: http://localhost:8000
          VITE_APP_BASE: http://localhost:3000
          VITE_SUPABASE_URL: http://localhost:54321
          VITE_SUPABASE_ANON_KEY: ci-placeholder
```

Точные значения `runs-on`/версии Node взять из соседнего джоба, чтобы не разъезжались.

- [ ] **Step 2: Убедиться, что есть `ext/package-lock.json`**

```bash
cd ext && npm install && git status --short package-lock.json
```

Expected: файл есть (нужен для `npm ci`).

- [ ] **Step 3: Написать `ext/README.md`**

```markdown
# Otclick Autofill (Firefox)

Расширение заполняет анкеты в Google Forms, Yandex Forms и Microsoft Forms
данными вашего hh-резюме. Отправляете форму вы сами — расширение никогда не
нажимает «Отправить».

## Запуск локально

1. Поднять стек Otclick-HH: `docker compose up -d` в корне репозитория.
2. `cp .env.example .env`, вписать `VITE_SUPABASE_ANON_KEY` (значение
   `SUPABASE_ANON_KEY` из корневого `.env`).
3. `npm install && npm run build`
4. Firefox → `about:debugging#/runtime/this-firefox` → Load Temporary Add-on →
   `.output/firefox-mv3/manifest.json`
5. Войти на `http://localhost:3000` — расширение подхватит сессию само.

## Команды

| Команда | Что делает |
|---|---|
| `npm run dev` | сборка с автоперезагрузкой |
| `npm run build` | production-сборка в `.output/firefox-mv3` |
| `npm test` | vitest |
| `npm run typecheck` | tsc --noEmit |

## Как это устроено

`entrypoints/content.ts` собирает поля страницы (`lib/snapshot.ts`), фоновая
страница шлёт их на `POST /api/extension/fill`, значения проставляются
`FormFiller` и подсвечиваются (`lib/marks.ts`). Паспортные поля и файл резюме
заполняются без LLM (`lib/deterministic-fill.ts`). Вкладка «Чат» ходит в
`POST /api/extension/chat`, история — в `browser.storage.local`.
```

- [ ] **Step 4: Дополнить корневой `CLAUDE.md`**

В список подпроектов (раздел Project Overview) добавить строку:

```markdown
- **`ext/`** — Firefox-расширение (WXT): автозаполнение Google/Yandex/MS Forms + чат с ИИ. Бэкенд — `/api/extension/*`. Каталог `extension/` (gitignored) — исходная копия расширения OtclickUS, из которой оно форкнуто; не редактировать.
```

В раздел Backend Architecture, в список `api/`, добавить:

```markdown
  extension.py               — /api/extension/* (context, fill, chat, qa, resume-file) для Firefox-расширения
```

и в список `services/`:

```markdown
  candidate_context.py       — контекст кандидата для расширения: load_resume + _resume_summary + qa_memory
  extension_resume.py        — PDF резюме с hh (байты) для <input type=file>
```

- [ ] **Step 5: Дополнить корневой `README.md`**

В список возможностей добавить пункт про расширение со ссылкой на `ext/README.md`.

- [ ] **Step 6: Прогнать всё локально**

```bash
cd ext && npm run typecheck && npm test && npm run build
cd ../backend && python -m pytest tests/ -q && ruff check app tests
```

Expected: всё зелёное

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml ext/README.md ext/package-lock.json CLAUDE.md README.md
git commit -m "ci: build and test the Firefox extension; document it"
```

---

## Приёмка

После Task 13 проверить критерии из спеки вручную:

1. `cd ext && npm run build` — собирается; add-on грузится в Firefox.
2. Вход: открыть Otclick в соседней вкладке → панель показывает email.
3. Google Form, Yandex Form, forms.office.com: поля заполнены, подсвечены, submit не нажат.
4. Вкладка «Чат» отвечает с учётом резюме.
5. Правка + «Сохранить» → пара видна в Q&A памяти веб-кабинета.
6. `pytest backend/tests` и `npm test` в `ext/` зелёные.

Известные упрощения v1, зафиксированные сознательно:
- Заполняется только верхний фрейм (`frame_id: 0`). Формы внутри iframe (частый случай на корпоративных порталах) — следующая итерация; каркас `frames[]` для этого уже готов на обеих сторонах.
- Без SSE: ответ приходит целиком. Если ожидание превысит ~5 с на типичной форме — вернуться к стриму, парсер SSE есть в исходном `extension/lib/api.ts`.
- Чат всегда видит текст страницы. Чекбокс-переключатель — по итогам использования.
