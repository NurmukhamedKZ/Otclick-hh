"""Recruiter chat browsing — list negotiations, fetch messages, send replies."""

from __future__ import annotations

import asyncio
import logging

from app.api.deps import get_current_user
from app.db.supabase import service_client
from app.schemas.recruiter import OkResponse, SendDraftRequest
from app.services import chatik
from app.services.hh_credentials import load_api_client, persist_if_refreshed
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chats", tags=["chats"])


class MarkReadRequest(BaseModel):
    nids: list[str] | None = None


def _chat_summary(item: dict) -> dict:
    vacancy = item.get("vacancy") or {}
    employer = vacancy.get("employer") or {}
    logo = (employer.get("logo_urls") or {}).get("90") or (employer.get("logo_urls") or {}).get("original")
    state = item.get("state") or {}
    counters = item.get("counters") or {}
    return {
        "id": str(item.get("id")),
        "vacancy_id": str(vacancy.get("id")) if vacancy.get("id") else None,
        "vacancy_name": vacancy.get("name"),
        "employer_name": employer.get("name"),
        "employer_logo": logo,
        "state_id": state.get("id"),
        "state_name": state.get("name"),
        "updated_at": item.get("updated_at") or item.get("created_at"),
        "unread": int(counters.get("unread_messages") or 0),
        "has_updates": bool(item.get("has_updates")),
    }


@router.get("")
async def list_chats(
    user_id: str = Depends(get_current_user),
    page: int = Query(0, ge=0),
    per_page: int = Query(50, ge=1, le=100),
    unread_only: bool = Query(False),
) -> dict:
    client = await load_api_client(user_id)
    original = client.access_token
    loop = asyncio.get_running_loop()
    try:
        try:
            data = await loop.run_in_executor(
                None,
                lambda: client.get(
                    "negotiations",
                    order_by="updated_at",
                    page=page,
                    per_page=per_page,
                ),
            )
        except Exception as ex:
            logger.warning("chats: list negotiations failed user=%s: %s", user_id, ex)
            raise HTTPException(status_code=502, detail="hh negotiations request failed") from ex
    finally:
        await persist_if_refreshed(user_id, client, original)

    items = [_chat_summary(it) for it in data.get("items", [])]
    if unread_only:
        items = [it for it in items if it["has_updates"]]
    return {
        "items": items,
        "page": data.get("page", page),
        "pages": data.get("pages", 1),
        "per_page": data.get("per_page", per_page),
        "found": data.get("found", len(items)),
    }


def _message(m: dict) -> dict:
    author = m.get("author") or {}
    return {
        "id": str(m.get("id")),
        "text": m.get("text") or "",
        "created_at": m.get("created_at"),
        "from_employer": author.get("participant_type") == "employer",
        "viewed_by_me": bool(m.get("viewed_by_me", True)),
    }


async def _load_response_letter(user_id: str, vacancy_id: str | None) -> dict | None:
    if not vacancy_id:
        return None

    def _q():
        return (
            service_client.table("applications")
            .select("cover_letter, applied_at, created_at")
            .eq("user_id", user_id)
            .eq("vacancy_id", vacancy_id)
            .limit(1)
            .execute()
        )

    res = await asyncio.get_running_loop().run_in_executor(None, _q)
    rows = res.data or []
    if not rows:
        return None
    row = rows[0]
    return {
        "id": f"response-{vacancy_id}",
        "text": (row.get("cover_letter") or "").strip(),
        "created_at": row.get("applied_at") or row.get("created_at"),
        "from_employer": False,
        "viewed_by_me": True,
        "kind": "response",
    }


async def _legacy_messages(user_id: str, negotiation_id: str) -> list[dict]:
    """Fallback when chatik has no web session: the (stale) legacy API."""
    client = await load_api_client(user_id)
    original = client.access_token
    loop = asyncio.get_running_loop()
    try:
        try:
            data = await loop.run_in_executor(
                None,
                lambda: client.get(f"negotiations/{negotiation_id}/messages"),
            )
        except Exception as ex:
            logger.warning("chats: messages fetch failed nid=%s: %s", negotiation_id, ex)
            raise HTTPException(status_code=502, detail="hh messages request failed") from ex
    finally:
        await persist_if_refreshed(user_id, client, original)
    return [_message(m) for m in data.get("items", [])]


@router.get("/{negotiation_id}/messages")
async def get_messages(
    negotiation_id: str,
    vacancy_id: str | None = Query(None),
    user_id: str = Depends(get_current_user),
) -> dict:
    # chatik is the source of truth (legacy API misses messages from a real
    # recruiter after the robot leaves). Fall back to legacy only when there is
    # no stored web session (chatik returns None).
    chat_msgs = await chatik.fetch_messages(user_id, negotiation_id)
    if chat_msgs is None:
        items = await _legacy_messages(user_id, negotiation_id)
    else:
        items = [
            {
                "id": m["id"],
                "text": m["text"],
                "created_at": m["created_at"],
                "from_employer": m["from_employer"],
                "viewed_by_me": True,
            }
            for m in chat_msgs
            if m["text"]
        ]

    db_letter: dict | None = None
    first_applicant_idx = next(
        (i for i, m in enumerate(items) if not m["from_employer"]), None
    )
    if first_applicant_idx is None:
        db_letter = await _load_response_letter(user_id, vacancy_id)
        if db_letter is not None:
            items.insert(0, db_letter)
    else:
        first = items[first_applicant_idx]
        first["kind"] = "response"
        if not first["text"].strip():
            db_letter = await _load_response_letter(user_id, vacancy_id)
            if db_letter and db_letter["text"]:
                first["text"] = db_letter["text"]

    return {"items": items}


@router.post("/read-all")
async def read_all(
    body: MarkReadRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    try:
        marked = await chatik.mark_all_read(user_id, body.nids)
    except Exception as ex:
        raise HTTPException(status_code=502, detail="hh mark-as-read failed") from ex
    return {"ok": True, "marked": marked}


@router.post("/{negotiation_id}/messages", response_model=OkResponse)
async def send_message(
    negotiation_id: str,
    body: SendDraftRequest,
    user_id: str = Depends(get_current_user),
) -> OkResponse:
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is empty")
    client = await load_api_client(user_id)
    original = client.access_token
    loop = asyncio.get_running_loop()
    try:
        try:
            await loop.run_in_executor(
                None,
                lambda: client.post(
                    f"negotiations/{negotiation_id}/messages", {"message": text}
                ),
            )
        except Exception as ex:
            logger.warning("chats: send failed nid=%s: %s", negotiation_id, ex)
            raise HTTPException(status_code=502, detail="hh send-message failed") from ex
    finally:
        await persist_if_refreshed(user_id, client, original)
    return OkResponse()
