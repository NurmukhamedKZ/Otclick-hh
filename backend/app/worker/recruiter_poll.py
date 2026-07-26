"""Poll recruiter chats and run the AI agent. Called once per runner loop iter.

Reads chats from chatik (the legacy negotiations API is frozen and misses new
messages — bot questions, our replies, and a real recruiter writing after the
robot leaves). Replies are still POSTed via the legacy messages API by the
agent tools — those land in the chatik chat.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from app.services import chatik, recruiter
from app.services.hh_credentials import load_api_client, persist_if_refreshed
from app.worker import throttle

logger = logging.getLogger(__name__)
_rng = random.Random()

# Negotiation states where the chat is closed / read-only: a reply can't be sent
# and there is nothing for the agent to do. Skip these before running the LLM
# (the agent would otherwise waste tokens "handling" a rejection). Mirrors the
# /chats UI READONLY_STATES — the rejection signal lives on the negotiation
# state.id (legacy negotiations API), NOT in the chat messages.
SKIP_STATES = frozenset({
    "discard", "discard_by_employer", "discard_after_interview",
    "discard_by_applicant", "discard_visited", "discard_no_appearance",
    "discard_to_other_vacancy", "hidden", "archive",
})
_MAX_NEG_PAGES = 15

# The state list is only used to skip rejected/archived chats — it changes on
# the scale of days, while the poll runs every 2 minutes. Without this cache
# every poll pulled up to 1500 negotiations per user from hh.
_STATES_TTL_S = 30 * 60
_states_cache: dict[str, tuple[float, dict[str, str]]] = {}


async def _negotiation_states(client, user_id: str) -> dict[str, str]:
    """nid -> state.id from the legacy negotiations list (same source the /chats
    UI uses for the «Отказ» tag). Cached per user for _STATES_TTL_S. Best-effort:
    returns {} on any failure so the poll stays fail-open (a fetch error must not
    stop the agent from replying)."""
    cached = _states_cache.get(user_id)
    if cached and time.monotonic() - cached[0] < _STATES_TTL_S:
        return cached[1]
    loop = asyncio.get_running_loop()
    out: dict[str, str] = {}
    try:
        page = 0
        while page < _MAX_NEG_PAGES:
            data = await loop.run_in_executor(
                None,
                lambda p=page: client.get(
                    "negotiations", order_by="updated_at", page=p, per_page=100
                ),
            )
            for it in data.get("items", []):
                sid = (it.get("state") or {}).get("id")
                if sid:
                    out[str(it.get("id"))] = str(sid)
            if page + 1 >= int(data.get("pages", 1)):
                break
            page += 1
    except Exception:
        logger.warning("recruiter poll: negotiation-state fetch failed", exc_info=True)
        return {}
    _states_cache[user_id] = (time.monotonic(), out)
    return out


async def poll_recruiter_chats(user_id: str, agent) -> None:
    """For each recent chat whose newest message is an unhandled employer/bot
    message, invoke the agent. Errors are logged and never crash the loop."""
    chats = await chatik.recent_chats(user_id)
    if chats is None:
        logger.warning("recruiter poll: no web session for %s — skipping", user_id)
        return
    try:
        client = await load_api_client(user_id)
    except Exception:
        logger.warning("recruiter poll: cannot load creds for %s", user_id, exc_info=True)
        return
    original = client.access_token
    try:
        states = await _negotiation_states(client, user_id)
        for ref in chats:
            try:
                handled = await _process_chat(user_id, agent, client, ref, states)
            except Exception:
                # Do NOT advance the cursor — retry on the next poll.
                logger.warning(
                    "recruiter poll: chat %s failed for %s", ref.get("nid"), user_id,
                    exc_info=True,
                )
                continue
            if handled:
                await asyncio.sleep(throttle.next_delay(_rng))
    finally:
        await persist_if_refreshed(user_id, client, original)


def _history(msgs: list[dict]) -> list[tuple[str, str]]:
    """chatik messages → LangChain (role, content) tuples for agent context."""
    out: list[tuple[str, str]] = []
    for m in msgs:
        if not m["text"]:
            continue
        out.append(("user" if m["from_employer"] else "assistant", m["text"]))
    return out


async def _process_chat(user_id: str, agent, client, ref: dict, states: dict[str, str]) -> bool:
    """Returns True when the agent acted (so the caller throttles before the next
    chat). Cursor (`last_handled_message_id`) is the dedup key — only the newest
    employer message, when unhandled, triggers a reply."""
    nid = ref["nid"]
    # Rejected / closed negotiation (отказ, archived, …) → don't run the agent.
    if states.get(nid) in SKIP_STATES:
        return False
    last_id = ref.get("last_id")
    if last_id is None:
        return False
    # Newest message is ours → waiting on the employer, nothing to do.
    if ref.get("last_participant_id") == ref.get("applicant_id"):
        return False
    cursor = await recruiter.get_cursor(user_id, nid)
    if cursor is not None and str(cursor) == str(last_id):
        return False  # already handled this message

    msgs = await chatik.chat_messages(user_id, ref["chat_id"], ref["applicant_id"])
    if not msgs:
        return False
    # Newest employer-authored text message (bot or real recruiter).
    target = next((m for m in reversed(msgs) if m["from_employer"] and m["text"]), None)
    if target is None:
        return False
    if cursor is not None and str(cursor) == str(target["id"]):
        return False

    vacancy_id = ref.get("vacancy_id")
    mid = target["id"]
    if target["buttons"]:
        # Robot-recruiter quick-reply: the agent must pick an exact button label
        # (free text loops) via answer_recruiter_question, or escalate.
        await agent.answer_recruiter_choice(
            nid, mid, _history(msgs), client, target["text"], target["buttons"]
        )
    else:
        # Free text — from a real recruiter OR from the hh bot (it also asks open
        # questions without buttons; skipping those dropped them silently).
        # The agent decides: reply / escalate / todo, or SKIP on a rejection.
        await agent.answer_recruiter(
            nid, mid, _history(msgs), client, question_text=target["text"] or None
        )
    await recruiter.upsert_cursor(user_id, nid, mid, vacancy_id=vacancy_id)
    return True
