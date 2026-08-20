"""LangChain tools for the recruiter chat agent.

Tools perform their own side effects (hh POST / DB write). Per-chat data is
injected via ToolRuntime[RecruiterContext] at agent runtime and is hidden from
the model. ToolRuntime cannot be built by hand, so the side-effect logic lives
in plain helpers (do_answer / do_ask / do_todo) that take a RecruiterContext;
the tools are thin adapters over them.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain.tools import ToolRuntime, tool

from app.ai.prompts import sanitize_ai_text
from app.hh.client import ApiClient
from app.services import recruiter
from app.services.notifications import notify


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
    chat_id: str | None = None
    applicant_id: str | None = None
    vacancy_id: str | None = None
    vacancy_title: str | None = None
    employer_name: str | None = None
    # Flipped by any successful side effect; the agent checks it after the run to
    # catch "model replied text and called nothing" (see HHAgent._run_recruiter).
    acted: bool = False


def match_label(labels: list[str], text: str | None) -> str | None:
    """Resolve a model-supplied answer to one of the bot's exact button labels.

    The hh robot accepts a reply ONLY when it matches a label verbatim, so we
    map the model's text back to the real label string (preserving e.g. a
    trailing space). None when it does not map to a single option."""
    t = (text or "").strip().strip('"').strip()
    tl = t.lower()
    for label in labels:  # exact (preferred)
        if t == label:
            return label
    for label in labels:  # equal ignoring label's surrounding whitespace / case
        if tl == label.strip().lower():
            return label
    for label in labels:  # model echoed the label inside a sentence
        ls = label.strip().lower()
        if ls and (ls in tl or tl in ls):
            return label
    return None


# --- side-effect helpers (testable without a ToolRuntime) --------------------

async def do_answer(ctx: RecruiterContext, message: str) -> str:
    """Answer the recruiter's question — always queued as a draft for the user
    to review/send (never auto-posted). Two modes, picked by whether the
    current message carries robot quick-reply buttons:

    - buttons present (ctx.quick_reply_labels): the bot accepts ONLY a verbatim
      label match (else it loops), so `message` is matched against the allowed
      set and stored as-is (no sanitize — would break e.g. a trailing space).
    - no buttons: free-text answer, sanitized before storing."""
    if ctx.quick_reply_labels:
        matched = match_label(ctx.quick_reply_labels, message)
        if matched is None:
            return f"error: '{message}' не входит в варианты {ctx.quick_reply_labels}"
        await recruiter.insert_draft(
            ctx.user_id, ctx.negotiation_id, ctx.message_id, matched, "",
            question_text=ctx.question_text,
            vacancy_id=ctx.vacancy_id, vacancy_title=ctx.vacancy_title,
            employer_name=ctx.employer_name,
        )
        await notify(ctx.user_id, "recruiter_draft", {"negotiation_id": ctx.negotiation_id})
        ctx.acted = True
        return "escalated"
    await recruiter.insert_draft(
        ctx.user_id, ctx.negotiation_id, ctx.message_id, sanitize_ai_text(message), "",
        question_text=ctx.question_text,
        vacancy_id=ctx.vacancy_id, vacancy_title=ctx.vacancy_title,
        employer_name=ctx.employer_name,
    )
    await notify(ctx.user_id, "recruiter_draft", {"negotiation_id": ctx.negotiation_id})
    ctx.acted = True
    return "escalated"


async def do_ask(ctx: RecruiterContext, questions: list[str], reason: str) -> str:
    """Ask the candidate one or more short direct questions instead of guessing
    the recruiter's answer. The question set is persisted as a pending row; the
    user answers on the Todo page, and the worker poller re-invokes the agent
    with the answers fed back in as a tool response (see
    HHAgent.resume_recruiter_with_answers) to produce the real reply draft."""
    await recruiter.insert_question(
        ctx.user_id, ctx.negotiation_id, ctx.message_id, questions, reason,
        question_text=ctx.question_text,
        chat_id=ctx.chat_id, applicant_id=ctx.applicant_id,
        vacancy_id=ctx.vacancy_id, vacancy_title=ctx.vacancy_title,
        employer_name=ctx.employer_name,
    )
    await notify(ctx.user_id, "recruiter_question", {"negotiation_id": ctx.negotiation_id})
    ctx.acted = True
    return "asked"


async def do_todo(ctx: RecruiterContext, title: str, detail: str, link: str | None) -> str:
    await recruiter.insert_todo(
        ctx.user_id, ctx.negotiation_id, ctx.message_id, title, detail, link,
        vacancy_id=ctx.vacancy_id, vacancy_title=ctx.vacancy_title,
        employer_name=ctx.employer_name,
    )
    await notify(ctx.user_id, "recruiter_todo", {"negotiation_id": ctx.negotiation_id, "title": title})
    ctx.acted = True
    return "todo_created"


# --- tools (thin adapters; runtime injected by create_agent) -----------------

@tool(return_direct=True)
async def answer_recruiter_question(message: str, runtime: ToolRuntime[RecruiterContext]) -> str:
    """Ответить на вопрос рекрутёра (текстом или кнопкой) — черновик уходит
    пользователю на проверку, ничего не отправляется в hh автоматически.

    КОГДА ИСПОЛЬЗОВАТЬ:
    - Вопрос закрытый, ответ ЕСТЬ в резюме кандидата (зарплата, опыт с
      технологией, город, удалёнка/релокация, владение языком).
    - К последнему сообщению приложены кнопки-варианты (список дан в задании) -
      выбери ОДИН правдивый по резюме, message = его ДОСЛОВНЫЙ текст.

    КОГДА НЕ ИСПОЛЬЗОВАТЬ:
    - Назначение времени собеседования → escalate_to_human.
    - Запрос данных, которых нет в резюме → escalate_to_human.
    - Есть кнопки, но ни одна не подходит / неоднозначно → escalate_to_human
      (НЕ угадывай).
    - Просьба заполнить форму / написать в Telegram / позвонить → make_todo.
    - Отказ или "резюме в обработке" → не вызывай инструменты вообще.

    PARAMETERS:
    - message (str, required): текст ответа на русском (или языке рекрутёра),
      либо ДОСЛОВНЫЙ текст выбранной кнопки (если кнопки есть).
      Формат для текстового ответа: plain text, 1-2 коротких предложения,
      БЕЗ markdown (*, _, **), БЕЗ длинных тире (—), БЕЗ эмодзи, БЕЗ приветствий
      "Уважаемые господа". Длина: 5-200 символов. Не пустая строка.
      Формат для кнопки: точный текст варианта, включая регистр и пробелы,
      без перефразирования.
      Пример good (текст): "250 000-300 000 руб на руки, готов обсудить."
      Пример good (кнопка): варианты ['Да, есть', 'Нет '] → message="Да, есть".
      Пример bad: "**Здравствуйте!** Мой опыт — 5 лет..."

    RETURNS: "escalated" при успешном сохранении черновика; строку "error: ..."
    если кнопки есть, а message не совпал ни с одним вариантом (тогда выбери
    корректный вариант или используй escalate_to_human).

    EDGE CASES:
    - Свободный текст автоматически санитизируется; текст кнопки — нет (нужен
      точный матч).
    - Вызывается РОВНО ОДИН раз за сообщение рекрутёра. Не дублировать.
    """
    return await do_answer(runtime.context, message)


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


@tool(return_direct=True)
async def make_todo(title: str, detail: str, link: str | None,
                    runtime: ToolRuntime[RecruiterContext]) -> str:
    """Создать задачу для действия ВНЕ hh.ru (форма, Telegram, звонок, e-mail).

    КОГДА ИСПОЛЬЗОВАТЬ:
    - Рекрутёр просит заполнить Google Form / Notion / Typeform.
    - Просит написать в Telegram/WhatsApp по @username или номеру.
    - Просит позвонить по номеру.
    - Просит отправить файлы/портфолио на e-mail.

    КОГДА НЕ ИСПОЛЬЗОВАТЬ:
    - Ответить можно прямо в hh-чате → answer_recruiter_question.
    - Нужен ручной ответ человека → escalate_to_human.

    PARAMETERS:
    - title (str, required): короткое название задачи в императиве.
      Формат: 3-8 слов, на русском, БЕЗ markdown, БЕЗ точки в конце.
      Пример good: "Заполнить Google-форму вакансии"
      Пример bad: "Нужно бы заполнить форму, которую прислал рекрутёр."
    - detail (str, required): что конкретно сделать + контекст из сообщения.
      Формат: 1-3 предложения, plain text, БЕЗ markdown. Длина: 10-400 символов.
      Пример: "Рекрутёр Анна просит заполнить форму до пятницы."
    - link (str | None, required): прямой URL формы/профиля/чата если ЕСТЬ в
      сообщении рекрутёра, иначе None (НЕ пустая строка, НЕ "нет", НЕ выдуманный).
      Допустимые форматы: "https://...", "tg://...", "mailto:...", None.
      Примеры: "https://forms.gle/abc", "https://t.me/recruiter_anna", None.
      НИКОГДА не подставляй сюда ссылку/контакт на мессенджер MAX (max.ru и
      т.п.) - кандидат туда не пишет. Если рекрутёр дал контакт и в MAX, и в
      Telegram - бери ТОЛЬКО Telegram-ссылку. Если рекрутёр дал контакт ТОЛЬКО
      в MAX - link=None, а сам факт (что просят написать в MAX) укажи в detail.

    RETURNS: "todo_created" при успешном создании.

    EDGE CASES:
    - Если рекрутёр дал номер телефона без ссылки → link=None, номер в detail.
    - Если в сообщении несколько ссылок → выбери основную (форма > профиль).
    - Пользователь получит уведомление recruiter_todo в UI.
    """
    return await do_todo(runtime.context, title, detail, link)


RECRUITER_TOOLS = [
    answer_recruiter_question, escalate_to_human, make_todo,
]
