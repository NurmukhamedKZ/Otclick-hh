"""Worker heartbeat → DB.

The worker container has the in-memory queue; the API process does not.
The runner writes its state here so /api/worker/status can read it back.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app.db.supabase import service_client

logger = logging.getLogger(__name__)

_SENTINEL = object()


async def heartbeat(
    user_id: str,
    *,
    state: str | None = None,
    queued: int | None = None,
    today_count: int | None = None,
    next_run_at: datetime | None | object = _SENTINEL,
    last_error: str | None | object = _SENTINEL,
) -> None:
    payload: dict[str, Any] = {
        "user_id": user_id,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if state is not None:
        payload["state"] = state
    if queued is not None:
        payload["queued"] = queued
    if today_count is not None:
        payload["today_count"] = today_count
    if next_run_at is not _SENTINEL:
        payload["next_run_at"] = (
            next_run_at.isoformat() if isinstance(next_run_at, datetime) else None
        )
    if last_error is not _SENTINEL:
        payload["last_error"] = last_error  # may be None to clear

    loop = asyncio.get_running_loop()

    def _write() -> None:
        try:
            service_client.table("worker_runtime").upsert(
                payload, on_conflict="user_id"
            ).execute()
        except Exception:
            logger.warning("worker_runtime upsert failed for %s", user_id, exc_info=True)

    await loop.run_in_executor(None, _write)


async def get(user_id: str) -> dict | None:
    loop = asyncio.get_running_loop()

    def _read() -> dict | None:
        try:
            res = (
                service_client.table("worker_runtime")
                .select("*")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            data = res.data or []
            return data[0] if data else None
        except Exception:
            logger.warning("worker_runtime read failed for %s", user_id, exc_info=True)
            return None

    return await loop.run_in_executor(None, _read)
