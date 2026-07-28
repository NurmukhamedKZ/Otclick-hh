"""Pull negotiation states from hh into applications.hh_state.

The apply pipeline only knows whether WE managed to send a response. Whether
the employer then invited or rejected lives on hh (`negotiations[].state.id` =
response | invitation | discard). Analytics needs it, so we mirror it.

Called on demand from the analytics endpoint, throttled by
profiles.negotiations_synced_at — nobody looking at the page, nobody paying
the hh requests.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.db.supabase import service_client
from app.services.hh_credentials import load_api_client, persist_if_refreshed

logger = logging.getLogger(__name__)

PER_PAGE = 100
MAX_PAGES = 5  # 500 most recently updated negotiations — enough for a 30d window
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


def _rows_from_items(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        vacancy = it.get("vacancy") or {}
        vid = vacancy.get("id")
        if not vid:
            continue
        out.append(
            {
                "vacancy_id": str(vid),
                "state": (it.get("state") or {}).get("id"),
                "viewed": bool(it.get("viewed_by_opponent")),
                "employer_name": ((vacancy.get("employer") or {}).get("name")),
            }
        )
    return out


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
    try:
        client = await load_api_client(user_id)
    except Exception:
        logger.info("negotiation_sync: no usable hh creds for %s — skip", user_id)
        return 0

    original_access = client.access_token
    changed = 0
    try:
        for page in range(MAX_PAGES):
            payload = await loop.run_in_executor(
                None,
                lambda p=page: client.get(
                    "negotiations", order_by="updated_at", page=p, per_page=PER_PAGE
                ),
            )
            items = payload.get("items") or [] if isinstance(payload, dict) else []
            if not items:
                break
            changed += await loop.run_in_executor(
                None, _persist, user_id, _rows_from_items(items)
            )
            pages_total = payload.get("pages")
            if pages_total is not None and page + 1 >= pages_total:
                break
            if len(items) < PER_PAGE:
                break
    except Exception:
        logger.warning("negotiation_sync failed for %s", user_id, exc_info=True)
    finally:
        await persist_if_refreshed(user_id, client, original_access)
        try:
            await loop.run_in_executor(None, _mark_synced, user_id)
        except Exception:  # pragma: no cover
            logger.exception("negotiation_sync: mark_synced failed for %s", user_id)

    logger.info("negotiation_sync: user=%s changed=%d", user_id, changed)
    return changed
