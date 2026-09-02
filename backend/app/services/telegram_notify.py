"""Telegram Bot channel: outbound push with inline action buttons + inbound.

Two halves:

- ``push_sync`` — outbound. Called from notifications.notify() in a worker
  thread for every event. Actionable types (questions, drafts, form approvals,
  todos) carry an entity id; we attach inline buttons so the user can
  approve / discard / edit right in Telegram.

- ``start_bot_loop`` / ``stop_bot_loop`` — inbound. A long-poll loop started
  by the worker; resolves the single configured chat to a user_id and handles
  callback_query (button presses) + text messages (answers to questions and
  draft edits). All side effects go through the existing service layer
  (recruiter / form_drafts), exactly as the web UI does — so nothing is
  duplicated or routed around.

Failing to send (bad token, blocked chat, network) is logged and swallowed —
a Telegram outage must never break the worker's own notification path.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"

# Friendly Russian labels per notification type, so the Telegram message reads
# like a human alert, not an internal enum. None = skip (too noisy / UI-only).
_TYPE_LABELS: dict[str, str | None] = {
    "captcha": "🤖 Капча",
    "worker_stop": "⏹ Воркер остановлен",
    "limit_reached": "📊 Дневной лимит",
    "limit_total": "🚫 Лимит исчерпан",
    "token_dead": "💀 Сессия hh.ru мертва",
    "account_banned": "⛔ Аккаунт hh.ru заблокирован",
    "resume_missing": "📄 Резюме не найдено",
    "recruiter_draft": "💬 Ответ рекрутёру (черновик)",
    "recruiter_todo": "📌 Задача вне hh.ru",
    "recruiter_question": "❓ Вопрос рекрутёра",
    "form_approval": "📝 Анкета на согласование",
    "cover_letter_written": "✉️ Письмо написано",
    "web_session_expired": "⏳ Веб-сессия истекла",
    "antibot_pause": "🛑 Пауза: антибот hh.ru",
}


# --- outbound formatting ------------------------------------------------------

def _vacancy_url(vacancy_id: Any) -> str | None:
    """https://hh.ru/vacancy/<id>. None when there's no id to link to."""
    if vacancy_id is None or str(vacancy_id).strip() == "":
        return None
    return f"https://hh.ru/vacancy/{vacancy_id}"


