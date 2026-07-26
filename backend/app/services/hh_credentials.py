"""Load/persist user's hh API credentials (decrypt → ApiClient → re-encrypt on refresh)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.db.supabase import service_client
from app.hh.client import ApiClient
from app.hh.user_agent import generate_android_useragent
from app.services.hh_auth import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)


class HHCredentialsInvalid(Exception):
    """Stored hh credentials marked invalid (token dead, banned, etc.)."""

    def __init__(self, user_id: str, reason: str | None) -> None:
        super().__init__(f"hh credentials invalid for {user_id}: {reason}")
        self.user_id = user_id
        self.reason = reason


def _load_row(user_id: str) -> dict:
    res = (
        service_client.table("hh_credentials")
        .select(
            "access_token_encrypted,refresh_token_encrypted,expires_at,"
            "invalid_at,invalid_reason"
        )
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    data = res.data if res else None
    if not data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="hh account not connected",
        )
    if data.get("invalid_at"):
        raise HHCredentialsInvalid(user_id, data.get("invalid_reason"))
    return data


def _mark_invalid_sync(user_id: str, reason: str) -> None:
    service_client.table("hh_credentials").update(
        {
            "invalid_at": datetime.now(timezone.utc).isoformat(),
            "invalid_reason": reason,
        }
    ).eq("user_id", user_id).execute()


async def mark_invalid(user_id: str, reason: str) -> None:
    drop_cached_client(user_id)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _mark_invalid_sync, user_id, reason)


def _build_client(row: dict) -> ApiClient:
    expires_at = row.get("expires_at")
    expires_ts = 0
    if isinstance(expires_at, str):
        dt = datetime.fromisoformat(expires_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        expires_ts = int(dt.timestamp())
    return ApiClient(
        user_agent=generate_android_useragent(),
        access_token=decrypt_token(row["access_token_encrypted"]),
        refresh_token=decrypt_token(row["refresh_token_encrypted"]),
        access_expires_at=expires_ts,
    )


def _persist_refreshed(user_id: str, client: ApiClient) -> None:
    service_client.table("hh_credentials").update({
        "access_token_encrypted": encrypt_token(client.access_token),
        "refresh_token_encrypted": encrypt_token(client.refresh_token),
        "expires_at": datetime.fromtimestamp(
            client.access_expires_at, tz=timezone.utc
        ).isoformat(),
        "last_refreshed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("user_id", user_id).execute()


# Every hh call used to rebuild the client: a Supabase round trip, two Fernet
# decrypts and a fresh TCP+TLS handshake. Short TTL so `invalid_at` (set by
# mark_invalid) still takes effect quickly on paths that don't call
# drop_cached_client themselves.
_CLIENT_TTL_S = 60.0
_clients: dict[str, tuple[float, ApiClient]] = {}


def drop_cached_client(user_id: str) -> None:
    _clients.pop(user_id, None)


async def load_api_client(user_id: str) -> ApiClient:
    """Build ApiClient from stored creds. Persists tokens if ApiClient auto-refreshes."""
    cached = _clients.get(user_id)
    if cached and time.monotonic() - cached[0] < _CLIENT_TTL_S:
        return cached[1]
    loop = asyncio.get_running_loop()
    row = await loop.run_in_executor(None, _load_row, user_id)
    client = await loop.run_in_executor(None, _build_client, row)
    _clients[user_id] = (time.monotonic(), client)
    return client


async def persist_if_refreshed(
    user_id: str, client: ApiClient, original_access: str
) -> None:
    if client.access_token != original_access:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _persist_refreshed, user_id, client)
