"""hh access-token refresh: force-refresh one user + daily near-expiry cron batch.

hh refresh token is single-use and only usable after the access token expires,
so the cron only refreshes creds whose expires_at is within REFRESH_THRESHOLD_DAYS
(not every active user every day). A successful refresh yields a fresh
access+refresh pair, persisted via persist_if_refreshed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import requests

from app.config import settings
from app.db.supabase import service_client
from app.hh import errors
from app.services.hh_credentials import (
    HHCredentialsInvalid,
    load_api_client,
    mark_invalid,
    persist_if_refreshed,
)

logger = logging.getLogger(__name__)


async def refresh_user(user_id: str) -> dict:
    """Refresh one user's access token via refresh_token grant.

    Raises HTTPException(409) if not connected, HHCredentialsInvalid if already
    marked invalid (both surface from load_api_client). Returns a result dict:
      {"user_id", "status": "refreshed" | "invalid" | "error", "error"?}
    hh rejection (token dead) → mark_invalid + "invalid". Network blip → "error"
    (creds left intact, cron retries next run).
    """
    client = await load_api_client(user_id)
    original_access = client.access_token
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, client.refresh_access_token)
    except errors.BadResponse as ex:
        # hh rejected the refresh token — dead/revoked. Mark invalid so worker stops.
        await mark_invalid(user_id, f"refresh_failed: {ex}")
        logger.warning("refresh rejected for %s: %s", user_id, ex)
        return {"user_id": user_id, "status": "invalid", "error": str(ex)}
    except requests.RequestException as ex:
        # Transient (network/timeout) — don't mark invalid, retry next run.
        logger.warning("refresh transient error for %s: %s", user_id, ex)
        return {"user_id": user_id, "status": "error", "error": str(ex)}

    await persist_if_refreshed(user_id, client, original_access)
    logger.info("refreshed token for %s", user_id)
    return {"user_id": user_id, "status": "refreshed"}


def _select_due(threshold_days: int) -> list[dict]:
    cutoff = (datetime.now(UTC) + timedelta(days=threshold_days)).isoformat()
    res = (
        service_client.table("hh_credentials")
        .select("user_id,expires_at")
        .is_("invalid_at", None)
        .lte("expires_at", cutoff)
        .execute()
    )
    return [r for r in (res.data or []) if r.get("user_id")]


async def refresh_due(threshold_days: int | None = None) -> dict:
    """Refresh all active creds expiring within threshold_days. Cron entrypoint."""
    threshold = (
        threshold_days
        if threshold_days is not None
        else settings.REFRESH_THRESHOLD_DAYS
    )
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, _select_due, threshold)

    summary = {"due": len(rows), "refreshed": 0, "invalid": 0, "errors": 0}
    for row in rows:
        user_id = row["user_id"]
        try:
            result = await refresh_user(user_id)
        except HHCredentialsInvalid:
            summary["invalid"] += 1
            continue
        except Exception as ex:
            logger.exception("unexpected error refreshing %s: %s", user_id, ex)
            summary["errors"] += 1
            continue
        if result["status"] == "refreshed":
            summary["refreshed"] += 1
        elif result["status"] == "invalid":
            summary["invalid"] += 1
        else:
            summary["errors"] += 1

    logger.info("refresh_due done: %s", summary)
    return summary