def _truncate(text: str, limit: int = 600) -> str:
    """Telegram message cap is 4096; keep drafts/questions readable on phone."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _format_message(type_: str, payload: dict[str, Any]) -> str | None:
    """Human-readable body text (without the buttons). None = skip this type."""
    label = _TYPE_LABELS.get(type_)
    if label is None:
        return None  # event type not pushed to Telegram

    lines = [label]

    # Vacancy-linked events: lead with the title + clickable hh.ru link,
    # instead of a bare "vacancy_id: 123" the user can't act on.
    vacancy_id = payload.get("vacancy_id")
    title = payload.get("vacancy_title") or payload.get("vacancy_name")
    employer = payload.get("employer") or payload.get("employer_name")
    url = _vacancy_url(vacancy_id)
    if url is not None:
        head = str(title or f"Вакансия {vacancy_id}")
        if employer:
            head = f"{head} — {employer}"
        lines.append(head)
        lines.append(url)
    elif employer:
        lines.append(f"Работодатель: {employer}")

    # Actionable content per type.
    if type_ == "recruiter_question":
        qtext = payload.get("question_text")
        questions = payload.get("questions") or []
        if qtext:
            lines.append(f"\n💬 Рекрутёр: {_truncate(str(qtext), 400)}")
        if questions:
            lines.append("\nВопросы от ИИ к тебе:")
            for i, q in enumerate(questions, 1):
                lines.append(f"{i}. {q}")
    elif type_ == "recruiter_draft":
        qtext = payload.get("question_text")
        draft = payload.get("draft_text")
        if qtext:
            lines.append(f"\n💬 Рекрутёр: {_truncate(str(qtext), 400)}")
        if draft:
            lines.append(f"\n📝 Черновик ответа:\n{_truncate(str(draft), 600)}")
    elif type_ == "form_approval":
        # answers is a list[{question, answer, ...}] — show Q→A pairs.
        answers = payload.get("answers")
        if isinstance(answers, list) and answers:
            lines.append("\nОтветы анкеты:")
            for i, a in enumerate(answers, 1):
                if isinstance(a, dict):
                    q = a.get("question") or a.get("q") or ""
                    ans = a.get("answer") or a.get("value") or ""
                    if q:
                        lines.append(f"{i}. {_truncate(str(q), 200)}: {_truncate(str(ans), 200)}")
        letter = payload.get("letter")
        if letter:
            lines.append(f"\n✉️ Сопроводительное:\n{_truncate(str(letter), 400)}")
    elif type_ == "recruiter_todo":
        detail = payload.get("detail")
        link = payload.get("link")
        if detail:
            lines.append(f"\n{_truncate(str(detail), 400)}")
        if link:
            lines.append(f"🔗 {link}")

    # Remaining fields, skipping the ones already shown above + noise.
    shown = {
        "vacancy_id", "vacancy_title", "vacancy_name", "employer", "employer_name",
        "negotiation_id", "draft_id", "question_id", "todo_id", "answers", "letter",
        "draft_text", "question_text", "questions", "reason", "title", "detail", "link",
    }
    for key, value in payload.items():
        if key in shown:
            continue
        if value is None or value == "":
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _inline_keyboard(type_: str, payload: dict[str, Any]) -> dict | None:
    """Build an InlineKeyboardMarkup for actionable types. None = plain text.

    Callback data is ``<kind>:<entity_id>`` — parsed by the inbound loop.
    """
    if type_ == "recruiter_question":
        qid = payload.get("question_id")
        if not qid:
            return None
        return {
            "inline_keyboard": [[
                {"text": "✏️ Ответить", "callback_data": f"qans:{qid}"},
                {"text": "🗑 Пропустить", "callback_data": f"qskip:{qid}"},
            ]]
        }
    if type_ == "recruiter_draft":
        did = payload.get("draft_id")
        if not did:
            return None
        return {
            "inline_keyboard": [[
                {"text": "✅ Отправить", "callback_data": f"dsend:{did}"},
                {"text": "✏️ Изменить", "callback_data": f"dedit:{did}"},
                {"text": "❌ Отклонить", "callback_data": f"ddisc:{did}"},
            ]]
        }
    if type_ == "form_approval":
        fid = payload.get("draft_id")
        if not fid:
            return None
        return {
            "inline_keyboard": [[
                {"text": "✅ Подтвердить", "callback_data": f"fsend:{fid}"},
                {"text": "❌ Отклонить", "callback_data": f"fdisc:{fid}"},
            ]]
        }
    if type_ == "recruiter_todo":
        tid = payload.get("todo_id")
        if not tid:
            return None
        return {
            "inline_keyboard": [[
                {"text": "✅ Выполнено", "callback_data": f"tdone:{tid}"},
                {"text": "🗑 Скрыть", "callback_data": f"tdisc:{tid}"},
            ]]
        }
    return None


# --- outbound send -----------------------------------------------------------

def push_sync(user_id: str, type_: str, payload: dict[str, Any]) -> None:
    """Send one notification to the configured Telegram chat. Swallows errors.

    Called from notifications.notify() in a worker thread. Cheap and best-effort:
    Telegram is an auxiliary channel, not a primary store.
    """
    if not settings.TELEGRAM_NOTIFY_ENABLED:
        return
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    chat_id = settings.TELEGRAM_CHAT_ID.strip()
    if not token or not chat_id:
        return

    text = _format_message(type_, payload)
    if text is None:
        return

    body: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }
    kb = _inline_keyboard(type_, payload)
    if kb is not None:
        body["reply_markup"] = kb

    url = f"{API_BASE}/bot{token}/sendMessage"
    try:
        resp = httpx.post(url, json=body, timeout=10.0)
        if resp.status_code >= 400:
            logger.warning(
                "telegram: sendMessage returned %s: %s",
                resp.status_code,
                resp.text[:200],
            )
    except Exception:
        logger.warning("telegram: push failed", exc_info=True)


async def send_test() -> tuple[bool, str]:
    """Manual connectivity check used by the debug endpoint / first-run test.

    Returns (ok, message). Awaited from request context, so it owns its own httpx
    call - kept async on purpose.
    """
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    chat_id = settings.TELEGRAM_CHAT_ID.strip()
    if not token:
        return False, "TELEGRAM_BOT_TOKEN не задан"
    if not chat_id:
        return False, "TELEGRAM_CHAT_ID не задан"

    url = f"{API_BASE}/bot{token}/sendMessage"
    try:
        resp = await httpx.AsyncClient(timeout=10.0).post(
            url,
            json={
                "chat_id": chat_id,
                "text": "✅ Otclick: уведомления Telegram подключены.",
                "disable_web_page_preview": True,
            },
        )
    except Exception as ex:
        return False, f"сетевая ошибка: {ex}"

    if resp.status_code >= 400:
        try:
            body = resp.json()
            desc = body.get("description") or resp.text[:200]
        except Exception:
            desc = resp.text[:200]
        return False, f"Telegram API {resp.status_code}: {desc}"
    return True, "ok"


# --- inbound bot (long polling) ----------------------------------------------

# Pending-input state machine: when the user taps "Ответить"/"Изменить", we
# record what we're waiting for, so the next free-text message is routed.
# Keys are chat_id strings; values are {"kind": ..., "entity_id": ...}.
_pending: dict[str, dict[str, str]] = {}

_bot_task: asyncio.Task | None = None
_user_id_cache: str | None = None  # single-user mode: resolve once

# How long to hold the "waiting for user text" state before it lapses.
PENDING_TTL_S = 600


async def _resolve_user_id() -> str | None:
    """Single-user mode: the bot serves the one configured hh account.

    We resolve the user once from profiles (any user with worker_enabled or a
    valid plan) and cache it. This matches the existing single-global-chat
    push model — no per-user binding flow needed.
    """
    global _user_id_cache
    if _user_id_cache:
        return _user_id_cache
    from app.services.worker_control import active_user_flags
    loop = asyncio.get_running_loop()
    flags = await loop.run_in_executor(None, active_user_flags)
    if flags:
        # Pick the first (and typically only) active user.
        _user_id_cache = next(iter(flags))
        return _user_id_cache
    return None


async def _tg_request(token: str, method: str, **params: Any) -> dict | None:
    url = f"{API_BASE}/bot{token}/{method}"
    try:
        resp = await httpx.AsyncClient(timeout=35.0).post(url, json=params)
    except Exception:
        logger.warning("telegram: %s request failed", method, exc_info=True)
        return None
    if resp.status_code >= 400:
        logger.warning("telegram: %s returned %s: %s", method, resp.status_code, resp.text[:200])
        return None
    try:
        return resp.json()
    except Exception:
        return None


async def _answer_callback(token: str, chat_id: str, callback_id: str, text: str) -> None:
    """Answer a callback_query (closes the loading spinner on the button)."""
    await _tg_request(token, "answerCallbackQuery", callback_query_id=callback_id, text=text)


async def _send_text(token: str, chat_id: str, text: str, reply_to: int | None = None) -> None:
    body: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_to is not None:
        body["reply_to_message_id"] = reply_to
    await _tg_request(token, "sendMessage", **body)


async def _handle_callback(token: str, chat_id: str, cb_id: str, data: str, user_id: str) -> None:
    """Dispatch a button press to the matching service function."""
    kind, _, entity_id = data.partition(":")
    if not entity_id:
        await _answer_callback(token, chat_id, cb_id, "плохой запрос")
        return

    try:
        if kind == "qans":
            # Start free-text answer mode; user will send N messages (one per question).
            from app.services import recruiter as svc
            row = await svc.list_questions(user_id)
            target = next((r for r in row if r["id"] == entity_id), None)
            if not target:
                await _answer_callback(token, chat_id, cb_id, "вопрос уже неактивен")
                return
            q_count = len(target.get("questions") or [])
            _pending[chat_id] = {"kind": "qans", "entity_id": entity_id, "left": str(q_count)}
            await _answer_callback(token, chat_id, cb_id, "жду ответы")
            qs = target.get("questions") or []
            await _send_text(
                token, chat_id,
                f"Напиши ответ{'ы' if q_count > 1 else ''} одним сообщением"
                f"{' — по одному на вопрос' if q_count > 1 else ''}:\n"
                + "\n".join(f"{i+1}. {q}" for i, q in enumerate(qs))
            )
        elif kind == "qskip":
            from app.services import recruiter as svc
            await svc.discard_question(user_id, entity_id)
            await _answer_callback(token, chat_id, cb_id, "❌ пропущено")
        elif kind == "dsend":
            from app.services import recruiter as svc
            await svc.send_draft(user_id, entity_id, message=None)
            await _answer_callback(token, chat_id, cb_id, "✅ отправлено рекрутёру")
        elif kind == "dedit":
            _pending[chat_id] = {"kind": "dedit", "entity_id": entity_id}
            await _answer_callback(token, chat_id, cb_id, "жду новый текст")
            await _send_text(token, chat_id, "Напиши новый текст ответа одним сообщением:")
        elif kind == "ddisc":
            from app.services import recruiter as svc
            await svc.discard_draft(user_id, entity_id)
            await _answer_callback(token, chat_id, cb_id, "❌ отклонено")
        elif kind == "fsend":
            from app.services import form_drafts
            status, err = await form_drafts.approve(user_id, entity_id, answers=None, letter=None)
            if status == "form_sent":
                await _answer_callback(token, chat_id, cb_id, "✅ анкета отправлена")
            else:
                await _answer_callback(token, chat_id, cb_id, f"ошибка: {err or status}")
        elif kind == "fdisc":
            from app.services import form_drafts
            await form_drafts.discard(user_id, entity_id)
            await _answer_callback(token, chat_id, cb_id, "❌ анкета отклонена")
        elif kind == "tdone":
            from app.services import recruiter as svc
            await svc.mark_todo(user_id, entity_id, "done")
            await _answer_callback(token, chat_id, cb_id, "✅ выполнено")
        elif kind == "tdisc":
            from app.services import recruiter as svc
            await svc.mark_todo(user_id, entity_id, "dismissed")
            await _answer_callback(token, chat_id, cb_id, "🗑 скрыто")
        else:
            await _answer_callback(token, chat_id, cb_id, "неизвестное действие")
    except Exception as ex:
        logger.warning("telegram: callback %s failed", kind, exc_info=True)
        await _answer_callback(token, chat_id, cb_id, f"ошибка: {ex}")


async def _handle_text(token: str, chat_id: str, text: str, user_id: str) -> None:
    """A free-text message — the answer to a pending question or an edited draft."""
    pending = _pending.pop(chat_id, None)
    if not pending:
        await _send_text(
            token, chat_id,
            "Я присылаю уведомления от Otclick. Чтобы ответить — нажми кнопку под "
            "сообщением с вопросом или черновиком.",
        )
        return
    try:
        if pending["kind"] == "qans":
            from app.services import recruiter as svc
            # Split by newlines; drop empties.
            answers = [p.strip() for p in text.split("\n") if p.strip()]
            # One line for a multi-question set → fan out the same answer to all
            # questions (the common case: the user gives one answer that covers
            # all). submit_answers validates len == len(questions).
            need = int(pending.get("left") or "1")
            if len(answers) == 1 and need > 1:
                answers = answers * need
            await svc.submit_answers(user_id, pending["entity_id"], answers)
            await _send_text(
                token, chat_id,
                "✅ Ответ записан. ИИ-агент подхватит и продолжит переписку.",
            )
        elif pending["kind"] == "dedit":
            from app.services import recruiter as svc
            await svc.send_draft(user_id, pending["entity_id"], message=text)
            await _send_text(token, chat_id, "✅ Изменённый ответ отправлен рекрутёру.")
    except ValueError as ex:
        await _send_text(token, chat_id, f"⚠️ {ex}\nПопробуй ещё раз или ответь в веб-интерфейсе.")
        # Re-arm pending so the user can retry.
        _pending[chat_id] = pending
    except Exception as ex:
        logger.warning("telegram: text handler failed", exc_info=True)
        await _send_text(token, chat_id, f"⚠️ Ошибка: {ex}")


async def _process_update(token: str, update: dict) -> None:
    user_id = await _resolve_user_id()
    if not user_id:
        logger.warning("telegram: no active user — dropping update")
        return

    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = str((cq.get("message") or {}).get("chat", {}).get("id") or "")
        cb_id = cq.get("id") or ""
        data = cq.get("data") or ""
        if chat_id:
            await _handle_callback(token, chat_id, cb_id, data, user_id)
        return

    msg = update.get("message") or {}
    chat_id = str(msg.get("chat", {}).get("id") or "")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return
    # Only serve the configured chat.
    if chat_id != settings.TELEGRAM_CHAT_ID.strip():
        return
    await _handle_text(token, chat_id, text, user_id)


async def _poll_loop(stop_event: asyncio.Event) -> None:
    """Long-poll getUpdates forever until stop_event is set."""
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    if not token or not settings.TELEGRAM_BOT_ENABLED:
        logger.info("telegram bot: inbound polling disabled (no token or TELEGRAM_BOT_ENABLED=False)")
        return
    # Drop any updates that arrived before we started — stale buttons make no sense.
    offset = 0
    logger.info("telegram bot: inbound polling started")
    while not stop_event.is_set():
        params: dict[str, Any] = {"timeout": 25}
        if offset:
            params["offset"] = offset
        try:
            data = await _tg_request(token, "getUpdates", **params)
        except Exception:
            logger.warning("telegram: getUpdates failed", exc_info=True)
            await asyncio.sleep(5)
            continue
        if data is None:
            await asyncio.sleep(2)
            continue
        if not data.get("ok"):
            logger.warning("telegram: getUpdates not ok: %s", str(data)[:200])
            await asyncio.sleep(5)
            continue
        for update in data.get("result") or []:
            offset = update.get("update_id", 0) + 1
            try:
                await _process_update(token, update)
            except Exception:
                logger.warning("telegram: update processing failed", exc_info=True)
    logger.info("telegram bot: inbound polling stopped")


def start_bot_loop(stop_event: asyncio.Event) -> None:
    """Start the long-poll task. Safe to call once at worker startup."""
    global _bot_task
    if _bot_task is not None and not _bot_task.done():
        return
    if not settings.TELEGRAM_BOT_ENABLED:
        logger.info("telegram bot: TELEGRAM_BOT_ENABLED is False — not starting")
        return
    _bot_task = asyncio.create_task(_poll_loop(stop_event))


async def stop_bot_loop() -> None:
    global _bot_task
    if _bot_task is None:
        return
    _bot_task.cancel()
    try:
        await _bot_task
    except (asyncio.CancelledError, Exception):
        pass
    _bot_task = None
