"""Pull negotiation states from hh into applications.hh_state.

The apply pipeline only knows whether WE managed to send a response. Whether
the employer then invited or rejected lives on hh. Analytics needs it, so we
mirror it — read off the negotiations page (web.list_negotiations), which
normalises hh's wording to response | invitation | discard.

Called on demand from the analytics endpoint, throttled by
profiles.negotiations_synced_at — nobody looking at the page, nobody paying
the hh requests.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.db.supabase import service_client
from app.hh import web

logger = logging.getLogger(__name__)

# The web negotiations page serves 20 topics per page (observed: total=841 over
# pageCount=43), where the old API took per_page=100. Keep the same ~500-row
# window the 30d analytics needs by paging 25 times instead of 5.
PER_PAGE = 20
MAX_PAGES = 25
MIN_SYNC_INTERVAL_S = 300


def _due(user_id: str) -> bool:
    res = (
        service_client.table("profiles")
        .select("negotiations_synced_at")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    last = (res.data or {}).get("negotiations_synced_at") if res else None
    if not last:
        return True
    try:
        ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(UTC) - ts > timedelta(seconds=MIN_SYNC_INTERVAL_S)


def _mark_synced(user_id: str) -> None:
    service_client.table("profiles").update(
        {"negotiations_synced_at": datetime.now(UTC).isoformat()}
    ).eq("id", user_id).execute()


def _persist(user_id: str, rows: list[dict]) -> int:
    """Write only actual changes — hh_state_at must mean 'when it changed'."""
    if not rows:
        return 0
    vids = [r["vacancy_id"] for r in rows]
    res = (
        service_client.table("applications")
        .select("vacancy_id,hh_state,hh_viewed,employer_name")
        .eq("user_id", user_id)
        .in_("vacancy_id", vids)
        .execute()
    )
    current = {r["vacancy_id"]: r for r in (res.data or [])}
    now = datetime.now(UTC).isoformat()
    changed = 0
    for r in rows:
        existing = current.get(r["vacancy_id"])
        if existing is None:
            continue  # negotiation we never created (manual apply on hh)
        patch: dict = {}
        if r["state"] and r["state"] != existing.get("hh_state"):
            patch["hh_state"] = r["state"]
            patch["hh_state_at"] = now
        if r["viewed"] != bool(existing.get("hh_viewed")):
            patch["hh_viewed"] = r["viewed"]
        if r["employer_name"] and not existing.get("employer_name"):
            patch["employer_name"] = r["employer_name"]
        if not patch:
            continue
        service_client.table("applications").update(patch).eq("user_id", user_id).eq(
            "vacancy_id", r["vacancy_id"]
        ).execute()
        changed += 1
    return changed


async def sync_states(user_id: str, force: bool = False) -> int:
    """Refresh hh_state for this user's applications. Returns rows changed.

    Never raises — analytics must render even when hh is unreachable or the
    user has not connected an account.
    """
    loop = asyncio.get_running_loop()
    if not force and not await loop.run_in_executor(None, _due, user_id):
        return 0
    changed = 0
    try:
        for page in range(MAX_PAGES):
            rows = await web.list_negotiations(user_id, page=page)
            if not rows:
                break
            changed += await loop.run_in_executor(None, _persist, user_id, rows)
            if len(rows) < PER_PAGE:
                break
    except Exception:
        logger.warning("negotiation_sync failed for %s", user_id, exc_info=True)
    finally:
        try:
            await loop.run_in_executor(None, _mark_synced, user_id)
        except Exception:  # pragma: no cover
            logger.exception("negotiation_sync: mark_synced failed for %s", user_id)

    logger.info("negotiation_sync: user=%s changed=%d", user_id, changed)
    return changed
