"""hh.ru chatik web API — the real source of truth for recruiter chats.

The legacy `GET /negotiations/{nid}/messages` API is frozen: it does NOT reflect
new chat activity (bot questions, our own replies, and — critically — messages
from a real recruiter after the robot leaves the chat). hh moved chats to
`chatik.hh.ru/chatik/api/*`; that backend has everything. Both the worker
(recruiter agent) and the /chats UI read messages from here.

Read over the stored web session (the same cookies the form-filler uses; cookies
for `.hh.ru` cover `chatik.hh.ru`). No browser. Replies are still POSTed via the
legacy messages API — those DO land in the chatik chat (verified).

Endpoints:
  GET /chatik/api/chats      → 20 chats per page; we walk `page` until
                               `hasNextPage` is false to cover every active chat.
                               item.resources.NEGOTIATION_TOPIC[0] = legacy nid,
                               item.id = chatId, currentParticipantId = my id,
                               lastMessage = newest message (drives the trigger).
  GET /chatik/api/chat_data  → full message list incl. actions.text_buttons.
"""

from __future__ import annotations

import asyncio
import logging

from app.services.form_filler import (
    WebSessionExpired,
    load_web_session,
    report_dead_session,
    session_looks_dead,
)

logger = logging.getLogger(__name__)

CHATIK = "https://chatik.hh.ru/chatik/api"
_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Referer": "https://hh.ru/chat"}


# --- sync helpers (run inside an executor) -----------------------------------

# /chats returns 20 per page; walk pages so the agent sees every active chat,
# not just the 20 most recent. Cap as a safety net against a runaway loop.
_MAX_CHAT_PAGES = 15


def _chat_items(session) -> list[dict]:
    items: list[dict] = []
    page = 0
    while page < _MAX_CHAT_PAGES:
        r = session.get(
            f"{CHATIK}/chats",
            params={"do_not_track_session_events": "true", "page": page},
            headers=_HEADERS,
            timeout=15,
        )
        if session_looks_dead(r):
            raise WebSessionExpired(f"chatik /chats rejected the session ({r.status_code})")
        r.raise_for_status()
        chats = r.json().get("chats") or {}
        items.extend(chats.get("items") or [])
        if not chats.get("hasNextPage"):
            break
        page += 1
    return items


def _chats_map(session) -> dict[str, dict]:
    """nid (NEGOTIATION_TOPIC) -> chat ref with last-message trigger info.

    Walks all pages (see _chat_items) so every active chat is present, not just
    the 20 most recent."""
    out: dict[str, dict] = {}
    for it in _chat_items(session):
        applicant_id = str(it.get("currentParticipantId") or "")
        lm = it.get("lastMessage") or {}
        vacancy = (it.get("resources") or {}).get("VACANCY") or []
        ref = {
            "chat_id": str(it["id"]),
            "applicant_id": applicant_id,
            "vacancy_id": str(vacancy[0]) if vacancy else None,
            "last_id": str(lm["id"]) if lm.get("id") is not None else None,
            "last_participant_id": (
                str(lm["participantId"]) if lm.get("participantId") is not None else None
            ),
            "last_is_bot": bool((lm.get("participantDisplay") or {}).get("isBot")),
        }
        for topic in (it.get("resources") or {}).get("NEGOTIATION_TOPIC") or []:
            out[str(topic)] = {"nid": str(topic), **ref}
    return out


def _chat_data(session, chat_id: str, applicant_id: str) -> dict:
    r = session.get(
        f"{CHATIK}/chat_data",
        params={
            "chatId": chat_id,
            "applicantId": applicant_id,
            "do_not_track_session_events": "true",
        },
        headers={**_HEADERS, "Referer": f"https://hh.ru/chat/{chat_id}"},
        timeout=15,
    )
    if session_looks_dead(r):
        raise WebSessionExpired(f"chatik /chat_data rejected the session ({r.status_code})")
    r.raise_for_status()
    return r.json()


def _norm(m: dict, applicant_id: str) -> dict:
    """Normalize a chatik message. `from_employer` covers both the bot and a
    real recruiter (anyone who is not me)."""
    pd = m.get("participantDisplay") or {}
    buttons = [
        b["text"] for b in (m.get("actions") or {}).get("text_buttons") or [] if b.get("text")
    ]
    return {
        "id": str(m.get("id")),
        "text": (m.get("text") or "").strip(),
        "created_at": m.get("creationTime"),
        "from_employer": str(m.get("participantId")) != str(applicant_id),
        "is_bot": bool(pd.get("isBot")),
        "name": pd.get("name"),
        "type": m.get("type"),
        "buttons": buttons,
    }


def _messages(session, chat_id: str, applicant_id: str) -> list[dict]:
    data = _chat_data(session, chat_id, applicant_id)
    items = (((data or {}).get("chat") or {}).get("messages") or {}).get("items") or []
    return [_norm(m, applicant_id) for m in items]


# --- async API ---------------------------------------------------------------

async def recent_chats(user_id: str) -> list[dict] | None:
    """Recent chat refs (nid, chat_id, applicant_id, last-message info) for the
    worker's poll trigger. None when there is no web session (reconnect needed)."""
    loop = asyncio.get_running_loop()
    try:
        session = await load_web_session(user_id)
    except Exception:
        return None
    try:
        return await loop.run_in_executor(None, lambda: list(_chats_map(session).values()))
    except WebSessionExpired as ex:
        await report_dead_session(user_id, ex)
        return None
    except Exception:
        logger.warning("chatik: recent_chats failed for %s", user_id, exc_info=True)
        return None


async def chat_messages(user_id: str, chat_id: str, applicant_id: str) -> list[dict] | None:
    """Normalized messages for a known chat (the worker already has the ref from
    recent_chats — avoids re-listing). None on no web session / failure."""
    loop = asyncio.get_running_loop()
    try:
        session = await load_web_session(user_id)
    except Exception:
        return None
    try:
        return await loop.run_in_executor(
            None, lambda: _messages(session, chat_id, applicant_id)
        )
    except WebSessionExpired as ex:
        await report_dead_session(user_id, ex)
        return None
    except Exception:
        logger.warning("chatik: chat_messages failed chat=%s", chat_id, exc_info=True)
        return None


async def fetch_messages(user_id: str, nid: str) -> list[dict] | None:
    """Normalized messages for negotiation `nid` over chatik (resolves nid→chat
    via the chats list). For the /chats UI, which only has the nid. None when
    there is no web session or the chat is not in the recent list (caller falls
    back to the legacy API)."""
    loop = asyncio.get_running_loop()
    try:
        session = await load_web_session(user_id)
    except Exception:
        return None

    def _q():
        ref = _chats_map(session).get(str(nid))
        if not ref:
            return None
        return _messages(session, ref["chat_id"], ref["applicant_id"])

    try:
        return await loop.run_in_executor(None, _q)
    except WebSessionExpired as ex:
        await report_dead_session(user_id, ex)
        return None
    except Exception:
        logger.warning("chatik: fetch_messages failed for nid=%s", nid, exc_info=True)
        return None
